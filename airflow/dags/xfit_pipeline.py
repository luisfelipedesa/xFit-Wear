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


@task(execution_timeout=timedelta(minutes=5))
def aprovar_dia(carga_id, selecao):
    data = get_current_context()['params']['data_referencia']
    subprocess.run([sys.executable, '-B', str(RAIZ / 'src/tratar_diario.py'),
                    '--data-referencia', data, '--carga-id', carga_id,
                    '--selecao', json.dumps(selecao)], cwd=RAIZ, check=True)
    return f'data/processed/staging_diaria/publicacoes/{carga_id}/manifesto.json'


@task(execution_timeout=timedelta(minutes=30))
def publicar_dia(manifesto):
    if not get_current_context()['params']['publicar_dw']:
        return {'status': 'validado_sem_publicacao', 'manifesto': manifesto}
    subprocess.run([sys.executable, '-B', str(RAIZ / 'src/carregar_diario_postgres.py'),
                    '--manifesto', manifesto], cwd=RAIZ, check=True)
    return {'status': 'publicado', 'manifesto': manifesto}


@dag(dag_id='xfit_pipeline_diario', schedule=None,
     start_date=pendulum.datetime(2026, 10, 18, tz='America/Sao_Paulo'),
     catchup=False, max_active_runs=1, default_args={'retries': 0},
     is_paused_upon_creation=True, tags=['xfit', 'diario', 'dw'],
     params={'data_referencia': Param(None, type=['null', 'string'], format='date'),
             'recebimentos': Param({}, type='object', additionalProperties={'type': 'string'},
                                   propertyNames={'enum': ['barbacena', 'lafaiete', 'ecommerce']}),
             'publicar_dw': Param(False, type='boolean')},
     description='Recebe, trata, exige dia completo e publica staging aprovada sem reler historico.')
def fluxo_pipeline_diario():
    carga_id = identificar_carga()
    selecao = {}
    for unidade in ('barbacena', 'lafaiete', 'ecommerce'):
        recebimento = receber_dia.override(task_id='receber_' + unidade)(carga_id, unidade)
        selecao[unidade] = tratar_dia.override(task_id='tratar_' + unidade)(carga_id, recebimento, unidade)
    publicar_dia(aprovar_dia(carga_id, selecao))


fluxo_pipeline_diario()
