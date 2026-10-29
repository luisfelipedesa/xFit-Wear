"""Rotulos e graficos comerciais em portugues brasileiro."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.metricas import formatar
from dashboard.interacao import aplicar_filtro_grafico


CANAIS = {'ecommerce': 'Ecommerce', 'loja_fisica': 'Loja física', 'Fisico': 'Loja física', 'Online': 'Ecommerce'}
UNIDADES = {'LJ-BQ': 'Barbacena', 'LJ-CL': 'Conselheiro Lafaiete', 'EC-BR': 'Ecommerce'}
CATEGORIAS = {'Acessorios': 'Acessórios', 'Calcas': 'Calças', 'Macacoes': 'Macacões'}
LOCALE = {
    'number': {'decimal': ',', 'thousands': '.', 'grouping': [3], 'currency': ['R$ ', '']},
    'time': {
        'dateTime': '%A, %e de %B de %Y, %X', 'date': '%d/%m/%Y', 'time': '%H:%M:%S',
        'periods': ['AM', 'PM'],
        'days': ['domingo', 'segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado'],
        'shortDays': ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'],
        'months': ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'],
        'shortMonths': ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'],
    },
}


def nome_unidade(linha):
    return UNIDADES.get(linha['unidade_id'], linha['unidade'])


def exibir_data(valor):
    if valor is None:
        return 'Não disponível'
    if isinstance(valor, datetime):
        return valor.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y às %H:%M') + ' (Brasília)'
    return valor.strftime('%d/%m/%Y')


def ler_data(texto):
    return datetime.strptime(texto.strip(), '%d/%m/%Y').date()


def exibir_grafico(linhas, eixo, valor, titulo_valor, tipo='barra', cor=None, chave=None, filtros=None):
    if not linhas:
        st.info('Sem registros para este gráfico no período selecionado.')
        return
    quadro = pd.DataFrame(linhas)
    if filtros is not None:
        if len(filtros) != len(linhas):
            raise ValueError('Cada ponto do grafico precisa do seu filtro.')
        quadro['filtro_id'] = [str(indice) for indice in range(len(linhas))]
    quadro[titulo_valor] = quadro[valor].map(lambda numero: float(numero) if numero is not None else None)
    quadro['Valor exibido'] = quadro[valor].map(lambda numero: formatar(numero, prefixo='R$ ' if '(R$)' in titulo_valor else ''))
    eixo_temporal = isinstance(linhas[0][eixo], date)
    tooltip = [alt.Tooltip(f'{eixo}:T', title='Data', format='%d/%m/%Y')] if eixo_temporal else [alt.Tooltip(f'{eixo}:N')]
    tooltip.append(alt.Tooltip('Valor exibido:N', title=titulo_valor))
    grafico = alt.Chart(quadro)
    grafico = grafico.mark_line(point=True) if tipo == 'linha' else grafico.mark_bar()
    eixo_x = alt.X(f'{eixo}:T', axis=alt.Axis(format='%d/%m/%Y'), title='Data') if eixo_temporal else alt.X(f'{eixo}:N', sort=None)
    campos = {'x': eixo_x, 'y': alt.Y(f'{titulo_valor}:Q', axis=alt.Axis(format=',.2f' if '(R$)' in titulo_valor else ',.0f')),
              'tooltip': tooltip}
    if cor:
        campos['color'] = alt.Color(f'{cor}:N', title=cor)
        campos['xOffset'] = alt.XOffset(f'{cor}:N')
        tooltip.append(alt.Tooltip(f'{cor}:N'))
    grafico = grafico.encode(**campos)
    opcoes = {}
    if filtros is not None:
        chave_widget = f"{chave}_{st.session_state.get('versao_graficos', 0)}"
        selecao = alt.selection_point(name='filtro', fields=['filtro_id'], toggle=False,
                                      nearest=tipo == 'linha', empty=False)
        if tipo == 'linha':
            # A selecao por proximidade pertence aos pontos, nao ao traco da linha.
            pontos = grafico.mark_point(filled=True, size=60, cursor='pointer').add_params(selecao)
            grafico = alt.layer(grafico.mark_line(), pontos)
        else:
            grafico = grafico.mark_bar(cursor='pointer').add_params(selecao)

        def selecionar():
            pontos = st.session_state[chave_widget]['selection'].get('filtro', [])
            if not pontos:
                return
            identificador = pontos[0].get('filtro_id')
            # Somente pontos da consulta exibida podem produzir novos filtros.
            for indice, filtro in enumerate(filtros):
                if identificador == str(indice):
                    aplicar_filtro_grafico(st.session_state, filtro)
                    break

        opcoes.update(key=chave_widget, on_select=selecionar, selection_mode='filtro')
    grafico = grafico.configure(locale=LOCALE, aria=False).properties(height=280)
    st.altair_chart(grafico, width='stretch', alt=titulo_valor, **opcoes)
