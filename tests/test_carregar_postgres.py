import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import carregar_postgres as carga


class ConfiguracaoCargaPostgresTest(unittest.TestCase):
    def ambiente(self, usuario='xfit_pipeline.projeto', porta='5432'):
        return {'XFIT_PG_HOST': 'exemplo.pooler.supabase.com', 'XFIT_PG_PORT': porta,
                'XFIT_PG_DATABASE': 'postgres', 'XFIT_PG_USER': usuario,
                'XFIT_PG_PASSWORD': 'segredo-apenas-do-teste'}

    def test_configuracao_exige_tls_e_papel_restrito(self):
        with patch.dict(os.environ, self.ambiente(), clear=True), patch.object(carga, 'carregar_env'):
            parametros = carga.configuracao_postgres()
        self.assertEqual(parametros['sslmode'], 'verify-full')
        self.assertTrue(parametros['autocommit'])
        self.assertIsNone(parametros['prepare_threshold'])

    def test_administrador_e_pooler_transacional_sao_bloqueados(self):
        for ambiente in (self.ambiente(usuario='postgres.projeto'), self.ambiente(porta='6543')):
            with self.subTest(ambiente=ambiente['XFIT_PG_USER']), \
                 patch.dict(os.environ, ambiente, clear=True), patch.object(carga, 'carregar_env'):
                with self.assertRaises(ValueError):
                    carga.configuracao_postgres()

    def test_papel_com_bypassrls_e_bloqueado(self):
        conexao = Mock()
        conexao.execute.return_value.fetchone.return_value = ('xfit_pipeline', False, False, False, True)
        with self.assertRaises(ValueError):
            carga.conferir_papel_conexao(conexao)

    def test_tls_confere_cliente_em_vez_do_trecho_interno_do_pooler(self):
        conexao = Mock()
        conexao.execute.return_value.fetchone.return_value = ('xfit_pipeline', False, False, False, False)
        conexao.pgconn.ssl_in_use = True
        carga.conferir_papel_conexao(conexao)
        conexao.pgconn.ssl_in_use = False
        with self.assertRaises(ValueError):
            carga.conferir_papel_conexao(conexao)

    def test_divergencia_de_transferencia_bloqueia_promocao(self):
        cursor = Mock()
        cursor.fetchone.return_value = (1, 99, 0)
        with self.assertRaisesRegex(ValueError, 'snapshot aprovado'):
            carga.conferir_transferencia_staging(cursor, {'stg_produtos': [
                {'preco_lista': 10, 'custo_padrao': 5}]})


if __name__ == '__main__':
    unittest.main()
