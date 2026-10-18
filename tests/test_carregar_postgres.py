import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

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

    def test_totais_iguais_nao_escondem_registros_divergentes(self):
        cursor = Mock()
        cursor.fetchone.side_effect = [(1, 10, 5), (True,)]
        with self.assertRaisesRegex(ValueError, 'Registros transferidos'):
            carga.conferir_transferencia_staging(cursor, {'stg_produtos': [
                {'preco_lista': 10, 'custo_padrao': 5}]})

    def test_perda_durante_commit_nao_afirma_rollback_nem_marca_erro(self):
        conexao = MagicMock()
        conexao.closed = True
        conexao.execute.return_value.fetchone.return_value = (True,)
        conexao.transaction.return_value.__enter__ = Mock()
        conexao.transaction.return_value.__exit__ = Mock(side_effect=carga.psycopg.OperationalError('privado'))
        with patch.object(carga, 'conferir_papel_conexao'), \
             patch.object(carga, 'preparar_staging_aprovada', return_value=({}, {'linhas': {}})), \
             patch.object(carga, 'enviar_staging_postgres'), \
             patch.object(carga, 'conferir_transferencia_staging'), \
             patch.object(carga, 'promover_dw_postgres'), \
             patch.object(carga, 'registrar_status_local') as registrar:
            with self.assertRaises(carga.psycopg.OperationalError):
                carga.executar_carga_postgres(conexao, 'commit-incerto')
        self.assertEqual(registrar.call_args.args[1], 'indeterminada')
        self.assertIn('reconciliar', registrar.call_args.args[2])
        self.assertFalse(any('update etl.cargas_dw' in str(chamada) for chamada in conexao.execute.call_args_list))


if __name__ == '__main__':
    unittest.main()
