"""Contrato de indicadores e isolamento da camada BI em PostgreSQL descartavel."""

from decimal import Decimal
import os
from pathlib import Path
import unittest

import psycopg

RAIZ = Path(__file__).resolve().parents[1]


class ContratoDashboardSQLTest(unittest.TestCase):
    def test_migration_unica_e_sem_credenciais(self):
        arquivos = list((RAIZ / 'supabase/migrations').glob('*_camada_consumo_dashboard.sql'))
        self.assertEqual(len(arquivos), 1)
        codigo = arquivos[0].read_text(encoding='utf-8')
        self.assertNotIn('password', codigo.lower())
        self.assertNotIn('to authenticated;', codigo.lower())
        self.assertIn('count(distinct (venda.fonte, venda.id_venda))', codigo)
        self.assertIn('full join bi.vw_metas_mensais', codigo)


@unittest.skipUnless(os.environ.get('XFIT_TEST_DW_LOCAL') == '1', 'Postgres descartavel nao solicitado')
class IndicadoresDashboardLocalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conexao = psycopg.connect(host='xfit-dw-verificacao', dbname='xfit_dw_test',
                                     user='postgres', autocommit=True, connect_timeout=5)
        for papel in ('anon', 'authenticated'):
            if not cls.conexao.execute('select 1 from pg_roles where rolname=%s', (papel,)).fetchone():
                cls.conexao.execute(psycopg.sql.SQL('create role {}').format(psycopg.sql.Identifier(papel)))
        cls.conexao.execute((RAIZ / 'sql/schema_dw.sql').read_text(encoding='utf-8'))
        if not cls.conexao.execute("select 1 from pg_namespace where nspname='bi'").fetchone():
            migration = next((RAIZ / 'supabase/migrations').glob('*_camada_consumo_dashboard.sql'))
            cls.conexao.execute(migration.read_text(encoding='utf-8'))
        if not cls.conexao.execute("select 1 from pg_roles where rolname='xfit_dashboard_teste'").fetchone():
            cls.conexao.execute('create role xfit_dashboard_teste login nosuperuser nobypassrls')
            cls.conexao.execute('grant xfit_dashboard to xfit_dashboard_teste')

    @classmethod
    def tearDownClass(cls):
        cls.conexao.close()

    def setUp(self):
        self.conexao.execute('begin')
        self.addCleanup(self.encerrar_transacao)
        self.conexao.execute('truncate stg.stg_vendas,stg.stg_produtos,stg.stg_metas,'
                             'dw.fato_vendas,dw.fato_metas,dw.dim_produto,dw.dim_unidade,'
                             'dw.dim_data,etl.cargas_dw restart identity cascade')
        self.conexao.execute("select dw.carregar_dim_data('2020-01-01','2020-02-29')")
        self.conexao.execute("insert into dw.dim_unidade (unidade_id,canal,unidade) values "
                             "('LJ-BQ','loja_fisica','Barbacena'),('EC-BR','ecommerce','Ecommerce')")
        self.conexao.execute("insert into dw.dim_produto (produto_id,produto,categoria,preco_lista,custo_padrao) "
                             "values ('P1','Produto A','A',30,10),('P2','Produto B','B',30,10)")
        self.conexao.execute("insert into dw.fato_vendas "
            "(venda_item_id,fonte,id_venda,data_id,produto_id,unidade_id,quantidade,"
            "valor_bruto,valor_desconto,valor_liquido,custo_total,margem_bruta,status_pedido) values "
            "('1','fisica','V1',20200102,'P1','LJ-BQ',1,30,0,30,10,20,'concluida'),"
            "('2','fisica','V1',20200102,'P2','LJ-BQ',2,60,0,60,20,40,'concluida'),"
            "('3','fisica','V2',20200103,'P1','LJ-BQ',1,30,0,30,10,20,'devolvida'),"
            "('4','fisica','V3',20200103,'P1','LJ-BQ',1,30,0,0,10,0,'cancelada'),"
            "('5','online','V1',20200102,'P1','EC-BR',1,50,0,50,20,30,'concluida')")
        self.conexao.execute("insert into dw.fato_metas "
            "(meta_id,ano_mes,data_id_mes,unidade_id,meta_receita_liquida,meta_pedidos,"
            "meta_ticket_medio,meta_margem_bruta_pct,meta_taxa_devolucao_pct) values "
            "('M1','2020-01',20200101,'LJ-BQ',100,5,20,0.5,0.1),"
            "('M2','2020-01',20200101,'EC-BR',200,10,20,0.5,0.1),"
            "('M3','2020-02',20200201,'LJ-BQ',100,5,20,0.5,0.1)")

    def encerrar_transacao(self):
        self.conexao.execute('rollback')

    def leitura(self, consulta):
        self.conexao.execute('set local role xfit_dashboard')
        return self.conexao.execute(consulta).fetchone()

    def test_receita_pedidos_itens_e_ticket_com_multiplos_produtos(self):
        valores = self.leitura('select sum(receita_liquida_registrada),sum(receita_liquida_concluida),'
                              'sum(margem_bruta_concluida),sum(pedidos_total),sum(pedidos_concluidos),'
                              'sum(itens_vendidos),sum(receita_liquida_concluida)/sum(pedidos_concluidos) '
                              'from bi.vw_vendas_diarias')
        self.assertEqual(valores, (170, 140, 90, 4, 2, 4, 70))

    def test_taxas_usam_denominadores_compativeis(self):
        valores = self.leitura('select 100*sum(pedidos_devolvidos)/sum(pedidos_concluidos+pedidos_devolvidos),'
                              '100*sum(pedidos_cancelados)/sum(pedidos_total),'
                              '100*sum(margem_bruta_concluida)/sum(receita_liquida_concluida) '
                              'from bi.vw_vendas_diarias')
        self.assertAlmostEqual(valores[0], Decimal(100) / 3)
        self.assertEqual(valores[1], 25)
        self.assertAlmostEqual(valores[2], Decimal(9000) / 140)

    def test_meta_nao_multiplica_por_item_e_mes_sem_vendas_nao_vira_fracasso(self):
        self.assertEqual(self.leitura("select meta_receita_liquida,receita_liquida_concluida,"
                                     "atingimento_receita_pct from bi.vw_desempenho_mensal "
                                     "where ano_mes='2020-01' and unidade_id='LJ-BQ'"), (100, 90, 90))
        self.assertEqual(self.leitura("select meta_receita_liquida,tem_registros_vendas,atingimento_receita_pct "
                                     "from bi.vw_desempenho_mensal where ano_mes='2020-02'"), (100, False, None))
        self.assertEqual(self.leitura("select sum(meta_receita_liquida) from bi.vw_desempenho_mensal "
                                     "where ano_mes='2020-01'"), (300,))

    def test_categoria_unica_tem_pedidos_corretos_e_nao_reparte_meta(self):
        self.assertEqual(self.leitura("select sum(receita_liquida_concluida),sum(pedidos_concluidos) "
                                     "from bi.vw_vendas_diarias_categoria where categoria='A'"), (80, 2))
        self.assertEqual(self.leitura("select sum(pedidos_concluidos) from bi.vw_vendas_diarias_categoria"), (3,))
        self.assertEqual(self.leitura("select sum(pedidos_concluidos) from bi.vw_vendas_diarias"), (2,))
        self.assertEqual(self.leitura("select count(*) from information_schema.columns "
                                     "where table_schema='bi' and table_name='vw_vendas_diarias_categoria' "
                                     "and column_name like 'meta_%'"), (0,))

    def test_periodo_canal_unidade_e_categoria_filtram_sem_misturar_denominadores(self):
        self.assertEqual(self.leitura("select sum(receita_liquida_concluida),sum(pedidos_concluidos) "
                                     "from bi.vw_vendas_diarias_categoria where data_venda between "
                                     "'2020-01-02' and '2020-01-02' and unidade_id='LJ-BQ' "
                                     "and canal='loja_fisica' and categoria='B'"), (60, 1))

    def test_receita_zero_retorna_taxa_e_ticket_nulos(self):
        self.assertEqual(self.leitura("select ticket_medio,margem_bruta_pct from bi.vw_vendas_diarias "
                                     "where data_venda='2020-01-03'"), (None, None))

    def test_meta_zero_e_meta_ausente_nao_ocultam_vendas(self):
        self.conexao.execute("update dw.fato_metas set meta_receita_liquida=0 where unidade_id='EC-BR'")
        self.assertEqual(self.leitura("select receita_liquida_concluida,atingimento_receita_pct "
                                     "from bi.vw_desempenho_mensal where unidade_id='EC-BR'"), (50, None))
        self.conexao.execute('reset role')
        self.conexao.execute("delete from dw.fato_metas where unidade_id='EC-BR'")
        self.assertEqual(self.leitura("select receita_liquida_concluida,tem_meta "
                                     "from bi.vw_desempenho_mensal where unidade_id='EC-BR'"), (50, False))

    def test_atualizacao_nao_inventa_completude_e_distingue_data_de_execucao(self):
        self.conexao.execute("insert into etl.cargas_dw (carga_dw_id,etapa,status,atualizado_em) "
                             "values ('dw-diario-20200104','dw','sucesso','2020-02-01'),"
                             "('pendente','dw','iniciada','2020-02-02')")
        valores = self.leitura('select ultima_data_venda::text,ultima_data_diaria_publicada::text,'
                              'cargas_sem_conclusao,completude_datalake_disponivel from bi.vw_atualizacao')
        self.assertEqual(valores, ('2020-01-03', '2020-01-04', 1, False))

    def test_views_obedecem_rls_do_owner_nao_administrativo(self):
        self.conexao.execute('alter policy bi_leitura on dw.fato_vendas using (false)')
        self.assertEqual(self.leitura('select count(*) from bi.vw_vendas_diarias'), (0,))

    def test_migration_funciona_com_administrador_sem_superuser(self):
        with psycopg.connect(host='xfit-dw-verificacao', dbname='xfit_dw_test',
                             user='postgres', autocommit=True) as administrador:
            for papel in ('xfit_migrador_bi_teste','xfit_bi_owner_mig_teste','xfit_dashboard_mig_teste'):
                self.assertIsNone(administrador.execute('select 1 from pg_roles where rolname=%s', (papel,)).fetchone())
            self.assertIsNone(administrador.execute("select 1 from pg_database where datname='xfit_bi_mig_teste'").fetchone())
            administrador.execute('create role xfit_migrador_bi_teste login createrole nosuperuser nobypassrls')
            administrador.execute('create database xfit_bi_mig_teste owner xfit_migrador_bi_teste')
            try:
                with psycopg.connect(host='xfit-dw-verificacao', dbname='xfit_bi_mig_teste',
                                     user='xfit_migrador_bi_teste', autocommit=True) as migrador:
                    migrador.execute((RAIZ / 'sql/schema_dw.sql').read_text(encoding='utf-8'))
                    migration = next((RAIZ / 'supabase/migrations').glob('*_camada_consumo_dashboard.sql'))
                    codigo = migration.read_text(encoding='utf-8').replace('xfit_bi_owner','xfit_bi_owner_mig_teste')
                    codigo = codigo.replace('xfit_dashboard','xfit_dashboard_mig_teste')
                    migrador.execute(codigo)
                    self.assertEqual(migrador.execute("select pg_has_role(current_user,"
                                                       "'xfit_bi_owner_mig_teste','SET')").fetchone(), (False,))
                    self.assertEqual(migrador.execute("select count(*) from pg_views where schemaname='bi'").fetchone(), (6,))
            finally:
                administrador.execute('drop database xfit_bi_mig_teste')
                administrador.execute('drop role if exists xfit_dashboard_mig_teste')
                administrador.execute('drop role if exists xfit_bi_owner_mig_teste')
                administrador.execute('drop role xfit_migrador_bi_teste')

    def test_sessao_nao_administrativa_le_views_mas_nega_bases_escrita_e_escalada(self):
        self.conexao.execute('commit')
        self.conexao.execute('begin')
        with psycopg.connect(host='xfit-dw-verificacao', dbname='xfit_dw_test',
                             user='xfit_dashboard_teste', autocommit=True, connect_timeout=5) as leitor:
            leitor.execute("set statement_timeout='5s'")
            leitor.execute('set role xfit_dashboard')
            for consulta in ('select count(*) from bi.vw_atualizacao',
                             'select count(*) from bi.vw_vendas_diarias'):
                leitor.execute(consulta).fetchone()
            for consulta in ('select * from dw.fato_vendas', 'select * from stg.stg_vendas',
                             'select * from etl.cargas_dw', 'select * from bi.vw_vendas_agrupadas',
                             'update dw.fato_vendas set quantidade=quantidade where false',
                             'set role xfit_bi_owner', 'set role postgres'):
                with self.subTest(consulta=consulta), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    leitor.execute(consulta)
            self.assertEqual(leitor.execute("select has_table_privilege(current_user,"
                                            "'bi.vw_vendas_diarias','UPDATE')").fetchone(), (False,))

    def test_anonimo_e_autenticado_nao_recebem_acesso_ao_bi(self):
        for papel in ('anon', 'authenticated'):
            with self.subTest(papel=papel):
                self.conexao.execute(psycopg.sql.SQL('set local role {}').format(psycopg.sql.Identifier(papel)))
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.conexao.transaction():
                        self.conexao.execute('select * from bi.vw_atualizacao')
                self.conexao.execute('reset role')


if __name__ == '__main__':
    unittest.main()
