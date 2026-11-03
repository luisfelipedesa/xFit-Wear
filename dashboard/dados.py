"""Leitura privada parametrizada; credencial independente do pipeline."""

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from streamlit import cache_data


CACHE_TTL_SEGUNDOS = 300


class ConfiguracaoInvalida(ValueError):
    pass


def configuracao_banco():
    campos = {'host': 'HOST', 'dbname': 'DATABASE', 'user': 'USER', 'password': 'PASSWORD', 'sslrootcert': 'SSLROOTCERT'}
    config = {campo: os.environ.get(f'XFIT_BI_PG_{nome}', '') for campo, nome in campos.items()}
    if not all(config.values()) or not Path(config['sslrootcert']).is_file():
        raise ConfiguracaoInvalida('Configure a credencial BI e o certificado CA no servidor.')
    if config['user'].split('.')[0] != 'xfit_dashboard_app':
        raise ConfiguracaoInvalida('Use somente o login dedicado xfit_dashboard_app.')
    config.update(port=5432, sslmode='verify-full', connect_timeout=8,
                  application_name='xfit_dashboard', options='-c default_transaction_read_only=on -c statement_timeout=15000')
    return config


@contextmanager
def conectar(config=None):
    if config is None:
        config = configuracao_banco()
    with psycopg.connect(**config, row_factory=dict_row) as conexao:
        conexao.execute('set transaction read only')
        conexao.execute('set local role xfit_dashboard')
        yield conexao


def carregar_contexto():
    # Valida a configuração mesmo em cache hit; a chave inclui a origem e a credencial.
    return _carregar_contexto(configuracao_banco())


@cache_data(ttl=CACHE_TTL_SEGUNDOS, max_entries=8, show_spinner=False)
def _carregar_contexto(config):
    with conectar(config) as conexao:
        atualizacao = conexao.execute('select * from bi.vw_atualizacao').fetchone()
        unidades = conexao.execute(
            'with unidades as ('
            'select distinct unidade_id, unidade, canal from bi.vw_desempenho_mensal), '
            'datas as (select unidade_id, max(data_venda) as ultima_data_disponivel '
            'from bi.vw_vendas_diarias group by unidade_id) '
            'select unidades.*, datas.ultima_data_disponivel from unidades '
            'left join datas using (unidade_id) order by unidade'
        ).fetchall()
        categorias = conexao.execute(
            'select distinct categoria from bi.vw_vendas_diarias_categoria order by categoria'
        ).fetchall()
    return atualizacao, unidades, [linha['categoria'] for linha in categorias]


def consultar_vendas(conexao, inicio, fim, unidades, canais, categoria=None):
    view = 'bi.vw_vendas_diarias_categoria' if categoria is not None else 'bi.vw_vendas_diarias'
    consulta = (
        f'select * from {view} where data_venda between %s and %s '
        'and unidade_id = any(%s) and canal = any(%s)'
    )
    parametros = [inicio, fim, unidades, canais]
    if categoria is not None:
        consulta += ' and categoria = %s'
        parametros.append(categoria)
    return conexao.execute(consulta + ' order by data_venda, unidade_id', parametros).fetchall()


def carregar_painel(inicio, fim, unidades, canais, categoria=None):
    # ANY trata seleções como conjuntos; a ordem dos cliques não cria outra entrada.
    return _carregar_painel(configuracao_banco(), inicio, fim,
                           sorted(set(unidades)), sorted(set(canais)), categoria)


@cache_data(ttl=CACHE_TTL_SEGUNDOS, max_entries=128, show_spinner=False)
def _carregar_painel(config, inicio, fim, unidades, canais, categoria):
    with conectar(config) as conexao:
        vendas = consultar_vendas(conexao, inicio, fim, unidades, canais, categoria)
        mix = conexao.execute(
            'select categoria, sum(receita_liquida_concluida) as receita_liquida_concluida '
            'from bi.vw_vendas_diarias_categoria where data_venda between %s and %s '
            'and unidade_id = any(%s) and canal = any(%s) '
            'and (%s::text is null or categoria = %s) group by categoria order by categoria',
            [inicio, fim, unidades, canais, categoria, categoria],
        ).fetchall()
        mensais = conexao.execute(
            'select * from bi.vw_desempenho_mensal where ano_mes between %s and %s '
            'and unidade_id = any(%s) and canal = any(%s) order by ano_mes, unidade_id',
            [inicio.strftime('%Y-%m'), fim.strftime('%Y-%m'), unidades, canais],
        ).fetchall()
    return vendas, mix, mensais
