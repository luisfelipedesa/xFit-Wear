"""Calculos de exibicao conforme docs/contrato_dashboard.md."""

from calendar import monthrange
from datetime import date
from decimal import Decimal


CAMPOS_SOMA = (
    'linhas_registradas', 'pedidos_total', 'pedidos_concluidos',
    'pedidos_devolvidos', 'pedidos_cancelados', 'itens_vendidos',
    'receita_liquida_registrada', 'receita_liquida_concluida',
    'receita_devolvida_registrada', 'margem_bruta_concluida',
)


def dividir(numerador, denominador, percentual=False):
    if not denominador:
        return None
    return Decimal(numerador) / Decimal(denominador) * (100 if percentual else 1)


def resumir(vendas):
    totais = {
        campo: sum((Decimal(linha.get(campo) or 0) for linha in vendas), Decimal(0))
        for campo in CAMPOS_SOMA
    }
    totais['ticket_medio'] = dividir(totais['receita_liquida_concluida'], totais['pedidos_concluidos'])
    totais['margem_bruta_pct'] = dividir(totais['margem_bruta_concluida'], totais['receita_liquida_concluida'], True)
    totais['taxa_devolucao_pct'] = dividir(totais['pedidos_devolvidos'], totais['pedidos_concluidos'] + totais['pedidos_devolvidos'], True)
    totais['taxa_cancelamento_pct'] = dividir(totais['pedidos_cancelados'], totais['pedidos_total'], True)
    return totais


def periodo_padrao(ultima_venda):
    referencia = ultima_venda or date.today()
    return referencia.replace(day=1), referencia.replace(day=monthrange(referencia.year, referencia.month)[1])


def meses_inteiros(inicio, fim):
    return inicio <= fim and inicio.day == 1 and fim.day == monthrange(fim.year, fim.month)[1]


def chaves_mensais(inicio, fim, unidades):
    referencia = inicio.replace(day=1)
    chaves = set()
    while referencia <= fim:
        chaves.update((referencia.strftime('%Y-%m'), unidade) for unidade in unidades)
        referencia = date(referencia.year + (referencia.month == 12), referencia.month % 12 + 1, 1)
    return chaves


def resumir_metas(mensais, esperadas=None):
    meta = sum((Decimal(linha['meta_receita_liquida'] or 0) for linha in mensais), Decimal(0))
    receita = sum((Decimal(linha['receita_liquida_concluida'] or 0) for linha in mensais), Decimal(0))
    presentes = {(linha.get('ano_mes'), linha.get('unidade_id')) for linha in mensais}
    tem_metas = bool(mensais) and all(linha['tem_meta'] for linha in mensais)
    if esperadas is not None:
        tem_metas = tem_metas and presentes == esperadas
    cobertura = tem_metas and all(linha['tem_registros_vendas'] for linha in mensais)
    tem_realizado = any(linha['tem_registros_vendas'] for linha in mensais)
    return {
        'meta': meta if tem_metas else None,
        'atingimento': dividir(receita, meta, True) if tem_metas and tem_realizado else None,
        'cobertura': cobertura,
        'realizado': receita if tem_realizado else None,
        'tem_metas': tem_metas,
        'meses_sem_registros': sum(not linha['tem_registros_vendas'] for linha in mensais),
    }


def comparar_metas(mensais, anual=False):
    grupos = {}
    for linha in mensais:
        periodo = linha['ano_mes'][:4] if anual else linha['ano_mes']
        grupos.setdefault((periodo, linha['unidade_id']), []).append(linha)
    comparativos = []
    for (periodo, unidade), linhas in sorted(grupos.items()):
        resumo = resumir_metas(linhas)
        comparativos.append({'periodo': periodo, 'unidade_id': unidade, **resumo})
    return comparativos


def agrupar(vendas, campo):
    grupos = {}
    for linha in vendas:
        grupos.setdefault(linha[campo], []).append(linha)
    return [{campo: chave, **resumir(linhas)} for chave, linhas in sorted(grupos.items())]


def formatar(valor, casas=2, prefixo='', sufixo=''):
    if valor is None:
        return '—'
    numero = f'{valor:,.{casas}f}'.translate(str.maketrans(',.', '.,'))
    return f'{prefixo}{numero}{sufixo}'
