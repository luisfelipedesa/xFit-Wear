"""Regressoes da interface, calculos e fronteira de leitura do dashboard."""

from datetime import date
from decimal import Decimal
import os
import time
import io
from contextlib import redirect_stderr
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from dashboard.acesso import previa_local_permitida, usuario_permitido
from dashboard import dados, demo
from dashboard.metricas import chaves_mensais, dividir, formatar, meses_inteiros, periodo_padrao, resumir, resumir_metas
from dashboard.apresentacao import CANAIS, CATEGORIAS, exibir_data, exibir_grafico, ler_data, nome_unidade
from dashboard.interacao import aplicar_filtro_grafico, limpar_filtros, periodo_do_grafico
from dashboard.atualizacao import avaliar_atualizacao


class MetricasDashboardTest(unittest.TestCase):
    def test_razoes_sao_calculadas_depois_das_somas(self):
        totais = resumir([
            {'receita_liquida_concluida': Decimal('100'), 'pedidos_concluidos': 1, 'margem_bruta_concluida': 50},
            {'receita_liquida_concluida': Decimal('300'), 'pedidos_concluidos': 6, 'margem_bruta_concluida': 150},
        ])
        self.assertEqual(totais['ticket_medio'], Decimal(400) / 7)
        self.assertEqual(totais['margem_bruta_pct'], 50)

    def test_vazio_e_denominadores_zero(self):
        self.assertIsNone(resumir([])['ticket_medio'])
        self.assertIsNone(dividir(10, 0))
        self.assertEqual(formatar(None), '—')
        self.assertEqual(formatar(Decimal('1234.56'), prefixo='R$ '), 'R$ 1.234,56')

    def test_periodo_padrao_usa_ultima_venda_e_meses_completos(self):
        self.assertEqual(periodo_padrao(date(2026, 7, 12)), (date(2026, 7, 1), date(2026, 7, 31)))
        self.assertTrue(meses_inteiros(date(2024, 1, 1), date(2024, 2, 29)))
        self.assertFalse(meses_inteiros(date(2026, 7, 2), date(2026, 7, 31)))

    def test_meta_sem_venda_ou_meta_ausente_nao_vira_zero_porcento(self):
        mensal = {'meta_receita_liquida': 100, 'receita_liquida_concluida': 90,
                  'tem_meta': True, 'tem_registros_vendas': True}
        self.assertEqual(resumir_metas([mensal])['atingimento'], 90)
        self.assertIsNone(resumir_metas([{**mensal, 'tem_registros_vendas': False}])['atingimento'])
        self.assertIsNone(resumir_metas([{**mensal, 'tem_meta': False}])['atingimento'])
        self.assertIsNone(resumir_metas([{**mensal, 'meta_receita_liquida': 0}])['atingimento'])
        self.assertIsNone(resumir_metas([])['atingimento'])

    def test_mes_unidade_ausente_nao_produz_meta_parcial(self):
        esperadas = chaves_mensais(date(2026, 7, 1), date(2026, 8, 31), ['A'])
        self.assertEqual(esperadas, {('2026-07', 'A'), ('2026-08', 'A')})
        julho = {'ano_mes': '2026-07', 'unidade_id': 'A', 'tem_meta': True,
                 'tem_registros_vendas': True, 'meta_receita_liquida': 100,
                 'receita_liquida_concluida': 90}
        self.assertIsNone(resumir_metas([julho], esperadas)['meta'])
        self.assertIsNone(resumir_metas([julho], esperadas)['atingimento'])

    def test_ano_com_metas_futuras_compara_realizado_registrado_com_meta_anual(self):
        mensais = [{'ano_mes': f'2026-{mes:02}', 'unidade_id': 'A',
                    'meta_receita_liquida': Decimal('100'), 'tem_meta': True,
                    'tem_registros_vendas': mes <= 7,
                    'receita_liquida_concluida': Decimal('90') if mes <= 7 else Decimal(0)}
                   for mes in range(1, 13)]
        resumo = resumir_metas(mensais, chaves_mensais(date(2026, 1, 1), date(2026, 12, 31), ['A']))
        self.assertEqual(resumo['meta'], 1200)
        self.assertEqual(resumo['atingimento'], Decimal('52.5'))
        self.assertFalse(resumo['cobertura'])


class AcessoDashboardTest(unittest.TestCase):
    def test_previa_real_exige_loopback_e_demo_desligado(self):
        self.assertTrue(previa_local_permitida(True, '127.0.0.1', False))
        self.assertTrue(previa_local_permitida(True, '::1', False))
        for endereco in ('0.0.0.0', '', None, '192.168.1.2'):
            self.assertFalse(previa_local_permitida(True, endereco, False))
        self.assertFalse(previa_local_permitida(False, '127.0.0.1', False))
        self.assertFalse(previa_local_permitida(True, '127.0.0.1', True))

    def test_email_verificado_e_lista_explicita(self):
        self.assertTrue(usuario_permitido({'email': 'BI@EXAMPLE.COM', 'email_verified': True, 'exp': time.time() + 60}, ['bi@example.com']))
        self.assertFalse(usuario_permitido({'email': 'bi@example.com'}, ['bi@example.com']))
        self.assertFalse(usuario_permitido({'email': 'bi@example.com', 'email_verified': 'true'}, ['bi@example.com']))
        self.assertFalse(usuario_permitido({'email': 'outro@example.com', 'email_verified': True}, ['bi@example.com']))
        self.assertFalse(usuario_permitido({}, []))

    def test_token_expirado_ou_sem_expiracao_e_negado(self):
        usuario = {'email': 'bi@example.com', 'email_verified': True}
        for expiracao in (None, 0, True, '9999999999999', float('inf')):
            with self.subTest(expiracao=expiracao):
                self.assertFalse(usuario_permitido({**usuario, 'exp': expiracao}, ['bi@example.com']))

    def test_sem_configuracao_nao_reutiliza_env_pipeline(self):
        with patch.dict(os.environ, {'XFIT_PG_USER': 'xfit_pipeline'}, clear=True):
            with self.assertRaises(dados.ConfiguracaoInvalida):
                dados.configuracao_banco()

    def test_credencial_dedicada_tls_e_timeout(self):
        ambiente = {f'XFIT_BI_PG_{nome}': 'teste' for nome in ['HOST', 'DATABASE', 'USER', 'PASSWORD', 'SSLROOTCERT']}
        ambiente['XFIT_BI_PG_USER'] = 'xfit_pipeline.projeto'
        with patch.dict(os.environ, ambiente, clear=True), patch.object(Path, 'is_file', return_value=True):
            with self.assertRaises(dados.ConfiguracaoInvalida):
                dados.configuracao_banco()
            os.environ['XFIT_BI_PG_USER'] = 'xfit_dashboard_app.projeto'
            config = dados.configuracao_banco()
        self.assertEqual(config['sslmode'], 'verify-full')
        self.assertEqual(config['port'], 5432)
        self.assertIn('read_only=on', config['options'])

    def test_sql_parametrizado_e_view_por_categoria(self):
        conexao = MagicMock()
        entrada = "Categoria'; drop table teste; --"
        dados.consultar_vendas(conexao, date(2026, 7, 1), date(2026, 7, 31), ['unidade'], ['canal'], entrada)
        consulta, parametros = conexao.execute.call_args.args
        self.assertIn('bi.vw_vendas_diarias_categoria', consulta)
        self.assertNotIn(entrada, consulta)
        self.assertEqual(parametros[-1], entrada)
        dados.consultar_vendas(conexao, date(2026, 7, 1), date(2026, 7, 31), [], [])
        self.assertNotIn('vw_vendas_diarias_categoria', conexao.execute.call_args.args[0])


class ApresentacaoDashboardTest(unittest.TestCase):
    def test_selecao_de_data_fica_nos_pontos_e_nao_na_linha(self):
        with patch('dashboard.apresentacao.st.session_state', {}), patch('dashboard.apresentacao.st.altair_chart') as renderizar:
            exibir_grafico([{'Data': date(2026, 7, 4), 'valor': 100}], 'Data', 'valor',
                           'Receita (R$)', tipo='linha', chave='receita',
                           filtros=[{'inicio': date(2026, 7, 4), 'fim': date(2026, 7, 4)}])
        especificacao = renderizar.call_args.args[0].to_dict()
        self.assertEqual(especificacao['layer'][0]['mark']['type'], 'line')
        self.assertEqual(especificacao['layer'][1]['mark']['type'], 'point')
        selecao = especificacao['params'][0]
        self.assertTrue(selecao['select']['nearest'])
        self.assertEqual(len(selecao['views']), 1)
        self.assertEqual(selecao['views'][0], especificacao['layer'][1]['name'])

    def test_selecao_usa_id_do_ponto_e_ignora_id_desconhecido(self):
        estado = {}
        filtros = [{'categoria': 'Camisetas'}]
        with patch('dashboard.apresentacao.st.session_state', estado), patch('dashboard.apresentacao.st.altair_chart') as renderizar:
            exibir_grafico([{'Categoria': 'Camisetas', 'valor': 10}], 'Categoria', 'valor',
                           'Receita (R$)', chave='categorias', filtros=filtros)
            opcoes = renderizar.call_args.kwargs
            especificacao = renderizar.call_args.args[0].to_dict()
            self.assertEqual(especificacao['params'][0]['select']['fields'], ['filtro_id'])
            estado[opcoes['key']] = {'selection': {'filtro': [{'filtro_id': 'invalido'}]}}
            opcoes['on_select']()
            self.assertNotIn('categoria', estado)
            estado[opcoes['key']] = {'selection': {'filtro': [{'filtro_id': '0'}]}}
            opcoes['on_select']()
            self.assertEqual(estado['categoria'], 'Camisetas')

    def test_rotulos_datas_e_localidade_brasileira(self):
        self.assertEqual(exibir_data(date(2026, 7, 31)), '31/07/2026')
        self.assertEqual(ler_data('01/01/2026'), date(2026, 1, 1))
        self.assertEqual(CANAIS['ecommerce'], 'Ecommerce')
        self.assertEqual(CATEGORIAS['Acessorios'], 'Acessórios')
        self.assertEqual(nome_unidade({'unidade_id': 'LJ-BQ', 'unidade': 'LJ-BQ'}), 'Barbacena')
        self.assertEqual(nome_unidade({'unidade_id': 'EC-BR', 'unidade': 'EC-BR'}), 'Ecommerce')

    def test_grafico_usa_numero_brasileiro_e_eixos_em_portugues(self):
        with patch('dashboard.apresentacao.st.altair_chart') as renderizar:
            exibir_grafico([{'Unidade': 'Barbacena', 'valor': Decimal('1234.56')}],
                           'Unidade', 'valor', 'Receita (R$)')
        especificacao = renderizar.call_args.args[0].to_dict()
        self.assertEqual(especificacao['config']['locale']['number']['decimal'], ',')
        self.assertEqual(especificacao['config']['locale']['number']['thousands'], '.')
        self.assertEqual(especificacao['encoding']['y']['field'], 'Receita (R$)')
        self.assertEqual(renderizar.call_args.kwargs['alt'], 'Receita (R$)')


try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


class InteracaoDashboardTest(unittest.TestCase):
    def test_unidade_sincroniza_canal_e_preserva_categoria_e_datas(self):
        estado = {'unidade_A': True, 'unidade_B': True, 'canal_loja': True,
                  'canal_web': False, 'categoria': 'Calcas', 'inicio': '02/07/2026'}
        aplicar_filtro_grafico(estado, {'unidade': 'B', 'canal': 'web', 'canais': ['loja', 'web']})
        self.assertFalse(estado['unidade_A'])
        self.assertTrue(estado['unidade_B'])
        self.assertTrue(estado['canal_web'])
        self.assertFalse(estado['canal_loja'])
        self.assertEqual(estado['categoria'], 'Calcas')
        self.assertEqual(estado['inicio'], '02/07/2026')

    def test_clique_no_dia_muda_modo_anual_e_preserva_unidade(self):
        estado = {'tipo_periodo': 'Anual', 'unidade_A': True}
        aplicar_filtro_grafico(estado, {'inicio': date(2026, 7, 12), 'fim': date(2026, 7, 12)})
        self.assertEqual(estado['tipo_periodo'], 'Mensal / personalizado')
        self.assertEqual(estado['inicio'], '12/07/2026')
        self.assertEqual(estado['fim'], '12/07/2026')
        self.assertTrue(estado['unidade_A'])

    def test_periodo_da_barra_nao_amplia_intervalo_personalizado(self):
        self.assertEqual(periodo_do_grafico('2024-02', date(2024, 2, 3), date(2024, 3, 2)),
                         {'inicio': date(2024, 2, 3), 'fim': date(2024, 2, 29)})
        self.assertEqual(periodo_do_grafico('2026', date(2026, 1, 1), date(2026, 12, 31)),
                         {'inicio': date(2026, 1, 1), 'fim': date(2026, 12, 31)})


class AtualizacaoDashboardTest(unittest.TestCase):
    def unidades(self, *datas):
        return [{'unidade_id': str(indice), 'ultima_data_disponivel': data}
                for indice, data in enumerate(datas)]

    def test_datas_iguais_ficam_verdes_inclusive_base_historica(self):
        resultado = avaliar_atualizacao(self.unidades(*[date(2026, 9, 30)] * 3))
        self.assertEqual([linha['cor'] for linha in resultado], ['verde'] * 3)

    def test_data_anterior_fica_vermelha_e_mais_recente_aguarda(self):
        resultado = avaliar_atualizacao(self.unidades(date(2026, 9, 30), date(2026, 9, 29), date(2026, 9, 30)))
        self.assertEqual([linha['cor'] for linha in resultado], ['amarelo', 'vermelho', 'amarelo'])

    def test_data_ausente_impede_validacao_do_conjunto(self):
        resultado = avaliar_atualizacao(self.unidades(date(2026, 9, 30), None, date(2026, 9, 30)))
        self.assertEqual([linha['cor'] for linha in resultado], ['amarelo', 'cinza', 'amarelo'])
        self.assertEqual(avaliar_atualizacao([]), [])
        self.assertEqual([linha['cor'] for linha in avaliar_atualizacao(self.unidades(None, None))], ['cinza', 'cinza'])

    def test_unidade_esperada_ausente_na_consulta_nao_desaparece_do_farol(self):
        resultado = avaliar_atualizacao(self.unidades(date(2026, 9, 30)), esperadas=['0', '1'])
        self.assertEqual([linha['cor'] for linha in resultado], ['amarelo', 'cinza'])
        self.assertEqual(resultado[1]['unidade_id'], '1')


@unittest.skipIf(AppTest is None, 'Instale dashboard/requirements.txt para testar a interface')
class InterfaceDashboardTest(unittest.TestCase):
    def test_erro_inesperado_nao_expoe_mensagem_interna_ou_traceback(self):
        with redirect_stderr(io.StringIO()), patch.dict(os.environ, {'XFIT_DASHBOARD_DEMO': '1', 'XFIT_DASHBOARD_LOCAL_DW': '0'}), patch.object(demo, 'contexto', side_effect=RuntimeError('DETALHE_INTERNO_DE_TESTE')):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard/app.py')).run(timeout=30)
        self.assertEqual(len(app.exception), 1)
        self.assertNotIn('DETALHE_INTERNO_DE_TESTE', app.exception[0].message)
        self.assertFalse(app.exception[0].stack_trace)

    def test_farol_independe_dos_filtros_e_substitui_aviso_anterior(self):
        app = self.executar_demo()
        self.assertEqual([mensagem.value for mensagem in app.success], ['Atualizada', 'Atualizada'])
        self.assertFalse(any('Completude por unidade/data' in mensagem.value for mensagem in app.warning))
        with patch.dict(os.environ, {'XFIT_DASHBOARD_DEMO': '1'}):
            app.checkbox('unidade_demo-web').uncheck().run()
        self.assertEqual([mensagem.value for mensagem in app.success], ['Atualizada', 'Atualizada'])

    def test_limpar_filtros_restaura_periodo_unidades_e_metas(self):
        app = self.executar_demo()
        with patch.dict(os.environ, {'XFIT_DASHBOARD_DEMO': '1'}):
            app.radio('categoria').set_value('Camisetas').run()
            app.text_input('inicio').set_value('02/07/2026').run()
            app.checkbox('unidade_demo-web').uncheck().run()
            app.button('limpar_filtros').click().run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.radio('categoria').value)
        self.assertTrue(app.checkbox('unidade_demo-web').value)
        self.assertEqual(app.text_input('inicio').value, '01/07/2026')
        cards = {card.label: card.value for card in app.metric}
        self.assertEqual(cards['Receita de vendas concluídas'], 'R$ 16.120,00')
        self.assertEqual(cards['Meta de receita'], 'R$ 20.000,00')

    def executar_demo(self):
        with patch.dict(os.environ, {'XFIT_DASHBOARD_DEMO': '1'}), patch.object(dados, 'conectar', side_effect=AssertionError('Demo nao pode acessar DW')):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard/app.py')).run(timeout=30)
        self.assertFalse(app.exception)
        return app

    def test_demo_renderiza_cards_e_nao_acessa_dw(self):
        app = self.executar_demo()
        cards = {card.label: card.value for card in app.metric}
        self.assertEqual(cards['Receita de vendas concluídas'], 'R$ 16.120,00')
        self.assertEqual(cards['Pedidos concluídos'], '186')
        self.assertEqual(cards['Meta de receita'], 'R$ 20.000,00')
        self.assertEqual(cards['Atingimento da receita'], '80,60%')

    def test_categoria_desabilita_metas(self):
        app = self.executar_demo()
        with patch.dict(os.environ, {'XFIT_DASHBOARD_DEMO': '1'}):
            app.radio('categoria').set_value('Camisetas').run()
        self.assertFalse(app.exception)
        self.assertNotIn('Meta de receita', [card.label for card in app.metric])
        self.assertEqual(app.metric[0].value, 'R$ 8.060,00')

    def test_filtro_vazio_e_periodo_parcial(self):
        app = self.executar_demo()
        with patch.dict(os.environ, {'XFIT_DASHBOARD_DEMO': '1'}):
            app.text_input('inicio').set_value('02/07/2026').run()
            self.assertNotIn('Meta de receita', [card.label for card in app.metric])
            for campo in app.checkbox:
                if campo.key.startswith('unidade_'):
                    campo.uncheck()
            app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 0)

    def test_ano_completo_exibe_meta_integral_e_comparacao_parcial(self):
        app = self.executar_demo()
        original = demo.carregar
        def carregar_ano(inicio, fim, unidades, canais, categoria):
            vendas, mix, mensais = original(inicio, fim, unidades, canais, categoria)
            ano = [{**linha, 'ano_mes': f'2026-{mes:02}',
                    'tem_registros_vendas': mes == 7,
                    'receita_liquida_concluida': linha['receita_liquida_concluida'] if mes == 7 else Decimal(0)}
                   for linha in mensais for mes in range(1, 13)]
            return vendas, mix, ano
        with patch.dict(os.environ, {'XFIT_DASHBOARD_DEMO': '1'}), patch.object(demo, 'carregar', side_effect=carregar_ano):
            app.radio('tipo_periodo').set_value('Anual').run()
        self.assertFalse(app.exception)
        cards = {card.label: card.value for card in app.metric}
        self.assertEqual(cards['Meta de receita'], 'R$ 240.000,00')
        self.assertEqual(cards['Atingimento da receita'], '6,72%')
        self.assertTrue(any(titulo.value == 'Metas anuais' for titulo in app.subheader))

    def test_devolucoes_sao_indicadores_visuais_e_rodape_foi_removido(self):
        app = self.executar_demo()
        cards = {card.label: card.value for card in app.metric}
        self.assertEqual(cards['Valor das devoluções registradas'], 'R$ 3.100,00')
        self.assertEqual(cards['Pedidos devolvidos'], '62')
        self.assertEqual(cards['Taxa de devolução'], '25,00%')
        self.assertTrue(any(titulo.value == 'Evolução das devoluções registradas' for titulo in app.subheader))
        self.assertFalse(any('Portfólio com dados demonstrativos' in legenda.value for legenda in app.caption))

    def test_datas_invalidas_exibem_orientacao_em_portugues(self):
        app = self.executar_demo()
        with patch.dict(os.environ, {'XFIT_DASHBOARD_DEMO': '1'}):
            app.text_input('inicio').set_value('31/02/2026').run()
        self.assertFalse(app.exception)
        self.assertTrue(any('DD/MM/AAAA' in mensagem.value for mensagem in app.info))

    def test_sem_login_configurado_nao_consulta_dw(self):
        with patch.dict(os.environ, {'XFIT_DASHBOARD_DEMO': '0', 'XFIT_DASHBOARD_PUBLIC': '0'}), patch.object(dados, 'carregar_contexto', side_effect=AssertionError('Consulta antes de autorizar')):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard/app.py')).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 0)
        self.assertTrue(any('Acesso bloqueado' in aviso.value for aviso in app.warning))

    def test_portfolio_publico_exibe_indicadores_sem_login(self):
        ambiente = {'XFIT_DASHBOARD_DEMO': '0', 'XFIT_DASHBOARD_PUBLIC': '1', 'XFIT_DASHBOARD_LOCAL_DW': '0'}
        with patch.dict(os.environ, ambiente), patch.object(dados, 'carregar_contexto', side_effect=demo.contexto), patch.object(dados, 'carregar_painel', side_effect=demo.carregar):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard/app.py')).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, 'R$ 16.120,00')
        self.assertFalse(any(botao.label in ('Entrar', 'Sair') for botao in app.button))
        self.assertTrue(any('Acesso público' in legenda.value for legenda in app.caption))

    def test_portfolio_publico_nao_expoe_erro_do_banco(self):
        ambiente = {'XFIT_DASHBOARD_DEMO': '0', 'XFIT_DASHBOARD_PUBLIC': '1', 'XFIT_DASHBOARD_LOCAL_DW': '0'}
        with patch.dict(os.environ, ambiente), patch.object(dados, 'carregar_contexto', side_effect=dados.psycopg.OperationalError('SENHA_INTERNA_DE_TESTE')):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard/app.py')).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 0)
        self.assertTrue(any('Não foi possível consultar' in erro.value for erro in app.error))
        self.assertFalse(any('SENHA_INTERNA_DE_TESTE' in erro.value for erro in app.error))

    def test_previa_local_nao_expoe_dw_em_interface_publica(self):
        with patch.dict(os.environ, {'XFIT_DASHBOARD_DEMO': '0', 'XFIT_DASHBOARD_LOCAL_DW': '1'}), patch.object(dados, 'carregar_contexto', side_effect=AssertionError('Acesso publico nao permitido')):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard/app.py')).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 0)
        self.assertTrue(any('Acesso bloqueado' in erro.value for erro in app.error))
