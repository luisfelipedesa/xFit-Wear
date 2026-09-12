"""# Parametros Python para carga SQL da dim_data

Python calcula a janela aprovada; SQL cria e carrega a tabela. Se este teste
falhar, alguem pode ter voltado a misturar schema de DW dentro do Python.
"""

from datetime import date
import unittest
from unittest.mock import patch

from src import preparar_dim_data_dw


class PreparoDimDataDwTest(unittest.TestCase):
    def test_janela_da_dim_data_cobre_vendas_e_metas_futuras(self) -> None:
        vendas = [{"data_venda": "2026-09-06"}]
        metas = [{"ano_mes": "2026-12"}]

        data_inicial, data_final = preparar_dim_data_dw.calcular_janela_calendario_dim_data(vendas, metas)

        self.assertEqual(data_inicial, date(2026, 9, 6))
        self.assertEqual(data_final, date(2026, 12, 31))

    def test_preparo_aprovado_entrega_parametros_para_sql(self) -> None:
        staging = {
            "staging": {
                "stg_vendas": [{"data_venda": "2026-09-01"}],
                "stg_metas": [{"ano_mes": "2026-09"}],
            }
        }
        relatorio = {"pode_promover_dw": True}

        with patch.object(preparar_dim_data_dw, "gerar_staging", return_value=staging), \
             patch.object(preparar_dim_data_dw, "validar_staging", return_value=relatorio):
            resultado = preparar_dim_data_dw.preparar_chamada_sql_dim_data(carga_dw_id="dw-dim-data-teste")

        self.assertTrue(resultado["pode_executar_sql"])
        self.assertEqual(resultado["data_inicial"], "2026-09-01")
        self.assertEqual(resultado["data_final"], "2026-09-30")
        self.assertIn("dw.carregar_dim_data", resultado["sql_funcao"])

    def test_staging_reprovada_nao_entrega_parametros_de_carga(self) -> None:
        with patch.object(preparar_dim_data_dw, "gerar_staging", return_value={"staging": {}}), \
             patch.object(preparar_dim_data_dw, "validar_staging", return_value={"pode_promover_dw": False}):
            resultado = preparar_dim_data_dw.preparar_chamada_sql_dim_data(carga_dw_id="dw-reprovado")

        self.assertFalse(resultado["pode_executar_sql"])
        self.assertNotIn("data_inicial", resultado)
        self.assertNotIn("data_final", resultado)


if __name__ == "__main__":
    unittest.main()
