"""Verificacao remota opt-in: somente leitura com credencial propria de BI."""

from datetime import date
from decimal import Decimal
import json
import os
import unittest
from unittest.mock import patch

import psycopg

from dashboard import dados
from dashboard.configurar_local import CONFIG_LOCAL
from dashboard.metricas import chaves_mensais, resumir, resumir_metas


@unittest.skipUnless(os.environ.get('XFIT_TEST_DASHBOARD_REMOTO') == '1', 'DW BI remoto nao solicitado')
class DashboardDWRemotoTest(unittest.TestCase):
    def setUp(self):
        self.ambiente = patch.dict(os.environ, json.loads(CONFIG_LOCAL.read_text(encoding='utf-8')))
        self.ambiente.start()
        self.addCleanup(self.ambiente.stop)

    def test_tls_identidade_e_leitura_somente_nas_views(self):
        with dados.conectar() as conexao:
            self.assertTrue(conexao.pgconn.ssl_in_use)
            papel = conexao.execute('select current_user as papel, session_user as login').fetchone()
            self.assertEqual(papel, {'papel': 'xfit_dashboard', 'login': 'xfit_dashboard_app'})
            self.assertEqual(conexao.execute('show transaction_read_only').fetchone()['transaction_read_only'], 'on')
            for view in ('vw_vendas_diarias', 'vw_vendas_diarias_categoria',
                         'vw_metas_mensais', 'vw_desempenho_mensal', 'vw_atualizacao'):
                conexao.execute(f'select * from bi.{view} limit 1').fetchall()
                acesso = conexao.execute("select has_table_privilege(current_user,%s,'INSERT,UPDATE,DELETE') as escrita", [f'bi.{view}']).fetchone()
                self.assertFalse(acesso['escrita'])
            for consulta in ('select * from dw.fato_vendas limit 0',
                             'select * from stg.stg_vendas limit 0',
                             'select * from etl.cargas_dw limit 0',
                             'select * from bi.vw_vendas_agrupadas limit 0',
                             'set local role xfit_bi_owner', 'set local role xfit_pipeline',
                             'set local role postgres'):
                with self.subTest(consulta=consulta):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        with conexao.transaction():
                            conexao.execute(consulta)

    def test_referencia_julho_e_filtros_sem_fixture_visual(self):
        atualizacao, unidades, categorias = dados.carregar_contexto()
        self.assertEqual(atualizacao['ultima_data_venda'], date(2026, 7, 31))
        self.assertEqual(len(unidades), 3)
        ids = [linha['unidade_id'] for linha in unidades]
        canais = list({linha['canal'] for linha in unidades})
        vendas, mix, mensais = dados.carregar_painel(date(2026, 7, 1), date(2026, 7, 31), ids, canais)
        totais = resumir(vendas)
        self.assertEqual(totais['receita_liquida_concluida'], Decimal('153960.75'))
        self.assertEqual(totais['pedidos_concluidos'], 1138)
        self.assertEqual(totais['itens_vendidos'], 1420)
        self.assertEqual(resumir_metas(mensais)['meta'], Decimal('206574.40'))
        self.assertEqual(sum(linha['receita_liquida_concluida'] for linha in mix), Decimal('153960.75'))
        self.assertTrue(categorias)
        vendas, mix, mensais = dados.carregar_painel(date(2026, 7, 1), date(2026, 7, 31), ids[:1], canais, categorias[0])
        self.assertTrue(all(linha['unidade_id'] == ids[0] and linha['categoria'] == categorias[0] for linha in vendas))

    def test_comparativo_anual_2026_inclui_metas_dos_doze_meses(self):
        _, unidades, _ = dados.carregar_contexto()
        ids = [linha['unidade_id'] for linha in unidades]
        canais = list({linha['canal'] for linha in unidades})
        inicio, fim = date(2026, 1, 1), date(2026, 12, 31)
        vendas, _, mensais = dados.carregar_painel(inicio, fim, ids, canais)
        resumo = resumir_metas(mensais, chaves_mensais(inicio, fim, ids))
        self.assertEqual(len(mensais), 36)
        self.assertEqual(resumo['meta'], Decimal('2807581.60'))
        self.assertEqual(resumir(vendas)['receita_liquida_concluida'], Decimal('1033764.33'))
        self.assertEqual(resumo['realizado'], Decimal('1033764.33'))
        self.assertEqual(round(resumo['atingimento'], 2), Decimal('36.82'))
        self.assertFalse(resumo['cobertura'])
