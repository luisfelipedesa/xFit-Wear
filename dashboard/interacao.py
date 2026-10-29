"""Selecoes dos graficos atualizam os mesmos filtros da barra lateral."""

from calendar import monthrange
from datetime import date


def periodo_do_grafico(periodo, inicio, fim):
    ano = int(periodo[:4])
    if len(periodo) == 4:
        primeiro, ultimo = date(ano, 1, 1), date(ano, 12, 31)
    else:
        mes = int(periodo[5:7])
        primeiro, ultimo = date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])
    return {'inicio': max(inicio, primeiro), 'fim': min(fim, ultimo)}


def aplicar_filtro_grafico(estado, filtro):
    # O filtro vem do ponto montado no servidor, nunca de SQL enviado pelo navegador.
    if 'unidade' in filtro:
        for chave in list(estado):
            if chave.startswith('unidade_'):
                estado[chave] = chave == f"unidade_{filtro['unidade']}"
        for canal in filtro['canais']:
            estado[f'canal_{canal}'] = canal == filtro['canal']
    if 'categoria' in filtro:
        estado['categoria'] = filtro['categoria']
    if 'inicio' in filtro:
        estado['tipo_periodo'] = 'Mensal / personalizado'
        estado['inicio'] = filtro['inicio'].strftime('%d/%m/%Y')
        estado['fim'] = filtro['fim'].strftime('%d/%m/%Y')
    renovar_graficos(estado)


def renovar_graficos(estado):
    estado['versao_graficos'] = estado.get('versao_graficos', 0) + 1


def limpar_filtros(estado, inicio, fim):
    estado.update(tipo_periodo='Mensal / personalizado', inicio=inicio.strftime('%d/%m/%Y'),
                  fim=fim.strftime('%d/%m/%Y'), ano=str(inicio.year), categoria=None)
    for chave in list(estado):
        if chave.startswith(('unidade_', 'canal_')):
            estado[chave] = True
    renovar_graficos(estado)
