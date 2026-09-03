from __future__ import annotations

# # Staging/Silver - primeira passada
#
# Este arquivo pega o resultado da extracao e transforma as vendas em uma
# estrutura comum. Ainda nao e DW, ainda nao e fato final.
#
# TODO: decidir depois se a staging sera gravada em CSV local ou direto no banco.
# FIXME: registros rejeitados ainda ficam apenas no status da fonte.
# NOTE: mantive tudo em Python puro para encaixar facil no Airflow depois.
# NOTE: nesta etapa entram vendas, produtos e metas. Cruzamento entre eles fica
# para a validacao da staging, para nao misturar responsabilidade demais aqui.

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    from extract_data_lake import carregar_data_lake
except ModuleNotFoundError:
    # FIXME: enquanto src nao virou pacote instalavel, aceitamos os dois jeitos:
    # rodar `python src/staging_data.py` e importar `src.staging_data`.
    from src.extract_data_lake import carregar_data_lake


STATUS_VALIDOS = {"concluida", "devolvida", "cancelada"}
CANAIS_VALIDOS = {"loja_fisica", "ecommerce"}
FONTES_VENDAS = [
    "vendas_barbacena",
    "vendas_conselheiro_lafaiete",
    "vendas_ecommerce",
]
FONTE_PRODUTOS = "produtos"
FONTE_METAS = "metas_mensais"


def agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def status_staging(
    fonte: str,
    status: str,
    linhas_entrada: int = 0,
    linhas_saida: int = 0,
    mensagem: str = "OK",
) -> dict:
    return {
        "fonte": fonte,
        "status": status,
        "linhas_entrada": linhas_entrada,
        "linhas_saida": linhas_saida,
        "mensagem": mensagem,
        "data_processamento": agora_iso(),
    }


def para_data(valor: str) -> str:
    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError as erro:
        raise ValueError(f"data_venda invalida: {valor}") from erro


def para_mes(valor: str) -> str:
    try:
        data_mes = date.fromisoformat(f"{valor}-01")
        return data_mes.strftime("%Y-%m")
    except ValueError as erro:
        raise ValueError(f"ano_mes invalido: {valor}") from erro


def para_hora(valor: str) -> str:
    try:
        return time.fromisoformat(valor).isoformat()
    except ValueError as erro:
        raise ValueError(f"hora_venda invalida: {valor}") from erro


def para_decimal(valor: Any, campo: str) -> Decimal:
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError) as erro:
        raise ValueError(f"{campo} invalido: {valor}") from erro


def para_inteiro(valor: Any, campo: str) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError) as erro:
        raise ValueError(f"{campo} invalido: {valor}") from erro


def validar_linha_venda(linha: dict) -> None:
    # TODO: puxar dominios de tabela de referencia quando o banco existir.
    if linha["status_pedido"] not in STATUS_VALIDOS:
        raise ValueError(f"status_pedido invalido: {linha['status_pedido']}")

    if linha["canal"] not in CANAIS_VALIDOS:
        raise ValueError(f"canal invalido: {linha['canal']}")

    if not linha.get("produto_id"):
        raise ValueError("produto_id vazio")

    if para_inteiro(linha["quantidade"], "quantidade") <= 0:
        raise ValueError("quantidade menor ou igual a zero")

    if para_decimal(linha["valor_liquido"], "valor_liquido") < 0:
        raise ValueError("valor_liquido negativo")


def validar_linha_produto(linha: dict) -> None:
    # NOTE: produto ainda e cadastro simples; dimensao final vem depois.
    if not linha.get("produto_id"):
        raise ValueError("produto_id vazio")

    if not linha.get("produto"):
        raise ValueError("produto vazio")

    if not linha.get("categoria"):
        raise ValueError("categoria vazia")

    if para_decimal(linha["preco_lista"], "preco_lista") < 0:
        raise ValueError("preco_lista negativo")

    if para_decimal(linha["custo_padrao"], "custo_padrao") < 0:
        raise ValueError("custo_padrao negativo")


def validar_linha_meta(linha: dict) -> None:
    # FIXME: metas ainda nao validam se unidade_id existe em dim_unidade.
    para_mes(linha["ano_mes"])

    if linha["canal"] not in CANAIS_VALIDOS:
        raise ValueError(f"canal invalido: {linha['canal']}")

    if not linha.get("unidade_id"):
        raise ValueError("unidade_id vazio")

    if para_decimal(linha["meta_receita_liquida"], "meta_receita_liquida") < 0:
        raise ValueError("meta_receita_liquida negativa")

    if para_inteiro(linha["meta_pedidos"], "meta_pedidos") <= 0:
        raise ValueError("meta_pedidos menor ou igual a zero")

    if para_decimal(linha["meta_ticket_medio"], "meta_ticket_medio") < 0:
        raise ValueError("meta_ticket_medio negativo")


def unidade_id(linha: dict) -> str:
    if linha["canal"] == "ecommerce":
        # NOTE: ecommerce nao tem loja fisica; EC-BR representa o canal online.
        return "EC-BR"

    return linha["loja_id"]


def cidade_venda(linha: dict) -> str | None:
    if linha["canal"] == "ecommerce":
        return linha.get("cidade_entrega")

    return linha.get("cidade")


def uf_venda(linha: dict) -> str | None:
    if linha["canal"] == "ecommerce":
        return linha.get("uf_entrega")

    return linha.get("uf")


def padronizar_venda(fonte: str, linha: dict) -> dict:
    validar_linha_venda(linha)

    # FIXME: venda_item_id ainda nao entra aqui. Ela deve nascer na camada DW,
    # quando a gente fechar a chave tecnica da fato_vendas.
    return {
        "fonte": fonte,
        "id_venda": linha["id_venda"],
        "data_venda": para_data(linha["data_venda"]),
        "hora_venda": para_hora(linha["hora_venda"]),
        "cliente_id": linha["cliente_id"],
        "produto_id": linha["produto_id"],
        "quantidade": para_inteiro(linha["quantidade"], "quantidade"),
        "valor_bruto": para_decimal(linha["valor_bruto"], "valor_bruto"),
        "valor_desconto": para_decimal(linha["valor_desconto"], "valor_desconto"),
        "valor_liquido": para_decimal(linha["valor_liquido"], "valor_liquido"),
        "custo_total": para_decimal(linha["custo_total"], "custo_total"),
        "margem_bruta": para_decimal(linha["margem_bruta"], "margem_bruta"),
        "status_pedido": linha["status_pedido"],
        "canal": linha["canal"],
        "unidade_id": unidade_id(linha),
        "cidade": cidade_venda(linha),
        "uf": uf_venda(linha),
        "campanha": linha.get("campanha"),
        "forma_pagamento": linha.get("forma_pagamento"),
        "pedido_online_id": linha.get("pedido_online_id"),
        "canal_origem": linha.get("canal_origem"),
        "cupom": linha.get("cupom") or None,
        "data_processamento": agora_iso(),
    }


def padronizar_produto(linha: dict) -> dict:
    validar_linha_produto(linha)

    # TODO: validar categorias contra uma tabela de dominio quando ela existir.
    return {
        "produto_id": linha["produto_id"],
        "produto": linha["produto"],
        "genero_produto": linha.get("genero_produto"),
        "categoria": linha["categoria"],
        "preco_lista": para_decimal(linha["preco_lista"], "preco_lista"),
        "custo_padrao": para_decimal(linha["custo_padrao"], "custo_padrao"),
        "data_processamento": agora_iso(),
    }


def padronizar_meta(linha: dict) -> dict:
    validar_linha_meta(linha)

    # NOTE: metas ficam mensais. Rateio diario para meta esperada entra no BI/DW.
    return {
        "ano_mes": para_mes(linha["ano_mes"]),
        "canal": linha["canal"],
        "unidade_id": linha["unidade_id"],
        "cidade": linha.get("cidade"),
        "uf": linha.get("uf"),
        "meta_receita_liquida": para_decimal(linha["meta_receita_liquida"], "meta_receita_liquida"),
        "meta_pedidos": para_inteiro(linha["meta_pedidos"], "meta_pedidos"),
        "meta_ticket_medio": para_decimal(linha["meta_ticket_medio"], "meta_ticket_medio"),
        "meta_margem_bruta_pct": para_decimal(linha["meta_margem_bruta_pct"], "meta_margem_bruta_pct"),
        "meta_taxa_devolucao_pct": para_decimal(
            linha["meta_taxa_devolucao_pct"],
            "meta_taxa_devolucao_pct",
        ),
        "inicio_operacao": para_data(linha["inicio_operacao"]),
        "observacao": linha.get("observacao"),
        "data_processamento": agora_iso(),
    }


def gerar_staging_vendas(dados_extraidos: dict) -> tuple[list[dict], list[dict]]:
    stg_vendas = []
    status = []

    for fonte in FONTES_VENDAS:
        linhas = dados_extraidos.get("dados", {}).get(fonte)
        if linhas is None:
            # NOTE: fonte ausente aqui normalmente significa falha na extracao.
            status.append(status_staging(fonte, "ignorado", mensagem="Fonte nao carregada na extracao"))
            continue

        try:
            vendas_fonte = [padronizar_venda(fonte, linha) for linha in linhas]
            stg_vendas.extend(vendas_fonte)
            status.append(
                status_staging(
                    fonte,
                    "sucesso",
                    linhas_entrada=len(linhas),
                    linhas_saida=len(vendas_fonte),
                )
            )
        except Exception as erro:
            # TODO: por enquanto, se uma linha quebrar, a fonte inteira falha.
            # Depois melhorar para separar linhas rejeitadas e linhas validas.
            status.append(status_staging(fonte, "falha", linhas_entrada=len(linhas), mensagem=str(erro)))

    return stg_vendas, status


def gerar_staging_produtos(dados_extraidos: dict) -> tuple[list[dict], list[dict]]:
    linhas = dados_extraidos.get("dados", {}).get(FONTE_PRODUTOS)
    if linhas is None:
        return [], [status_staging(FONTE_PRODUTOS, "ignorado", mensagem="Fonte nao carregada na extracao")]

    try:
        produtos = [padronizar_produto(linha) for linha in linhas]
        return produtos, [
            status_staging(
                FONTE_PRODUTOS,
                "sucesso",
                linhas_entrada=len(linhas),
                linhas_saida=len(produtos),
            )
        ]
    except Exception as erro:
        # TODO: rejeicao linha a linha vai ajudar quando o cadastro crescer.
        return [], [status_staging(FONTE_PRODUTOS, "falha", linhas_entrada=len(linhas), mensagem=str(erro))]


def gerar_staging_metas(dados_extraidos: dict) -> tuple[list[dict], list[dict]]:
    linhas = dados_extraidos.get("dados", {}).get(FONTE_METAS)
    if linhas is None:
        return [], [status_staging(FONTE_METAS, "ignorado", mensagem="Fonte nao carregada na extracao")]

    try:
        metas = [padronizar_meta(linha) for linha in linhas]
        return metas, [
            status_staging(
                FONTE_METAS,
                "sucesso",
                linhas_entrada=len(linhas),
                linhas_saida=len(metas),
            )
        ]
    except Exception as erro:
        # FIXME: metas podem ter erro em uma unidade/mes e ainda assim outras linhas boas.
        return [], [status_staging(FONTE_METAS, "falha", linhas_entrada=len(linhas), mensagem=str(erro))]


def gerar_staging() -> dict:
    resultado_extracao = carregar_data_lake()
    stg_vendas, status_vendas = gerar_staging_vendas(resultado_extracao)
    stg_produtos, status_produtos = gerar_staging_produtos(resultado_extracao)
    stg_metas, status_metas = gerar_staging_metas(resultado_extracao)

    return {
        "staging": {
            "stg_vendas": stg_vendas,
            "stg_produtos": stg_produtos,
            "stg_metas": stg_metas,
        },
        "status_cargas": resultado_extracao["status_cargas"],
        "status_staging": status_vendas + status_produtos + status_metas,
    }


def imprimir_resumo(resultado: dict) -> None:
    print("\nResumo da staging")
    print("-" * 32)
    print(f"stg_vendas: {len(resultado['staging']['stg_vendas'])} linhas")
    print(f"stg_produtos: {len(resultado['staging']['stg_produtos'])} linhas")
    print(f"stg_metas: {len(resultado['staging']['stg_metas'])} linhas")

    for item in resultado["status_staging"]:
        print(
            f"{item['fonte']}: {item['status']} | "
            f"{item['linhas_entrada']} entrada | {item['linhas_saida']} saida | {item['mensagem']}"
        )


if __name__ == "__main__":
    resultado_staging = gerar_staging()
    imprimir_resumo(resultado_staging)
