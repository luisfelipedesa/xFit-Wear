"""# Numeros aceitos na staging

## Limite desta etapa
Valida finitude e integralidade antes da staging devolver dados padronizados.
Nao cobre materialidade financeira; isso ja mora em validate_staging.py.
"""
from decimal import Decimal
import unittest

from src import staging_data as staging


def venda_bruta_minima() -> dict:
    return {
        "id_venda": "V1",
        "data_venda": "2026-01-10",
        "hora_venda": "10:00:00",
        "cliente_id": "CLI-00001",
        "produto_id": "P1",
        "quantidade": "1",
        "valor_bruto": "30.00",
        "valor_desconto": "0.00",
        "valor_liquido": "30.00",
        "custo_total": "10.00",
        "margem_bruta": "20.00",
        "status_pedido": "concluida",
        "canal": "loja_fisica",
        "loja_id": "LJ-BQ",
        "cidade": "Barbacena",
        "uf": "MG",
    }


def produto_bruto_minimo() -> dict:
    return {
        "produto_id": "P1",
        "produto": "Top treino",
        "categoria": "Tops",
        "preco_lista": "30.00",
        "custo_padrao": "10.00",
    }


def meta_bruta_minima() -> dict:
    return {
        "ano_mes": "2026-01",
        "canal": "loja_fisica",
        "unidade_id": "LJ-BQ",
        "meta_receita_liquida": "3000.00",
        "meta_pedidos": "100",
        "meta_ticket_medio": "30.00",
        "meta_margem_bruta_pct": "0.50",
        "meta_taxa_devolucao_pct": "0.04",
        "inicio_operacao": "2018-11-01",
    }


class NumerosDaStagingTest(unittest.TestCase):
    def test_decimal_finito_continua_aceito(self) -> None:
        self.assertEqual(staging.para_decimal("10.25", "valor_liquido"), Decimal("10.25"))

    def test_nan_e_infinito_nao_entram_como_decimal_valido(self) -> None:
        for valor in ["NaN", "Infinity", "-Infinity"]:
            with self.subTest(valor=valor):
                with self.assertRaisesRegex(ValueError, "precisa ser finito"):
                    staging.para_decimal(valor, "valor_liquido")

    def test_inteiro_nao_trunca_numero_fracionario(self) -> None:
        for valor in ["1.9", 1.9, Decimal("2.5")]:
            with self.subTest(valor=valor):
                with self.assertRaisesRegex(ValueError, "precisa ser inteiro"):
                    staging.para_inteiro(valor, "quantidade")

    def test_booleano_nao_vira_quantidade_um_ou_zero(self) -> None:
        for valor in [True, False]:
            with self.subTest(valor=valor):
                with self.assertRaisesRegex(ValueError, "precisa ser inteiro"):
                    staging.para_inteiro(valor, "quantidade")

    def test_decimal_nao_finito_reprova_linha_de_venda(self) -> None:
        venda = venda_bruta_minima()
        venda["valor_liquido"] = "Infinity"
        with self.assertRaisesRegex(ValueError, "valor_liquido precisa ser finito"):
            staging.padronizar_venda("vendas_barbacena", venda)

    def test_quantidade_fracionaria_reprova_linha_de_venda(self) -> None:
        venda = venda_bruta_minima()
        venda["quantidade"] = "1.9"
        with self.assertRaisesRegex(ValueError, "quantidade precisa ser inteiro"):
            staging.padronizar_venda("vendas_barbacena", venda)

    def test_numero_nao_finito_reprova_produto_e_meta(self) -> None:
        produto = produto_bruto_minimo()
        produto["custo_padrao"] = "NaN"
        with self.assertRaisesRegex(ValueError, "custo_padrao precisa ser finito"):
            staging.padronizar_produto(produto)

        meta = meta_bruta_minima()
        meta["meta_receita_liquida"] = "Infinity"
        with self.assertRaisesRegex(ValueError, "meta_receita_liquida precisa ser finito"):
            staging.padronizar_meta(meta)


if __name__ == "__main__":
    unittest.main()
