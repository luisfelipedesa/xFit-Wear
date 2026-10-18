"""Integracao opt-in em PostgreSQL descartavel, sem usar o .env do projeto."""

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / 'src'))
import carregar_postgres as carga


def staging_de_teste():
    produtos = [{'produto_id': 'P1', 'produto': 'Produto A', 'categoria': 'Teste',
                 'preco_lista': 30, 'custo_padrao': 10},
                {'produto_id': 'P2', 'produto': 'Produto B', 'categoria': 'Teste',
                 'preco_lista': 30, 'custo_padrao': 10}]
    vendas = [{'fonte': 'teste', 'id_venda': 'V' + str(indice), 'data_venda': '2020-01-01',
               'hora_venda': '10:00:00', 'cliente_id': 'demonstrativo', 'produto_id': produto['produto_id'],
               'quantidade': 1, 'valor_bruto': 30, 'valor_desconto': 0, 'valor_liquido': 30,
               'custo_total': 10, 'margem_bruta': 20, 'status_pedido': 'concluida',
               'canal': 'loja_fisica', 'unidade_id': 'LJ-BQ'}
              for indice, produto in enumerate(produtos)]
    metas = [{'ano_mes': '2020-01', 'canal': 'loja_fisica', 'unidade_id': 'LJ-BQ',
              'meta_receita_liquida': 300, 'meta_pedidos': 10, 'meta_ticket_medio': 30,
              'meta_margem_bruta_pct': 60, 'meta_taxa_devolucao_pct': 2}]
    for tabela in (produtos, vendas, metas):
        for registro in tabela:
            registro['data_processamento'] = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return {'stg_produtos': produtos, 'stg_vendas': vendas, 'stg_metas': metas}


@unittest.skipUnless(os.environ.get('XFIT_TEST_DW_LOCAL') == '1', 'Postgres descartavel nao solicitado')
class ProtecoesDWLocalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conexao = psycopg.connect(host='xfit-dw-verificacao', dbname='xfit_dw_test',
                                     user='postgres', autocommit=True, connect_timeout=5)
        for papel in ('anon', 'authenticated'):
            if not cls.conexao.execute('select 1 from pg_roles where rolname=%s', (papel,)).fetchone():
                cls.conexao.execute(psycopg.sql.SQL('create role {}').format(psycopg.sql.Identifier(papel)))
        cls.conexao.execute((RAIZ / 'sql/schema_dw.sql').read_text(encoding='utf-8'))
        if not cls.conexao.execute("select 1 from pg_roles where rolname='xfit_pipeline'").fetchone():
            cls.conexao.execute((RAIZ / 'supabase/migrations/20261001115245_papel_pipeline_postgres.sql').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        cls.conexao.close()

    def setUp(self):
        self.conexao.execute('reset role')
        self.conexao.execute('truncate stg.stg_produtos, stg.stg_metas, stg.stg_vendas, '
                             'dw.fato_vendas, dw.fato_metas, dw.dim_produto, dw.dim_unidade, '
                             'dw.dim_data, etl.cargas_dw restart identity cascade')
        self.conexao.execute('set role xfit_pipeline')
        self.staging = staging_de_teste()

    def carregar(self, staging=None, identificador=None):
        staging = staging if staging is not None else self.staging
        with patch.object(carga, 'conferir_papel_conexao'), \
             patch.object(carga, 'preparar_staging_aprovada', return_value=(staging, {'linhas': {}})), \
             patch.object(carga, 'registrar_status_local'):
            return carga.executar_carga_postgres(self.conexao, identificador or 'teste-' + uuid4().hex)

    def test_carga_reprocessada_nao_duplica_e_id_repetido_bloqueia(self):
        resultado = self.carregar(identificador='primeira')
        self.assertEqual(resultado['status'], 'sucesso')
        self.carregar()
        self.assertEqual(self.conexao.execute('select count(*), sum(valor_liquido) from dw.fato_vendas').fetchone(),
                         (2, 60))
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.carregar(identificador='primeira')
        self.assertEqual(self.conexao.execute("select status from etl.cargas_dw where carga_dw_id='dw-primeira'").fetchone(),
                         ('sucesso',))

    def test_compensacao_financeira_na_transferencia_e_bloqueada_com_rollback(self):
        self.carregar()
        enviar_original = carga.enviar_staging_postgres

        def enviar_com_corrupcao(cursor, staging):
            enviar_original(cursor, staging)
            cursor.execute("update stg.stg_vendas set valor_liquido = valor_liquido + "
                           "case when id_venda = 'V0' then 1 else -1 end")

        with patch.object(carga, 'enviar_staging_postgres', side_effect=enviar_com_corrupcao):
            with self.assertRaisesRegex(ValueError, 'Registros transferidos'):
                self.carregar()
        self.assertEqual(self.conexao.execute('select distinct valor_liquido from stg.stg_vendas').fetchall(), [(30,)])

    def test_falha_depois_da_promocao_reverte_staging_e_dw(self):
        self.carregar()
        alterada = deepcopy(self.staging)
        alterada['stg_vendas'][0]['valor_liquido'] = 31
        promover_original = carga.promover_dw_postgres

        def promover_e_falhar(cursor, carga_id):
            promover_original(cursor, carga_id)
            raise ValueError('Falha controlada')

        with patch.object(carga, 'promover_dw_postgres', side_effect=promover_e_falhar):
            with self.assertRaises(ValueError):
                self.carregar(alterada)
        self.assertEqual(self.conexao.execute('select sum(valor_liquido) from dw.fato_vendas').fetchone(), (60,))
        self.assertEqual(self.conexao.execute('select sum(valor_liquido) from stg.stg_vendas').fetchone(), (60,))

    def test_reconciliacao_sql_detecta_produto_nao_atualizado(self):
        self.carregar()
        with self.assertRaisesRegex(psycopg.errors.RaiseException, 'Reconciliacao'):
            with self.conexao.transaction():
                self.conexao.execute('reset role')
                self.conexao.execute("create or replace function dw.carregar_dim_produto() returns integer "
                                     "language sql as 'select 0'")
                self.conexao.execute('set local role xfit_pipeline')
                self.conexao.execute("update stg.stg_produtos set produto='Cadastro alterado' where produto_id='P1'")
                self.conexao.execute("insert into etl.cargas_dw (carga_dw_id, etapa, status) values ('produto', 'dw', 'iniciada')")
                carga.promover_dw_postgres(self.conexao.cursor(), 'produto')

    def test_banco_nega_orfaos_duplicatas_e_acesso_anonimo(self):
        self.carregar()
        for comando, erro in [
            ("update dw.fato_vendas set produto_id='inexistente'", psycopg.errors.ForeignKeyViolation),
            ("insert into dw.dim_produto (produto_id, produto, categoria, preco_lista, custo_padrao) "
             "values ('P1', 'Duplicado', 'Teste', 1, 1)", psycopg.errors.UniqueViolation),
            ('update dw.fato_vendas set quantidade=0', psycopg.errors.CheckViolation),
            ('delete from dw.fato_vendas', psycopg.errors.InsufficientPrivilege)]:
            with self.subTest(comando=comando), self.assertRaises(erro):
                with self.conexao.transaction():
                    self.conexao.execute(comando)
        self.conexao.execute('reset role')
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.conexao.transaction():
                self.conexao.execute('set local role anon')
                self.conexao.execute('select * from dw.fato_vendas')

    def test_bloqueios_negam_segundo_job_e_escritor_concorrente(self):
        self.carregar()
        with psycopg.connect(host='xfit-dw-verificacao', dbname='xfit_dw_test',
                             user='postgres', autocommit=True) as segunda:
            segunda.execute('set role xfit_pipeline')
            segunda.execute('select pg_advisory_lock(%s)', (carga.CHAVE_BLOQUEIO,))
            try:
                with self.assertRaisesRegex(ValueError, 'Outra carga'):
                    self.carregar(identificador='concorrente')
                self.assertEqual(self.conexao.execute(
                    "select count(*) from etl.cargas_dw where carga_dw_id='dw-concorrente'").fetchone(), (0,))
            finally:
                segunda.execute('select pg_advisory_unlock(%s)', (carga.CHAVE_BLOQUEIO,))
            with self.conexao.transaction():
                self.conexao.execute('lock table stg.stg_vendas in share row exclusive mode')
                segunda.execute("set lock_timeout='200ms'")
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    segunda.execute('update stg.stg_vendas set quantidade=quantidade+1')


if __name__ == '__main__':
    unittest.main()
