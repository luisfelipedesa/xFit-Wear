"""Fixture visual sintetica independente das fontes e do DW."""

from datetime import date
from decimal import Decimal

from dashboard.metricas import resumir


UNIDADES = [
    {'unidade_id': 'demo-loja', 'unidade': 'Loja demonstrativa', 'canal': 'Fisico'},
    {'unidade_id': 'demo-web', 'unidade': 'Online demonstrativo', 'canal': 'Online'},
]
CATEGORIAS = ['Camisetas', 'Leggings']


def contexto():
    return {
        'ultima_data_venda': date(2026, 7, 31), 'ultima_execucao_sucesso': None,
        'ultima_data_diaria_publicada': None, 'cargas_sem_conclusao': 0,
        'cargas_com_erro': 0,
    }, [{**unidade, 'ultima_data_disponivel': date(2026, 7, 31)} for unidade in UNIDADES], CATEGORIAS


def carregar(inicio, fim, unidades, canais, categoria=None):
    vendas = []
    categorias = []
    mensais = []
    for unidade in UNIDADES:
        if unidade['unidade_id'] not in unidades or unidade['canal'] not in canais:
            continue
        mes = []
        for dia in range(1, 32):
            data_venda = date(2026, 7, dia)
            receita = Decimal(100 + dia * 10)
            linha = {
                **unidade, 'data_venda': data_venda, 'ano_mes': '2026-07',
                'linhas_registradas': 4, 'pedidos_total': 4, 'pedidos_concluidos': 3,
                'pedidos_devolvidos': 1, 'pedidos_cancelados': 0, 'itens_vendidos': 5,
                'receita_liquida_registrada': receita + 50,
                'receita_liquida_concluida': receita,
                'receita_devolvida_registrada': Decimal(50),
                'margem_bruta_concluida': receita / 2,
            }
            mes.append(linha)
            if inicio <= data_venda <= fim:
                for nome in CATEGORIAS:
                    categorias.append({'categoria': nome, 'receita_liquida_concluida': receita / 2})
                if categoria is not None:
                    linha = {**linha, 'receita_liquida_concluida': receita / 2,
                             'receita_liquida_registrada': receita / 2 + 25,
                             'receita_devolvida_registrada': Decimal(25),
                             'margem_bruta_concluida': receita / 4, 'itens_vendidos': 3}
                vendas.append(linha)
        if inicio.strftime('%Y-%m') <= '2026-07' <= fim.strftime('%Y-%m'):
            mensais.append({**unidade, **resumir(mes), 'ano_mes': '2026-07',
                            'meta_receita_liquida': Decimal(10000),
                            'tem_meta': True, 'tem_registros_vendas': True})
    mix = [{'categoria': nome, 'receita_liquida_concluida': sum(
        (linha['receita_liquida_concluida'] for linha in categorias if linha['categoria'] == nome), Decimal(0)
    )} for nome in CATEGORIAS if categoria is None or categoria == nome]
    return vendas, mix, mensais
