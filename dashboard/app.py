"""Visao Geral Comercial; executar da raiz com streamlit run dashboard/app.py."""

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from dashboard import dados, demo
from dashboard.atualizacao import avaliar_atualizacao
from dashboard.interacao import limpar_filtros, periodo_do_grafico, renovar_graficos
from dashboard.acesso import previa_local_permitida, usuario_permitido
from dashboard.apresentacao import CANAIS, CATEGORIAS, UNIDADES, exibir_data, exibir_grafico, ler_data, nome_unidade
from dashboard.metricas import agrupar, chaves_mensais, comparar_metas, formatar, meses_inteiros, periodo_padrao, resumir, resumir_metas


st.set_page_config(page_title='xFit Wear | Comercial', page_icon='📊', layout='wide')
st.html('<style>[data-testid="stToolbar"], [data-testid="stElementToolbar"] {display:none !important} [data-testid="stMetricValue"] {font-size:clamp(1.2rem,2.4vw,2rem)}</style>')
st.title('xFit Wear')

modo_demo = os.environ.get('XFIT_DASHBOARD_DEMO') == '1'
modo_publico = os.environ.get('XFIT_DASHBOARD_PUBLIC') == '1'
local_solicitado = os.environ.get('XFIT_DASHBOARD_LOCAL_DW') == '1'
modo_local = previa_local_permitida(local_solicitado, st.get_option('server.address'), modo_demo)
if local_solicitado and not modo_local:
    st.error('Acesso bloqueado pela configuração do servidor.')
    st.stop()
if modo_demo:
    st.info('DEMONSTRAÇÃO VISUAL · Dados fictícios independentes do DW. Nenhuma conexão com o Supabase.')
elif modo_publico:
    st.caption('Portfólio com dados demonstrativos. Acesso público aos indicadores.')
elif not modo_local:
    try:
        auth = st.secrets.get('auth', {})
        emails = st.secrets.get('dashboard', {}).get('allowed_emails', [])
    except FileNotFoundError:
        auth, emails = {}, []
    if not auth or not emails:
        st.warning('Acesso bloqueado: configure o provedor OIDC e a lista de usuários autorizados no servidor.')
        st.stop()
    if not st.user.is_logged_in:
        st.write('Entre com sua conta autorizada para consultar os indicadores.')
        if st.button('Entrar', type='primary'):
            st.login()
        st.stop()
    if not usuario_permitido(dict(st.user), emails):
        st.error('Sessão expirada, conta sem autorização ou e-mail não verificado. Saia e entre novamente.')
        if st.button('Sair'):
            st.logout()
        st.stop()
    if st.sidebar.button('Sair'):
        st.logout()
        st.stop()

try:
    atualizacao, unidades, categorias = demo.contexto() if modo_demo else dados.carregar_contexto()
except (dados.ConfiguracaoInvalida, dados.psycopg.Error):
    st.error('Não foi possível consultar o DW. Verifique a configuração BI, TLS e disponibilidade no servidor.')
    st.stop()

st.subheader('Atualização das cargas')
farol = avaliar_atualizacao(unidades, esperadas=None if modo_demo else UNIDADES)
for coluna, unidade in zip(st.columns(len(farol) or 1), farol):
    with coluna.container(border=True):
        st.markdown(f"**{nome_unidade(unidade)}**")
        if unidade['cor'] == 'verde':
            st.success(unidade['status'], icon='🟢')
        elif unidade['cor'] == 'vermelho':
            st.error(unidade['status'], icon='🔴')
        elif unidade['cor'] == 'amarelo':
            st.warning(unidade['status'], icon='🟡')
        else:
            st.info(unidade['status'], icon='⚪')
        st.caption(f"Data final no DW: {exibir_data(unidade.get('ultima_data_disponivel'))}")
if not farol:
    st.info('⚪ Sem unidades disponíveis para verificar as cargas.')
st.caption('Verde quando todas as fontes têm a mesma data final no DW. A verificação considera todas as unidades e o Ecommerce, independentemente dos filtros.')


with st.expander('Cobertura e atualização', expanded=True):
    colunas = st.columns(3)
    colunas[0].write(f"Última venda: **{exibir_data(atualizacao['ultima_data_venda'])}**")
    colunas[1].write(f"Última carga bem-sucedida: **{exibir_data(atualizacao['ultima_execucao_sucesso'])}**")
    colunas[2].write(f"Último dia publicado: **{exibir_data(atualizacao['ultima_data_diaria_publicada'])}**")
    st.caption(f"Cargas sem conclusão: {atualizacao['cargas_sem_conclusao']} · Registros históricos de erro: {atualizacao['cargas_com_erro']}")

inicio_padrao, fim_padrao = periodo_padrao(atualizacao['ultima_data_venda'])
todos_canais = sorted({linha['canal'] for linha in unidades})
padroes = {'tipo_periodo': 'Mensal / personalizado', 'ano': str(inicio_padrao.year),
           'inicio': exibir_data(inicio_padrao), 'fim': exibir_data(fim_padrao), 'categoria': None}
padroes.update({f"unidade_{linha['unidade_id']}": True for linha in unidades})
padroes.update({f'canal_{canal}': True for canal in todos_canais})
for chave, valor in padroes.items():
    st.session_state.setdefault(chave, valor)


def alterar_filtro_lateral():
    renovar_graficos(st.session_state)


with st.sidebar:
    st.header('Filtros')
    st.button('Limpar filtros', on_click=limpar_filtros,
              args=(st.session_state, inicio_padrao, fim_padrao), key='limpar_filtros')
    st.caption('Clique nas barras de unidade ou categoria e nos pontos de data para filtrar o painel. Os filtros são combinados.')
    tipo_periodo = st.radio('Período de análise', ['Mensal / personalizado', 'Anual'], key='tipo_periodo', on_change=alterar_filtro_lateral)
    if tipo_periodo == 'Anual':
        ano_texto = st.text_input('Ano (AAAA)', key='ano', on_change=alterar_filtro_lateral)
        try:
            if len(ano_texto.strip()) != 4:
                raise ValueError('Ano deve ter quatro dígitos')
            ano = int(ano_texto)
            inicio, fim = date(ano, 1, 1), date(ano, 12, 31)
        except ValueError:
            st.info('Informe um ano válido com quatro dígitos.')
            st.stop()
    else:
        inicio_texto = st.text_input('Data inicial (DD/MM/AAAA)', key='inicio', on_change=alterar_filtro_lateral)
        fim_texto = st.text_input('Data final (DD/MM/AAAA)', key='fim', on_change=alterar_filtro_lateral)
        try:
            inicio, fim = ler_data(inicio_texto), ler_data(fim_texto)
        except ValueError:
            st.info('Informe as datas no formato DD/MM/AAAA.')
            st.stop()
    nomes = {linha['unidade_id']: nome_unidade(linha) for linha in unidades}
    with st.expander('Unidades', expanded=True):
        selecionadas = [identificador for identificador, nome in nomes.items()
                        if st.checkbox(nome, key=f'unidade_{identificador}', on_change=alterar_filtro_lateral)]
    with st.expander('Canais', expanded=True):
        canais = [canal for canal in todos_canais
                  if st.checkbox(CANAIS.get(canal, canal), key=f'canal_{canal}', on_change=alterar_filtro_lateral)]
    with st.expander('Categorias'):
        categoria = st.radio('Categoria', options=[None, *categorias], key='categoria',
                             on_change=alterar_filtro_lateral,
                             format_func=lambda valor: 'Todas' if valor is None else CATEGORIAS.get(valor, valor))
    st.caption('Categorias seguem o cadastro atual. Pedidos não são somáveis entre categorias.')

filtros_unidades = {linha['unidade_id']: {'unidade': linha['unidade_id'],
                   'canal': linha['canal'], 'canais': todos_canais} for linha in unidades}
st.caption(f"Período: {exibir_data(inicio)} a {exibir_data(fim)} · "
           f"Unidades: {', '.join(nomes[unidade] for unidade in selecionadas)} · "
           f"Categoria: {CATEGORIAS.get(categoria, categoria) if categoria else 'Todas'}")

if inicio > fim:
    st.info('A data inicial deve ser anterior ou igual à data final.')
    st.stop()
if not selecionadas or not canais:
    st.info('Selecione ao menos uma unidade e um canal.')
    st.stop()
try:
    with st.spinner('Consultando indicadores…'):
        carregar = demo.carregar if modo_demo else dados.carregar_painel
        vendas, mix, mensais = carregar(inicio, fim, selecionadas, canais, categoria)
except (dados.ConfiguracaoInvalida, dados.psycopg.Error):
    st.error('Consulta indisponível. Nenhuma alteração foi realizada no DW.')
    st.stop()

totais = resumir(vendas)
st.subheader('Resultado comercial')
if not vendas:
    st.info('Sem registros no filtro. Isso não comprova ausência de movimento ou alimentação completa.')
cards = st.columns(3)
cards[0].metric('Receita de vendas concluídas', formatar(totais['receita_liquida_concluida'], prefixo='R$ '))
cards[1].metric('Margem bruta das concluídas', formatar(totais['margem_bruta_concluida'], prefixo='R$ '))
cards[2].metric('Margem bruta %', formatar(totais['margem_bruta_pct'], sufixo='%'))
cards = st.columns(3)
cards[0].metric('Pedidos concluídos', formatar(totais['pedidos_concluidos'], 0))
cards[1].metric('Unidades vendidas', formatar(totais['itens_vendidos'], 0))
cards[2].metric('Ticket médio', formatar(totais['ticket_medio'], prefixo='R$ '))

anual = inicio.month == 1 and inicio.day == 1 and fim.month == 12 and fim.day == 31
st.subheader('Metas anuais' if anual else 'Metas do período')
metas_ativas = categoria is None and meses_inteiros(inicio, fim)
if not metas_ativas:
    st.info('Metas indisponíveis com categoria selecionada ou período parcial. Não há rateio aprovado.')
else:
    unidades_compativeis = [linha['unidade_id'] for linha in unidades
                           if linha['unidade_id'] in selecionadas and linha['canal'] in canais]
    metas = resumir_metas(mensais, chaves_mensais(inicio, fim, unidades_compativeis))
    cards = st.columns(2)
    cards[0].metric('Meta de receita', formatar(metas['meta'], prefixo='R$ '))
    cards[1].metric('Atingimento da receita', formatar(metas['atingimento'], sufixo='%'))
    if not metas['tem_metas']:
        st.info('Há metas ausentes para o período/unidades selecionados. Não é possível calcular uma meta total confiável.')
    elif not metas['cobertura']:
        st.caption('O comparativo usa o realizado registrado e a meta integral do período, sem projeção ou rateio. Há meses/unidades sem vendas registradas; isso não comprova movimento zero nem alimentação completa.')
    comparativos = comparar_metas(mensais, anual)
    barras_metas = []
    filtros_metas = []
    for linha in comparativos:
        for indicador, campo in [('Realizado registrado', 'realizado'), ('Meta cadastrada', 'meta')]:
            barras_metas.append({'Período / unidade': f"{linha['periodo']} · {nomes[linha['unidade_id']]}",
                                 'Comparativo': indicador, 'valor': linha[campo]})
            filtros_metas.append({**filtros_unidades[linha['unidade_id']],
                                  **periodo_do_grafico(linha['periodo'], inicio, fim)})
    exibir_grafico(barras_metas, 'Período / unidade', 'valor', 'Receita (R$)', cor='Comparativo',
                   chave='grafico_metas', filtros=filtros_metas)

st.subheader('Evolução diária · receita concluída')
if vendas:
    serie = [{'Data': linha['data_venda'], 'valor': linha['receita_liquida_concluida']}
             for linha in agrupar(vendas, 'data_venda')]
    exibir_grafico(serie, 'Data', 'valor', 'Receita concluída (R$)', tipo='linha',
                   chave='grafico_receita_diaria',
                   filtros=[{'inicio': linha['Data'], 'fim': linha['Data']} for linha in serie])

st.subheader('Receita anual por unidade' if anual else 'Receita mensal por unidade')
if vendas:
    grupos = {}
    for linha in vendas:
        chave = (linha['ano_mes'][:4] if anual else linha['ano_mes'], linha['unidade_id'])
        grupos[chave] = grupos.get(chave, 0) + linha['receita_liquida_concluida']
    quadro = [{'Período': chave[0], 'Unidade': nomes[chave[1]], 'valor': valor} for chave, valor in sorted(grupos.items())]
    filtros = [{**filtros_unidades[unidade], **periodo_do_grafico(periodo, inicio, fim)}
               for periodo, unidade in sorted(grupos)]
    exibir_grafico(quadro, 'Período', 'valor', 'Receita concluída (R$)', cor='Unidade',
                   chave='grafico_receita_unidade', filtros=filtros)
    st.caption('Somente datas do filtro; meses parciais não representam o mês completo.')

st.subheader('Participação das categorias · receita concluída')
if mix:
    quadro = [{'Categoria': CATEGORIAS.get(linha['categoria'], linha['categoria']),
               'valor': linha['receita_liquida_concluida']} for linha in mix]
    exibir_grafico(quadro, 'Categoria', 'valor', 'Receita concluída (R$)',
                   chave='grafico_categorias', filtros=[{'categoria': linha['categoria']} for linha in mix])

st.subheader('Comparativo por unidade')
linhas = []
for linha in agrupar(vendas, 'unidade_id'):
    linhas.append({
        'Unidade': nomes.get(linha['unidade_id'], linha['unidade_id']),
        'Receita concluída': formatar(linha['receita_liquida_concluida'], prefixo='R$ '),
        'Margem %': formatar(linha['margem_bruta_pct'], sufixo='%'),
        'Pedidos concluídos': formatar(linha['pedidos_concluidos'], 0),
        'Ticket médio': formatar(linha['ticket_medio'], prefixo='R$ '),
    })
st.table(linhas, hide_index=True)

st.subheader('Devoluções e cancelamentos')
cards = st.columns(3)
cards[0].metric('Valor das devoluções registradas', formatar(totais['receita_devolvida_registrada'], prefixo='R$ '))
cards[1].metric('Pedidos devolvidos', formatar(totais['pedidos_devolvidos'], 0))
cards[2].metric('Taxa de devolução', formatar(totais['taxa_devolucao_pct'], sufixo='%'))
cards = st.columns(2)
cards[0].metric('Pedidos cancelados', formatar(totais['pedidos_cancelados'], 0))
cards[1].metric('Taxa de cancelamento', formatar(totais['taxa_cancelamento_pct'], sufixo='%'))
st.subheader('Evolução das devoluções registradas')
serie = [{'Data': linha['data_venda'], 'valor': linha['receita_devolvida_registrada']}
         for linha in agrupar(vendas, 'data_venda')]
exibir_grafico(serie, 'Data', 'valor', 'Devoluções registradas (R$)', tipo='linha',
               chave='grafico_devolucoes_diarias',
               filtros=[{'inicio': linha['Data'], 'fim': linha['Data']} for linha in serie])

st.subheader('Pedidos por situação')
situacoes = [{'Situação': rotulo, 'valor': totais[campo]} for rotulo, campo in
             [('Concluídos', 'pedidos_concluidos'), ('Devolvidos', 'pedidos_devolvidos'), ('Cancelados', 'pedidos_cancelados')]]
exibir_grafico(situacoes, 'Situação', 'valor', 'Pedidos')
st.caption('Comparação entre situações no filtro atual. As taxas preservam seus denominadores.')
st.subheader('Devoluções por unidade')
quadro = [{'Unidade': nomes[linha['unidade_id']], 'valor': linha['receita_devolvida_registrada']}
          for linha in agrupar(vendas, 'unidade_id')]
exibir_grafico(quadro, 'Unidade', 'valor', 'Devoluções registradas (R$)',
               chave='grafico_devolucoes_unidade',
               filtros=[filtros_unidades[linha['unidade_id']] for linha in agrupar(vendas, 'unidade_id')])
with st.expander('Como interpretar os indicadores'):
    st.write('Devoluções mantêm valores positivos da origem e seguem a data da venda, pois não há data própria do evento de devolução. Não representam estorno financeiro. Canceladas não entram nos indicadores de vendas concluídas.')
    st.write('Taxa de devolução: pedidos devolvidos divididos pela soma de concluídos e devolvidos. Taxa de cancelamento: pedidos cancelados divididos por todos os pedidos.')
