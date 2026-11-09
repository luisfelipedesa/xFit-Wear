"""Base BI agregada em cache; filtros locais e credencial independente do pipeline."""

import os
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import psycopg
from psycopg.rows import dict_row
from streamlit import cache_resource


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
        conexao.execute('set transaction isolation level repeatable read, read only')
        conexao.execute('set local role xfit_dashboard')
        yield conexao


def carregar_contexto():
    atualizacao, unidades, categorias = carregar_base()['contexto']
    return dict(atualizacao), [dict(linha) for linha in unidades], list(categorias)


def carregar_base():
    # Valida mesmo em cache hit; a chave inclui origem e credencial, nunca os filtros.
    return _carregar_base(configuracao_banco())


@cache_resource(ttl=CACHE_TTL_SEGUNDOS, max_entries=2, show_spinner=False)
def _carregar_base(config):
    with conectar(config) as conexao:
        atualizacao = conexao.execute('select * from bi.vw_atualizacao').fetchone()
        vendas = conexao.execute(
            'select * from bi.vw_vendas_diarias order by data_venda, unidade_id'
        ).fetchall()
        categorias = conexao.execute(
            'select * from bi.vw_vendas_diarias_categoria order by data_venda, unidade_id, categoria'
        ).fetchall()
        mensais = conexao.execute(
            'select * from bi.vw_desempenho_mensal order by ano_mes, unidade_id'
        ).fetchall()
    ultimas_datas = {}
    for linha in vendas:
        unidade = linha['unidade_id']
        ultimas_datas[unidade] = max(ultimas_datas.get(unidade, linha['data_venda']), linha['data_venda'])
    cadastros = {(linha['unidade_id'], linha['unidade'], linha['canal']) for linha in mensais}
    unidades = sorted([
        {'unidade_id': identidade, 'unidade': nome, 'canal': canal,
         'ultima_data_disponivel': ultimas_datas.get(identidade)}
        for identidade, nome, canal in cadastros
    ], key=lambda linha: linha['unidade'])
    # A base é compartilhada entre sessões. Tuplas e mappings somente leitura
    # evitam tanto a cópia integral em cada filtro quanto alterações por um visitante.
    contexto = (MappingProxyType(atualizacao), tuple(MappingProxyType(linha) for linha in unidades),
                tuple(sorted({linha['categoria'] for linha in categorias})))
    return MappingProxyType({'contexto': contexto,
                             'vendas': tuple(MappingProxyType(linha) for linha in vendas),
                             'categorias': tuple(MappingProxyType(linha) for linha in categorias),
                             'mensais': tuple(MappingProxyType(linha) for linha in mensais)})


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
    return filtrar_painel(carregar_base(), inicio, fim, unidades, canais, categoria)


def filtrar_painel(base, inicio, fim, unidades, canais, categoria=None):
    unidades, canais = set(unidades), set(canais)

    def pertence_ao_filtro(linha):
        return linha['unidade_id'] in unidades and linha['canal'] in canais

    categorias = [linha for linha in base['categorias']
                  if inicio <= linha['data_venda'] <= fim and pertence_ao_filtro(linha)
                  and (categoria is None or linha['categoria'] == categoria)]
    # Pedidos de categorias distintas não são aditivos: preservar o agregado geral.
    vendas = ([dict(linha) for linha in base['vendas']
               if inicio <= linha['data_venda'] <= fim and pertence_ao_filtro(linha)]
              if categoria is None else [dict(linha) for linha in categorias])
    receitas = {}
    for linha in categorias:
        nome = linha['categoria']
        receitas[nome] = receitas.get(nome, Decimal(0)) + linha['receita_liquida_concluida']
    mix = [{'categoria': nome, 'receita_liquida_concluida': receita}
           for nome, receita in sorted(receitas.items())]
    inicio_mes, fim_mes = inicio.strftime('%Y-%m'), fim.strftime('%Y-%m')
    mensais = [dict(linha) for linha in base['mensais']
               if inicio_mes <= linha['ano_mes'] <= fim_mes and pertence_ao_filtro(linha)]
    return vendas, mix, mensais
