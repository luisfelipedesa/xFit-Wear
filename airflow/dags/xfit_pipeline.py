"""Fluxos manuais para validar fontes e promover a carga historica xFit Wear."""

from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pendulum
from airflow.sdk import dag, task, get_current_context, Param

RAIZ = Path('/opt/xfit')


@task
def identificar_carga():
    contexto = get_current_context()
    identidade = f"{contexto['dag'].dag_id}:{contexto['run_id']}"
    return 'airflow-' + sha256(identidade.encode()).hexdigest()[:40]


@task(execution_timeout=timedelta(minutes=2))
def verificar_conexao():
    subprocess.run([sys.executable, '-B', str(RAIZ / 'src/carregar_postgres.py'),
                    '--verificar-conexao'], cwd=RAIZ, check=True)


@task(execution_timeout=timedelta(minutes=30))
def executar_pipeline(carga_id, somente_validar):
    modulo = 'validar_carga_airflow.py' if somente_validar else 'carregar_postgres.py'
    subprocess.run([sys.executable, '-B', str(RAIZ / 'src' / modulo),
                    '--carga-id', carga_id], cwd=RAIZ, check=True)
    return {'carga_id': carga_id,
            'carga_dw_id': None if somente_validar else 'dw-' + carga_id}


@dag(dag_id='xfit_validar_fontes', schedule=None,
     start_date=pendulum.datetime(2026, 10, 15, tz='America/Sao_Paulo'),
     catchup=False, max_active_runs=1, default_args={'retries': 0},
     is_paused_upon_creation=True, tags=['xfit', 'qualidade'],
     description='Auditoria, backup verificado, extracao, staging e qualidade local.')
def fluxo_validar_fontes():
    executar_pipeline(identificar_carga(), somente_validar=True)


@dag(dag_id='xfit_carga_dw', schedule=None,
     start_date=pendulum.datetime(2026, 10, 15, tz='America/Sao_Paulo'),
     catchup=False, max_active_runs=1, default_args={'retries': 0},
     is_paused_upon_creation=True, tags=['xfit', 'dw'],
     description='Valida fontes e promove staging e DW na mesma transacao.')
def fluxo_carga_dw():
    carga_id = identificar_carga()
    conexao = verificar_conexao()
    carga = executar_pipeline(carga_id, somente_validar=False)
    conexao >> carga


@task(execution_timeout=timedelta(minutes=10))
def receber_entrega(carga_id, unidade=None):
    data_referencia = get_current_context()['params'].get('data_referencia')
    if not data_referencia:
        raise ValueError('Informe data_referencia no disparo do fluxo')
    argumentos = [sys.executable, '-B', str(RAIZ / 'src/alimentar_datalake.py'),
                  '--carga-id', carga_id, '--data-referencia', data_referencia]
    if unidade:
        argumentos.extend(['--unidade', unidade])
    subprocess.run(argumentos, cwd=RAIZ, check=True)


@dag(dag_id='xfit_alimentar_datalake', schedule=None,
     start_date=pendulum.datetime(2026, 10, 15, tz='America/Sao_Paulo'),
     catchup=False, max_active_runs=1, default_args={'retries': 0},
     is_paused_upon_creation=True, tags=['xfit', 'datalake'],
     params={'data_referencia': Param(None, type=['null', 'string'], format='date')},
     description='Recebe cada unidade/data independentemente e sinaliza pendencias.')
def fluxo_alimentar_datalake():
    carga_id = identificar_carga()
    entregas = [receber_entrega.override(task_id='receber_' + unidade)(carga_id, unidade)
                for unidade in ('barbacena', 'lafaiete', 'ecommerce')]
    resumo = receber_entrega.override(task_id='resumir_alimentacao', trigger_rule='all_done')(carga_id)
    for entrega in entregas:
        entrega >> resumo


fluxo_validar_fontes()
fluxo_carga_dw()
fluxo_alimentar_datalake()


@task(execution_timeout=timedelta(minutes=10))
def receber_dia(carga_id, unidade):
    params = get_current_context()['params']
    selecionado = params.get('recebimentos', {}).get(unidade)
    if selecionado:
        return selecionado
    data = params.get('data_referencia')
    if not data:
        raise ValueError('Informe data_referencia')
    subprocess.run([sys.executable, '-B', str(RAIZ / 'src/alimentar_datalake.py'),
                    '--unidade', unidade, '--data-referencia', data, '--carga-id', carga_id],
                   cwd=RAIZ, check=True)
    return carga_id


@task(execution_timeout=timedelta(minutes=15))
def tratar_dia(carga_id, recebimento, unidade):
    data = get_current_context()['params']['data_referencia']
    subprocess.run([sys.executable, '-B', str(RAIZ / 'src/tratar_diario.py'),
                    '--unidade', unidade, '--data-referencia', data,
                    '--carga-recebimento', recebimento, '--carga-id', carga_id], cwd=RAIZ, check=True)
    return f'data/processed/staging_diaria/{unidade}/{data}/{carga_id}/manifesto.json'


@task(execution_timeout=timedelta(minutes=90), trigger_rule='all_done')
def publicar_unidades(carga_id):
    contexto = get_current_context()
    params = contexto['params']
    resultados = {}
    # Sequencial apenas na escrita: o DW tem um bloqueio global de carga.
    for unidade in ('barbacena', 'lafaiete', 'ecommerce'):
        lote = contexto['ti'].xcom_pull(task_ids='tratar_' + unidade)
        if not lote:
            resultados[unidade] = 'sem_lote_aprovado'
            continue
        carga_unidade = carga_id + '-' + unidade
        try:
            subprocess.run([sys.executable, '-B', str(RAIZ / 'src/tratar_diario.py'),
                            '--data-referencia', params['data_referencia'], '--carga-id', carga_unidade,
                            '--aprovar-unidade', unidade, '--selecao', json.dumps({unidade: lote})],
                           cwd=RAIZ, check=True)
            manifesto = f'data/processed/staging_diaria/publicacoes/{carga_unidade}/manifesto.json'
            if params['publicar_dw']:
                subprocess.run([sys.executable, '-B', str(RAIZ / 'src/carregar_diario_postgres.py'),
                                '--manifesto', manifesto], cwd=RAIZ, check=True)
            resultados[unidade] = 'publicado' if params['publicar_dw'] else 'validado_sem_publicacao'
        except subprocess.CalledProcessError:
            resultados[unidade] = 'publicacao_bloqueada'
    for unidade, status in resultados.items():
        print(f'Unidade {unidade}: {status}.')
    if any(status in {'sem_lote_aprovado', 'publicacao_bloqueada'} for status in resultados.values()):
        # Uma folha all_done bem-sucedida ocultaria falhas anteriores no estado da DAG.
        raise ValueError('Atualizacao com pendencias; unidades aprovadas processadas e historico das demais preservado')
    return resultados


@dag(dag_id='xfit_pipeline_diario', schedule=None,
     start_date=pendulum.datetime(2026, 10, 18, tz='America/Sao_Paulo'),
     catchup=False, max_active_runs=1, default_args={'retries': 0},
     is_paused_upon_creation=True, tags=['xfit', 'diario', 'dw'],
     params={'data_referencia': Param(None, type=['null', 'string'], format='date'),
             'recebimentos': Param({}, type='object', additionalProperties={'type': 'string'},
                                   propertyNames={'enum': ['barbacena', 'lafaiete', 'ecommerce']}),
             'publicar_dw': Param(False, type='boolean')},
     description='Recebe e trata por unidade; publica aprovadas e preserva historico das unidades pendentes.')
def fluxo_pipeline_diario():
    carga_id = identificar_carga()
    tratamentos = []
    for unidade in ('barbacena', 'lafaiete', 'ecommerce'):
        recebimento = receber_dia.override(task_id='receber_' + unidade)(carga_id, unidade)
        tratamentos.append(tratar_dia.override(task_id='tratar_' + unidade)(carga_id, recebimento, unidade))
    publicacao = publicar_unidades(carga_id)
    for tratamento in tratamentos:
        tratamento >> publicacao


fluxo_pipeline_diario()
