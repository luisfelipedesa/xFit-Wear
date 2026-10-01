import sys
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from preparar_carga_supabase import literal_sql, preparar_lotes


class PrepararCargaSupabaseTest(unittest.TestCase):
    def test_literal_preserva_decimal_null_e_aspas(self):
        self.assertEqual(literal_sql(Decimal('123456.78')), '123456.78')
        self.assertEqual(literal_sql(None), 'NULL')
        self.assertEqual(literal_sql("d'agua"), "'d''agua'")
        self.assertEqual(literal_sql("x'); delete from dw.fato_vendas; --"),
                         "'x''); delete from dw.fato_vendas; --'")

    def test_lote_invalido_bloqueia_antes_de_auditar(self):
        with patch('preparar_carga_supabase.auditar_fontes_da_carga') as auditoria:
            with self.assertRaises(ValueError):
                preparar_lotes('teste', 0)
            auditoria.assert_not_called()

    def test_staging_reprovada_nao_cria_lotes(self):
        manifesto = {'status': 'sucesso', 'backup': {'arquivos_ausentes': []}}
        with patch('preparar_carga_supabase.auditar_fontes_da_carga', return_value=manifesto), \
             patch('preparar_carga_supabase.gerar_staging', return_value={}), \
             patch('preparar_carga_supabase.validar_staging', return_value={'pode_promover_dw': False}):
            with self.assertRaisesRegex(ValueError, 'Staging reprovada'):
                preparar_lotes('teste-bloqueio-supabase')
        self.assertFalse((Path(__file__).resolve().parents[1] / 'data/processed/dw/teste-bloqueio-supabase').exists())


if __name__ == '__main__':
    unittest.main()
