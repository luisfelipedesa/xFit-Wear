"""# Mensagens seguras do pipeline local

## Limite desta etapa
Garante que erros operacionais nao ecoem valores brutos da fonte. Ainda nao
existe tabela de rejeicoes com detalhe tecnico protegido.
"""
from copy import deepcopy
import unittest

from src import extract_data_lake as extracao
from src import staging_data as staging
from src import validate_staging as validacao
from tests.test_completude_staging import montar_carga_historica_minima_aprovavel


def primeira_mensagem_status(status: list[dict]) -> str:
    return status[0]["mensagem"]


class MensagensSegurasTest(unittest.TestCase):
    def test_extracao_nao_repassa_texto_bruto_da_excecao(self) -> None:
        mensagem = extracao.mensagem_segura(ValueError("CAMINHO-OU-VALOR-PRIVADO"))

        self.assertIn("Falha ao carregar fonte", mensagem)
        self.assertNotIn("CAMINHO-OU-VALOR-PRIVADO", mensagem)

    def test_status_de_venda_invalida_nao_expoe_valor_da_fonte(self) -> None:
        carga = montar_carga_historica_minima_aprovavel()
        venda = deepcopy(carga["staging"]["stg_vendas"][0])
        venda["status_pedido"] = "STATUS-PRIVADO"

        _vendas, status = staging.gerar_staging_vendas({"dados": {"vendas_barbacena": [venda]}})

        self.assertIn("falha de padronizacao", primeira_mensagem_status(status))
        self.assertNotIn("STATUS-PRIVADO", primeira_mensagem_status(status))

    def test_status_de_produto_invalido_nao_expoe_valor_da_fonte(self) -> None:
        produto = {
            "produto_id": "P1",
            "produto": "Produto Teste",
            "categoria": "Categoria Teste",
            "preco_lista": "NaN",
            "custo_padrao": "10.00",
        }

        _produtos, status = staging.gerar_staging_produtos({"dados": {"produtos": [produto]}})

        self.assertIn("falha de padronizacao", primeira_mensagem_status(status))
        self.assertNotIn("NaN", primeira_mensagem_status(status))

    def test_status_de_meta_invalida_nao_expoe_valor_da_fonte(self) -> None:
        meta = {
            "ano_mes": "MES-PRIVADO",
            "canal": "loja_fisica",
            "unidade_id": "LJ-BQ",
            "meta_receita_liquida": "300.00",
            "meta_pedidos": "10",
            "meta_ticket_medio": "30.00",
            "meta_margem_bruta_pct": "0.50",
            "meta_taxa_devolucao_pct": "0.04",
            "inicio_operacao": "2018-11-01",
        }

        _metas, status = staging.gerar_staging_metas({"dados": {"metas_mensais": [meta]}})

        self.assertIn("falha de padronizacao", primeira_mensagem_status(status))
        self.assertNotIn("MES-PRIVADO", primeira_mensagem_status(status))

    def test_validacao_de_produto_sem_cadastro_nao_lista_produto_privado(self) -> None:
        carga = montar_carga_historica_minima_aprovavel()
        carga["staging"]["stg_vendas"][0]["produto_id"] = "PRODUTO-PRIVADO"

        relatorio = validacao.validar_staging(carga)

        self.assertFalse(relatorio["pode_promover_dw"])
        self.assertNotIn("PRODUTO-PRIVADO", str(relatorio))

    def test_validacao_de_venda_futura_nao_lista_id_venda(self) -> None:
        carga = montar_carga_historica_minima_aprovavel()
        carga["staging"]["stg_vendas"][0]["id_venda"] = "PEDIDO-PRIVADO"
        carga["staging"]["stg_vendas"][0]["data_venda"] = "2027-01-01"

        relatorio = validacao.validar_staging(carga)

        self.assertFalse(relatorio["pode_promover_dw"])
        self.assertNotIn("PEDIDO-PRIVADO", str(relatorio))


if __name__ == "__main__":
    unittest.main()
