"""# Identidade dos itens vendidos na staging

## Limite desta etapa
A fonte ainda nao tem item_id. Estes testes protegem a regra provisoria antes
do DW: pedido pode ter varios produtos, mas pedido+produto repetido fica ambiguo.
"""
from copy import deepcopy
from decimal import Decimal
import unittest

from src import validate_staging as validacao
from tests.test_completude_staging import montar_carga_historica_minima_aprovavel


def declarar_novo_total_da_fonte(carga: dict, fonte: str, total: int) -> None:
    for status_carga in carga["status_cargas"]:
        if status_carga["fonte"] == fonte:
            status_carga["linhas_lidas"] = total
    for status_staging in carga["status_staging"]:
        if status_staging["fonte"] == fonte:
            status_staging.update(linhas_entrada=total, linhas_saida=total)


def incluir_produto_cadastrado(carga: dict, produto_id: str) -> None:
    carga["staging"]["stg_produtos"].append({"produto_id": produto_id, "custo_padrao": Decimal("10")})
    declarar_novo_total_da_fonte(carga, validacao.FONTE_PRODUTOS, len(carga["staging"]["stg_produtos"]))


def nome_do_check_identidade(relatorio: dict) -> dict:
    return next(check for check in relatorio["validacoes"] if check["nome"] == "identidade_itens_vendidos")


class IdentidadeItensVendidosTest(unittest.TestCase):
    def test_pedido_com_dois_produtos_pode_promover_dw(self) -> None:
        carga = montar_carga_historica_minima_aprovavel()
        fonte = validacao.FONTES_VENDAS[0]
        segundo_item = dict(carga["staging"]["stg_vendas"][0], produto_id="P2")
        carga["staging"]["stg_vendas"].append(segundo_item)
        declarar_novo_total_da_fonte(carga, fonte, 2)
        incluir_produto_cadastrado(carga, "P2")

        relatorio = validacao.validar_staging(carga)

        self.assertTrue(relatorio["pode_promover_dw"])
        identidade = nome_do_check_identidade(relatorio)
        self.assertEqual(identidade["metricas"]["pedidos_com_multiplos_produtos"], 1)

    def test_linha_duplicada_nao_vira_item_vendido_novo(self) -> None:
        carga = montar_carga_historica_minima_aprovavel()
        fonte = validacao.FONTES_VENDAS[0]
        carga["staging"]["stg_vendas"].append(deepcopy(carga["staging"]["stg_vendas"][0]))
        declarar_novo_total_da_fonte(carga, fonte, 2)

        relatorio = validacao.validar_staging(carga)

        self.assertFalse(relatorio["pode_promover_dw"])
        identidade = nome_do_check_identidade(relatorio)
        self.assertEqual(identidade["status"], "erro")
        self.assertEqual(identidade["metricas"]["itens_sem_chave_confiavel"], 1)

    def test_mesmo_pedido_e_produto_com_valor_diferente_continua_ambiguo(self) -> None:
        carga = montar_carga_historica_minima_aprovavel()
        fonte = validacao.FONTES_VENDAS[0]
        item_sem_numero_de_linha = dict(
            carga["staging"]["stg_vendas"][0],
            quantidade=2,
            valor_bruto=Decimal("60"),
            valor_liquido=Decimal("60"),
            custo_total=Decimal("20"),
            margem_bruta=Decimal("40"),
        )
        carga["staging"]["stg_vendas"].append(item_sem_numero_de_linha)
        declarar_novo_total_da_fonte(carga, fonte, 2)

        relatorio = validacao.validar_staging(carga)

        self.assertFalse(relatorio["pode_promover_dw"])
        identidade = nome_do_check_identidade(relatorio)
        self.assertEqual(identidade["metricas"]["itens_sem_chave_confiavel"], 1)

    def test_id_venda_com_cabecalho_divergente_bloqueia_pedido(self) -> None:
        carga = montar_carga_historica_minima_aprovavel()
        fonte = validacao.FONTES_VENDAS[0]
        segundo_item = dict(
            carga["staging"]["stg_vendas"][0],
            produto_id="P2",
            cliente_id="CLI-OUTRO",
        )
        carga["staging"]["stg_vendas"].append(segundo_item)
        declarar_novo_total_da_fonte(carga, fonte, 2)
        incluir_produto_cadastrado(carga, "P2")

        relatorio = validacao.validar_staging(carga)

        self.assertFalse(relatorio["pode_promover_dw"])
        identidade = nome_do_check_identidade(relatorio)
        self.assertEqual(identidade["metricas"]["pedidos_com_cabecalho_conflitante"], 1)

    def test_mensagem_de_identidade_nao_expoe_id_venda(self) -> None:
        carga = montar_carga_historica_minima_aprovavel()
        fonte = validacao.FONTES_VENDAS[0]
        carga["staging"]["stg_vendas"][0]["id_venda"] = "PEDIDO-PRIVADO"
        carga["staging"]["stg_vendas"].append(deepcopy(carga["staging"]["stg_vendas"][0]))
        declarar_novo_total_da_fonte(carga, fonte, 2)

        relatorio = validacao.validar_staging(carga)

        self.assertFalse(relatorio["pode_promover_dw"])
        self.assertNotIn("PEDIDO-PRIVADO", str(relatorio))


if __name__ == "__main__":
    unittest.main()
