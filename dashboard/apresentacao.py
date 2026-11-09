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


@st.dialog('Conheça o projeto xFit Wear', width='large', on_dismiss='rerun')
def apresentar_projeto():
    st.markdown('### Do dado à decisão')
    st.write('Um projeto de engenharia de dados e BI para uma operação demonstrativa '
             'de roupas fitness, com lojas em Barbacena e Conselheiro Lafaiete e um canal de ecommerce.')
    st.write('O objetivo é transformar entregas independentes em indicadores consistentes de vendas, '
             'margem, pedidos, devoluções e metas, com rastreabilidade da origem ao dashboard.')
    st.caption('Arquivos CSV/JSON → Data lake → Tratamento em Python → DW PostgreSQL/Supabase → Views BI → Streamlit')

    with st.expander('01 · Por que usar o Airflow?', expanded=True):
        st.write('Cada unidade alimenta o data lake individualmente. O Apache Airflow organiza os '
                 'recebimentos e tratamentos em tarefas independentes, controla as dependências '
                 'e registra o resultado de cada etapa. Se uma unidade não entregar o arquivo, '
                 'o recebimento das outras não é cancelado.')
        st.write('Cada unidade com uma entrega aprovada pode atualizar o DW, mesmo que outra '
                 'não tenha alimentado o lake. A aprovação e a publicação são feitas por unidade '
                 'e data: a ausência ou reprovação de um arquivo não impede o processamento '
                 'dos arquivos válidos das demais unidades.')
        st.markdown('**Continuidade da análise:** quem entregou dados válidos é atualizado; quem '
                    'não entregou mantém no DW os últimos dados válidos que vieram do lake. '
                    'O dashboard continua exibindo esse histórico, com as datas originais. '
                    'Dados antigos não são copiados para o dia atual nem apresentados como novos. '
                    'O farol mostra a última data disponível de cada unidade e evidencia a defasagem.')
        st.caption('As DAGs são acionadas manualmente, com data de referência explícita. '
                   'Essa proteção preserva os dados; a disponibilidade da tela também depende do servidor e do banco.')

    with st.expander('02 · Como os arquivos são tratados e validados?'):
        st.markdown('''
**Recebimento rastreável.** Cada entrega declara unidade, data, quantidade de registros
e hash SHA-256. O processo confere estrutura, localização autorizada, volume e conteúdo,
preserva a cópia de origem e identifica a carga em um manifesto. Ausência de arquivo
não é tratada como zero vendas: um dia sem movimento exige declaração explícita válida.
Na carga histórica, a auditoria e o backup verificado antecedem a publicação.

**Padronização em Python.** Vendas, produtos e metas são convertidos para um formato
comum. Datas, horários, canais e status são validados; valores monetários usam Decimal
para preservar precisão, e quantidades precisam ser inteiras e positivas.

**Qualidade antes do DW.** São conferidos campos obrigatórios, unidade/data corretas,
produtos cadastrados, metas por unidade/mês, duplicidades, consistência dos pedidos
e coerência entre receita, custo e margem. Alterações de arquivo durante o processamento
e divergências de hash ou volume bloqueiam a aprovação. Um erro reprova o lote da
unidade/data inteiro; linhas inválidas não são descartadas silenciosamente.

**Publicação protegida.** Somente o lote aprovado da unidade/data segue para a carga SQL,
com reconciliação de conteúdo e totais e confirmação em transação. Falhas antes da
confirmação desfazem as alterações no banco. Chaves únicas, relacionamentos e restrições
SQL reforçam a integridade. A repetição de uma entrega idêntica não
duplica vendas; conteúdo diferente para um dia já aprovado exige revisão, sem
substituição ou exclusão automática do histórico.
''')

    with st.expander('03 · Modelo dimensional e schemas utilizados'):
        st.write('O PostgreSQL/Supabase organiza o DW em um modelo dimensional em estrela, '
                 'com dimensões compartilhadas entre as tabelas de fatos. O objetivo é facilitar '
                 'os cruzamentos por data, produto e unidade, preservando o nível de detalhe de cada indicador.')
        st.markdown('''
| Tabela no schema `dw` | Papel e nível de detalhe |
|---|---|
| `dim_data` | Calendário para análises por dia, mês e ano. |
| `dim_produto` | Cadastro e categoria dos produtos. |
| `dim_unidade` | Lojas e ecommerce, com canal e localização. |
| `fato_vendas` | Um registro por item vendido, ligado a data, produto e unidade. |
| `fato_metas` | Uma meta por unidade/mês, ligada a data e unidade. |

As vendas são agregadas por unidade/mês antes da comparação com metas, para que
a mesma meta não seja multiplicada pela quantidade de itens vendidos.

**Separação de responsabilidades:** `stg` recebe os dados padronizados; `etl`
registra a execução e o estado das cargas; `dw` mantém dimensões e fatos;
`bi` oferece views agregadas para o consumo do dashboard.
''')

    with st.expander('04 · Como o dashboard consome os dados com segurança?'):
        st.write('O Streamlit consulta views privadas de BI, em vez de ler os arquivos do lake '
                 'diretamente. As views centralizam os cálculos e entregam os agregados usados '
                 'nos cards, gráficos e filtros. A base agregada fica compartilhada em memória '
                 'por até cinco minutos; os filtros trabalham sobre essa base, sem consultar '
                 'novamente o banco a cada seleção.')
        st.write('A conexão usa TLS com validação do certificado e uma credencial exclusiva de '
                 'leitura, sem acesso direto às tabelas internas ou permissão para alterar o DW. '
                 'Os filtros usam parâmetros SQL. Senhas e arquivos operacionais ficam fora do '
                 'código publicado; o visitante recebe os indicadores, não as credenciais do banco.')
        st.caption('Hash verifica a correspondência do conteúdo; não comprova, sozinho, a autenticidade '
                   'do remetente ou a completude do sistema de origem.')

    st.info('Os dados são demonstrativos para portfólio. Não representam resultados de uma operação comercial real.')
    st.caption('Explore os filtros laterais ou clique nos gráficos para combinar período, unidade e categoria.')
    if st.button('Explorar dashboard', type='primary', key='fechar_apresentacao'):
        st.rerun()


def apresentar_projeto_na_abertura():
    if not st.session_state.get('apresentacao_exibida', False):
        # A marca pertence à sessão; filtros e fechamento do modal não o reabrem.
        st.session_state['apresentacao_exibida'] = True
        apresentar_projeto()


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
