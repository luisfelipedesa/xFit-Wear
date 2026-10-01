"""Testes reais opt-in: XFIT_TEST_POSTGRES=1, com o .env privado configurado."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import psycopg
import carregar_postgres as carga


@unittest.skipUnless(os.environ.get('XFIT_TEST_POSTGRES') == '1', 'Postgres real nao solicitado')
class IntegracaoPostgresTest(unittest.TestCase):
    def setUp(self):
        self.parametros = carga.configuracao_postgres()
        self.certificado = self.enterContext(carga.certificado_postgres())
        self.conexao = self.enterContext(psycopg.connect(**self.parametros, sslrootcert=self.certificado))

    def totais(self):
        return self.conexao.execute('''select
            (select count(*) from stg.stg_vendas), (select sum(quantidade) from stg.stg_vendas),
            (select sum(valor_liquido) from stg.stg_vendas),
            (select count(*) from dw.fato_vendas), (select sum(quantidade) from dw.fato_vendas),
            (select sum(valor_liquido) from dw.fato_vendas), (select count(*) from dw.fato_metas)
        ''').fetchone()

    def test_papel_nao_pode_apagar_criar_schema_ou_ler_auth(self):
        for comando in ('delete from dw.fato_vendas where false', 'truncate dw.fato_vendas',
                        'create table public.xfit_teste_proibido (id integer)',
                        'select count(*) from auth.users', 'set local role postgres'):
            with self.subTest(comando=comando), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with self.conexao.transaction():
                    self.conexao.execute(comando)

    def test_bloqueio_impede_segunda_carga_sem_registrar_attempt(self):
        identificador = 'teste-bloqueio-' + uuid4().hex
        self.conexao.execute('select pg_advisory_lock(%s)', (carga.CHAVE_BLOQUEIO,))
        try:
            with psycopg.connect(**self.parametros, sslrootcert=self.certificado) as segunda:
                with self.assertRaisesRegex(ValueError, 'Outra carga'):
                    carga.executar_carga_postgres(segunda, identificador)
            self.assertEqual(self.conexao.execute(
                'select count(*) from etl.cargas_dw where carga_dw_id = %s',
                ('dw-' + identificador,)).fetchone(), (0,))
        finally:
            self.conexao.execute('select pg_advisory_unlock(%s)', (carga.CHAVE_BLOQUEIO,))

    def test_falha_de_promocao_reverte_staging_e_dw(self):
        antes = self.totais()
        identificador = 'teste-rollback-' + uuid4().hex
        promover_original = carga.promover_dw_postgres

        def promover_e_falhar(cursor, carga_dw_id):
            promover_original(cursor, carga_dw_id)
            cursor.execute('''update stg.stg_vendas set quantidade = quantidade + 1
                where (fonte, id_venda, produto_id) =
                (select fonte, id_venda, produto_id from stg.stg_vendas limit 1)''')
            cursor.execute('''update dw.fato_vendas set quantidade = quantidade + 1
                where venda_item_id = (select venda_item_id from dw.fato_vendas limit 1)''')
            raise ValueError('segredo-que-nao-pode-ir-para-log')

        with patch.object(carga, 'promover_dw_postgres', side_effect=promover_e_falhar):
            with self.assertRaises(ValueError):
                carga.executar_carga_postgres(self.conexao, identificador)
        self.assertEqual(self.totais(), antes)
        status, mensagem = self.conexao.execute(
            'select status, mensagem_publica from etl.cargas_dw where carga_dw_id = %s',
            ('dw-' + identificador,)).fetchone()
        self.assertEqual(status, 'erro')
        self.assertNotIn('segredo-que-nao-pode-ir-para-log', mensagem)

    def test_reprocessamento_preserva_itens_metas_e_valores(self):
        antes = self.totais()
        resultado = carga.executar_carga_postgres(self.conexao, 'teste-reprocessar-' + uuid4().hex)
        self.assertEqual(resultado['status'], 'sucesso')
        self.assertEqual(self.totais(), antes)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            carga.executar_carga_postgres(self.conexao, resultado['carga_id'])
        self.assertEqual(self.conexao.execute(
            'select status from etl.cargas_dw where carga_dw_id = %s',
            (resultado['carga_dw_id'],)).fetchone(), ('sucesso',))


if __name__ == '__main__':
    unittest.main()
