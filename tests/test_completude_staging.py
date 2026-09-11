"""# Completude da carga historica

## Limite desta etapa
Confere fontes, status e volumes em memoria. A identidade do item vendido fica
em test_identidade_vendas_staging.py, para nao misturar duas regras no mesmo teste.
"""
from copy import deepcopy
from decimal import Decimal
import unittest

from src import validate_staging as validacao


def montar_carga_historica_minima_aprovavel() -> dict:
    item_vendido_base = {
        "id_venda": "V1",
        "data_venda": "2020-01-10",
        "hora_venda": "10:00:00",
        "cliente_id": "CLI-00001",
        "produto_id": "P1",
        "quantidade": 1,
        "valor_bruto": Decimal("30"),
        "valor_desconto": Decimal("0"),
        "valor_liquido": Decimal("30"),
        "custo_total": Decimal("10"),
        "margem_bruta": Decimal("20"),
        "status_pedido": "concluida",
    }
    vendas = []
    metas = []
    for indice, fonte in enumerate(validacao.FONTES_VENDAS):
        unidade = f"UNIDADE-{indice}"
        canal = "ecommerce" if fonte == "vendas_ecommerce" else "loja_fisica"
        vendas.append(dict(item_vendido_base, fonte=fonte, unidade_id=unidade, canal=canal, id_venda=f"V{indice}"))
        metas.append({
            "ano_mes": "2020-01",
            "unidade_id": unidade,
            "canal": canal,
            "meta_receita_liquida": Decimal("300"),
            "meta_pedidos": 10,
            "meta_ticket_medio": Decimal("30"),
            "meta_margem_bruta_pct": Decimal("60"),
            "meta_taxa_devolucao_pct": Decimal("2"),
        })
    produtos = [{"produto_id": "P1", "custo_padrao": Decimal("10")}]
    volumes = dict.fromkeys(validacao.FONTES_VENDAS, 1)
    volumes.update({validacao.FONTE_PRODUTOS: len(produtos), validacao.FONTE_METAS: len(metas)})
    return {
        "staging": {"stg_vendas": vendas, "stg_produtos": produtos, "stg_metas": metas},
        "status_cargas": [
            {"fonte": fonte, "status": "sucesso", "linhas_lidas": total}
            for fonte, total in volumes.items()
        ],
        "status_staging": [
            {"fonte": fonte, "status": "sucesso", "linhas_entrada": total, "linhas_saida": total}
            for fonte, total in volumes.items()
        ],
    }


class CompletudeStagingTest(unittest.TestCase):
    def confirmar_que_staging_nao_pode_promover_dw(self, carga: dict) -> None:
        relatorio = validacao.validar_staging(carga)
        self.assertFalse(relatorio["pode_promover_dw"])
        self.assertEqual(relatorio["status_geral"], "reprovado")
        self.assertGreater(relatorio["erros"], 0)
        self.assertEqual(relatorio["validacoes"][0]["nome"], "completude_staging")

    def test_carga_completa_passa_sem_alterar_entrada(self) -> None:
        carga = montar_carga_historica_minima_aprovavel()
        antes = deepcopy(carga)
        relatorio = validacao.validar_staging(carga)
        self.assertTrue(relatorio["pode_promover_dw"])
        self.assertEqual(relatorio["linhas"], {"stg_vendas": 3, "stg_produtos": 1, "stg_metas": 3})
        self.assertEqual(carga, antes)

    def test_tabela_obrigatoria_sem_linhas_reprova_carga_historica(self) -> None:
        self.confirmar_que_staging_nao_pode_promover_dw({})
        for tabela_staging in ["stg_vendas", "stg_produtos", "stg_metas"]:
            for linhas_staging in [None, [], {}, [None]]:
                with self.subTest(tabela_staging=tabela_staging, linhas_staging=linhas_staging):
                    carga = montar_carga_historica_minima_aprovavel()
                    carga["staging"][tabela_staging] = linhas_staging
                    self.confirmar_que_staging_nao_pode_promover_dw(carga)
            carga = montar_carga_historica_minima_aprovavel()
            del carga["staging"][tabela_staging]
            self.confirmar_que_staging_nao_pode_promover_dw(carga)

    def test_status_de_cada_fonte_precisa_aparecer_uma_vez(self) -> None:
        for lista_status in ["status_cargas", "status_staging"]:
            for indice_fonte in range(5):
                for duplicar in [False, True]:
                    with self.subTest(lista_status=lista_status, indice_fonte=indice_fonte, duplicar=duplicar):
                        carga = montar_carga_historica_minima_aprovavel()
                        if duplicar:
                            carga[lista_status].append(deepcopy(carga[lista_status][indice_fonte]))
                        else:
                            carga[lista_status].pop(indice_fonte)
                        self.confirmar_que_staging_nao_pode_promover_dw(carga)
            for status_invalidos in [None, {}, [], [None]]:
                carga = montar_carga_historica_minima_aprovavel()
                carga[lista_status] = status_invalidos
                self.confirmar_que_staging_nao_pode_promover_dw(carga)

    def test_status_sem_sucesso_bloqueia(self) -> None:
        for lista_status in ["status_cargas", "status_staging"]:
            for status in [None, "falha", "ignorado", "desconhecido"]:
                carga = montar_carga_historica_minima_aprovavel()
                carga[lista_status][0]["status"] = status
                self.confirmar_que_staging_nao_pode_promover_dw(carga)

    def test_volume_declarado_precisa_bater_com_linhas_reais(self) -> None:
        for lista_status, campo_volume in [("status_cargas", "linhas_lidas"),
                                           ("status_staging", "linhas_entrada"),
                                           ("status_staging", "linhas_saida")]:
            for indice_fonte in range(5):
                for volume_declarado in [None, 0, -1, True, "1", 1.0, 100]:
                    with self.subTest(
                        lista_status=lista_status,
                        campo_volume=campo_volume,
                        indice_fonte=indice_fonte,
                        volume_declarado=volume_declarado,
                    ):
                        carga = montar_carga_historica_minima_aprovavel()
                        carga[lista_status][indice_fonte][campo_volume] = volume_declarado
                        self.confirmar_que_staging_nao_pode_promover_dw(carga)

    def test_excesso_em_uma_loja_nao_compensa_falta_em_outra(self) -> None:
        carga = montar_carga_historica_minima_aprovavel()
        carga["staging"]["stg_vendas"][0]["fonte"] = validacao.FONTES_VENDAS[1]
        self.confirmar_que_staging_nao_pode_promover_dw(carga)

    def test_status_sucesso_nao_esconde_linha_perdida_na_tabela(self) -> None:
        for tabela_staging in ["stg_vendas", "stg_produtos", "stg_metas"]:
            carga = montar_carga_historica_minima_aprovavel()
            carga["staging"][tabela_staging].pop()
            self.confirmar_que_staging_nao_pode_promover_dw(carga)

    def test_fonte_desconhecida_bloqueia_sem_ecoar_valor(self) -> None:
        for local_da_fonte in ["status_cargas", "status_staging", "stg_vendas"]:
            carga = montar_carga_historica_minima_aprovavel()
            linhas = carga[local_da_fonte] if local_da_fonte.startswith("status") else carga["staging"][local_da_fonte]
            linhas[0]["fonte"] = "MARCADOR-PRIVADO"
            self.confirmar_que_staging_nao_pode_promover_dw(carga)
            self.assertNotIn("MARCADOR-PRIVADO", str(validacao.validar_staging(carga)))

    def test_pedido_com_dois_itens_nao_e_bloqueado_so_pelo_id(self) -> None:
        # NOTE: completude conta linhas. Nao transforma id_venda em chave do item.
        carga = montar_carga_historica_minima_aprovavel()
        segunda_linha = dict(carga["staging"]["stg_vendas"][0], produto_id="P2")
        carga["staging"]["stg_vendas"].append(segunda_linha)
        carga["staging"]["stg_produtos"].append({"produto_id": "P2", "custo_padrao": Decimal("10")})
        for status_carga in carga["status_cargas"]:
            if status_carga["fonte"] in [validacao.FONTES_VENDAS[0], validacao.FONTE_PRODUTOS]:
                status_carga["linhas_lidas"] = 2
        for status_staging in carga["status_staging"]:
            if status_staging["fonte"] in [validacao.FONTES_VENDAS[0], validacao.FONTE_PRODUTOS]:
                status_staging.update(linhas_entrada=2, linhas_saida=2)
        self.assertTrue(validacao.validar_staging(carga)["pode_promover_dw"])


if __name__ == "__main__":
    unittest.main()
