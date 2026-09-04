from __future__ import annotations

# Validacao de qualidade da staging antes de promover para DW.
#
# Esta etapa ainda nao cria dim/fato. A ideia e barrar erro silencioso:
# produto vendido sem cadastro, unidade sem meta, valor incoerente etc.
#
# TODO: quando existir banco, gravar este resultado em etl.validacoes_staging.
# FIXME: por enquanto os exemplos sao pequenos e assertivos; teste formal fica
# para quando a camada DW nascer.
# NOTE: mensagens deste relatorio nao mostram caminhos locais nem conteudo do .env.

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterable
import sys

try:
    from staging_data import gerar_staging
except ModuleNotFoundError:
    # FIXME: manter compatibilidade enquanto src ainda nao e pacote instalavel.
    from src.staging_data import gerar_staging


LIMITE_EXEMPLOS = 5
TOLERANCIA_CENTAVOS = Decimal("0.02")
MATERIALIDADE_ABSOLUTA_GRUPO = Decimal("1.00")
MATERIALIDADE_RELATIVA_RECEITA = Decimal("0.0001")


def ano_mes(data_iso: str) -> str:
    return data_iso[:7]


def novo_check(nome: str) -> dict:
    return {
        "nome": nome,
        "status": "ok",
        "erros": [],
        "alertas": [],
        "metricas": {},
    }


def adicionar_erro(check: dict, mensagem: str) -> None:
    check["status"] = "erro"
    check["erros"].append(mensagem)


def adicionar_alerta(check: dict, mensagem: str) -> None:
    if check["status"] == "ok":
        check["status"] = "alerta"
    check["alertas"].append(mensagem)


def exemplo(valores: Iterable) -> list:
    return sorted(set(valores))[:LIMITE_EXEMPLOS]


def validar_status_pipeline(resultado: dict) -> dict:
    check = novo_check("status_pipeline")

    falhas_carga = [item for item in resultado["status_cargas"] if item["status"] != "sucesso"]
    falhas_staging = [item for item in resultado["status_staging"] if item["status"] != "sucesso"]

    check["metricas"] = {
        "fontes_com_falha_carga": len(falhas_carga),
        "fontes_com_falha_staging": len(falhas_staging),
    }

    for item in falhas_carga:
        adicionar_erro(check, f"carga {item['fonte']} ficou como {item['status']}: {item['mensagem']}")

    for item in falhas_staging:
        adicionar_erro(check, f"staging {item['fonte']} ficou como {item['status']}: {item['mensagem']}")

    return check


def validar_produtos(vendas: list[dict], produtos: list[dict]) -> dict:
    check = novo_check("produtos")
    produto_ids = [produto["produto_id"] for produto in produtos]
    ids_cadastrados = set(produto_ids)
    ids_vendidos = {venda["produto_id"] for venda in vendas}
    duplicados = [produto_id for produto_id, total in Counter(produto_ids).items() if total > 1]
    sem_cadastro = ids_vendidos - ids_cadastrados

    check["metricas"] = {
        "produtos_cadastrados": len(ids_cadastrados),
        "produtos_vendidos": len(ids_vendidos),
        "produtos_sem_cadastro": len(sem_cadastro),
        "produtos_duplicados": len(duplicados),
    }

    if duplicados:
        adicionar_erro(check, f"produto_id duplicado no cadastro: {exemplo(duplicados)}")

    if sem_cadastro:
        adicionar_erro(check, f"produto_id vendido sem cadastro: {exemplo(sem_cadastro)}")

    return check


def validar_unidades_e_metas(vendas: list[dict], metas: list[dict]) -> dict:
    check = novo_check("unidades_metas")
    unidades_vendas = {venda["unidade_id"] for venda in vendas}
    unidades_metas = {meta["unidade_id"] for meta in metas}
    unidades_sem_meta = unidades_vendas - unidades_metas
    metas_sem_venda = unidades_metas - unidades_vendas

    canal_por_unidade_venda = defaultdict(set)
    for venda in vendas:
        canal_por_unidade_venda[venda["unidade_id"]].add(venda["canal"])

    canal_por_unidade_meta = defaultdict(set)
    for meta in metas:
        canal_por_unidade_meta[meta["unidade_id"]].add(meta["canal"])

    canais_conflitantes = [
        unidade
        for unidade in unidades_vendas & unidades_metas
        if canal_por_unidade_venda[unidade] != canal_por_unidade_meta[unidade]
    ]

    check["metricas"] = {
        "unidades_com_venda": len(unidades_vendas),
        "unidades_com_meta": len(unidades_metas),
        "unidades_sem_meta": len(unidades_sem_meta),
        "metas_sem_venda": len(metas_sem_venda),
        "unidades_com_canal_conflitante": len(canais_conflitantes),
    }

    if unidades_sem_meta:
        adicionar_erro(check, f"unidade_id com venda e sem meta: {exemplo(unidades_sem_meta)}")

    if canais_conflitantes:
        adicionar_erro(check, f"unidade_id com canal divergente entre venda/meta: {exemplo(canais_conflitantes)}")

    if metas_sem_venda:
        adicionar_alerta(check, f"unidade_id com meta mas sem venda no periodo: {exemplo(metas_sem_venda)}")

    return check


def validar_cobertura_mensal(vendas: list[dict], metas: list[dict]) -> dict:
    check = novo_check("cobertura_mensal")
    meses_vendas = {(venda["unidade_id"], ano_mes(venda["data_venda"])) for venda in vendas}
    meses_metas = {(meta["unidade_id"], meta["ano_mes"]) for meta in metas}
    vendas_sem_meta = meses_vendas - meses_metas

    check["metricas"] = {
        "pares_unidade_mes_vendas": len(meses_vendas),
        "pares_unidade_mes_metas": len(meses_metas),
        "pares_venda_sem_meta": len(vendas_sem_meta),
    }

    if vendas_sem_meta:
        adicionar_erro(check, f"unidade/mes com venda e sem meta: {exemplo(vendas_sem_meta)}")

    return check


def validar_valores(vendas: list[dict], produtos: list[dict], metas: list[dict]) -> dict:
    check = novo_check("valores")
    produtos_por_id = {produto["produto_id"]: produto for produto in produtos}
    vendas_negativas = []
    margens_inconsistentes = []
    canceladas_com_valor = []
    metas_invalidas = []

    for venda in vendas:
        if (
            venda["quantidade"] <= 0
            or venda["valor_bruto"] < 0
            or venda["valor_desconto"] < 0
            or venda["valor_liquido"] < 0
            or venda["custo_total"] < 0
        ):
            vendas_negativas.append(venda["id_venda"])

        margem_esperada = venda["valor_liquido"] - venda["custo_total"]
        diferenca_margem = abs(venda["margem_bruta"] - margem_esperada)
        if venda["status_pedido"] == "cancelada":
            if venda["valor_liquido"] != Decimal("0") or venda["margem_bruta"] != Decimal("0"):
                canceladas_com_valor.append(venda["id_venda"])
        elif diferenca_margem > TOLERANCIA_CENTAVOS:
            # NOTE: aceitamos diferenca pequena porque a fonte arredonda campos
            # monetarios ja calculados; acima disso vira erro analitico.
            margens_inconsistentes.append(venda["id_venda"])

        produto = produtos_por_id.get(venda["produto_id"])
        if produto and venda["status_pedido"] != "cancelada":
            custo_minimo = produto["custo_padrao"] * venda["quantidade"]
            # NOTE: devolucao pode ter margem ruim, mas custo_total abaixo do
            # custo padrao indicaria erro de simulacao ou regra nao documentada.
            if venda["custo_total"] < custo_minimo:
                margens_inconsistentes.append(venda["id_venda"])

    for meta in metas:
        if (
            meta["meta_receita_liquida"] < 0
            or meta["meta_pedidos"] <= 0
            or meta["meta_ticket_medio"] < 0
            or meta["meta_margem_bruta_pct"] < 0
            or meta["meta_taxa_devolucao_pct"] < 0
        ):
            metas_invalidas.append((meta["unidade_id"], meta["ano_mes"]))

    check["metricas"] = {
        "vendas_com_valor_invalido": len(set(vendas_negativas)),
        "vendas_com_margem_inconsistente": len(set(margens_inconsistentes)),
        "canceladas_com_receita_liquida": len(set(canceladas_com_valor)),
        "metas_com_valor_invalido": len(set(metas_invalidas)),
    }

    if vendas_negativas:
        adicionar_erro(check, f"vendas com quantidade/valor invalido: {exemplo(vendas_negativas)}")

    if margens_inconsistentes:
        adicionar_erro(check, f"vendas com margem/custo inconsistente: {exemplo(margens_inconsistentes)}")

    if canceladas_com_valor:
        adicionar_erro(check, f"vendas canceladas com receita liquida: {exemplo(canceladas_com_valor)}")

    if metas_invalidas:
        adicionar_erro(check, f"metas com valor invalido: {exemplo(metas_invalidas)}")

    return check


def limite_materialidade(receita_liquida: Decimal) -> Decimal:
    return max(MATERIALIDADE_ABSOLUTA_GRUPO, receita_liquida.copy_abs() * MATERIALIDADE_RELATIVA_RECEITA)


def validar_arredondamento_agregado(vendas: list[dict]) -> dict:
    check = novo_check("arredondamento_agregado")
    grupos = defaultdict(lambda: {"diferenca_liquida": Decimal("0"), "diferenca_absoluta": Decimal("0"), "receita": Decimal("0"), "linhas": 0})
    total = {"diferenca_liquida": Decimal("0"), "diferenca_absoluta": Decimal("0"), "receita": Decimal("0"), "linhas": 0}

    for venda in vendas:
        if venda["status_pedido"] == "cancelada":
            continue

        chave = (venda["fonte"], venda["canal"], venda["unidade_id"], ano_mes(venda["data_venda"]))
        diferenca = venda["margem_bruta"] - (venda["valor_liquido"] - venda["custo_total"])

        grupos[chave]["diferenca_liquida"] += diferenca
        grupos[chave]["diferenca_absoluta"] += abs(diferenca)
        grupos[chave]["receita"] += venda["valor_liquido"]
        grupos[chave]["linhas"] += 1

        total["diferenca_liquida"] += diferenca
        total["diferenca_absoluta"] += abs(diferenca)
        total["receita"] += venda["valor_liquido"]
        total["linhas"] += 1

    grupos_acima = []
    for chave, metricas in grupos.items():
        limite = limite_materialidade(metricas["receita"])
        if metricas["diferenca_absoluta"] > limite:
            grupos_acima.append((chave, metricas["diferenca_absoluta"], limite))

    limite_global = limite_materialidade(total["receita"])
    check["metricas"] = {
        "linhas_avaliadas": total["linhas"],
        "diferenca_liquida_global": total["diferenca_liquida"],
        "diferenca_absoluta_global": total["diferenca_absoluta"],
        "receita_liquida_avaliada": total["receita"],
        "limite_global": limite_global,
        "grupos_avaliados": len(grupos),
        "grupos_acima_da_materialidade": len(grupos_acima),
    }

    if total["diferenca_absoluta"] > limite_global:
        adicionar_erro(
            check,
            f"diferenca absoluta global de arredondamento acima da materialidade: "
            f"{total['diferenca_absoluta']} > {limite_global}",
        )

    if grupos_acima:
        # NOTE: este controle evita que centavos aceitos por linha virem desvio
        # material por fonte/canal/unidade/mes quando o volume crescer.
        adicionar_erro(check, f"grupos acima da materialidade: {exemplo(grupos_acima)}")

    return check


def validar_status_e_datas(vendas: list[dict], metas: list[dict]) -> dict:
    check = novo_check("status_datas")
    status_validos = {"concluida", "devolvida", "cancelada"}
    canais_validos = {"loja_fisica", "ecommerce"}
    status_invalidos = {venda["status_pedido"] for venda in vendas if venda["status_pedido"] not in status_validos}
    canais_invalidos = {venda["canal"] for venda in vendas if venda["canal"] not in canais_validos}
    vendas_futuras = [venda["id_venda"] for venda in vendas if date.fromisoformat(venda["data_venda"]) > date.today()]
    metas_duplicadas = [
        chave
        for chave, total in Counter((meta["unidade_id"], meta["ano_mes"]) for meta in metas).items()
        if total > 1
    ]

    datas_vendas = [venda["data_venda"] for venda in vendas]
    meses_metas = [meta["ano_mes"] for meta in metas]
    check["metricas"] = {
        "data_minima_venda": min(datas_vendas) if datas_vendas else None,
        "data_maxima_venda": max(datas_vendas) if datas_vendas else None,
        "mes_minimo_meta": min(meses_metas) if meses_metas else None,
        "mes_maximo_meta": max(meses_metas) if meses_metas else None,
        "vendas_futuras": len(vendas_futuras),
        "metas_duplicadas": len(metas_duplicadas),
    }

    if status_invalidos:
        adicionar_erro(check, f"status_pedido fora do dominio: {exemplo(status_invalidos)}")

    if canais_invalidos:
        adicionar_erro(check, f"canal fora do dominio: {exemplo(canais_invalidos)}")

    if vendas_futuras:
        adicionar_erro(check, f"vendas com data futura: {exemplo(vendas_futuras)}")

    if metas_duplicadas:
        adicionar_erro(check, f"metas duplicadas por unidade/mes: {exemplo(metas_duplicadas)}")

    return check


def validar_staging(resultado: dict | None = None) -> dict:
    if resultado is None:
        resultado = gerar_staging()

    staging = resultado["staging"]
    vendas = staging["stg_vendas"]
    produtos = staging["stg_produtos"]
    metas = staging["stg_metas"]

    validacoes = [
        validar_status_pipeline(resultado),
        validar_produtos(vendas, produtos),
        validar_unidades_e_metas(vendas, metas),
        validar_cobertura_mensal(vendas, metas),
        validar_valores(vendas, produtos, metas),
        validar_arredondamento_agregado(vendas),
        validar_status_e_datas(vendas, metas),
    ]
    erros = sum(len(check["erros"]) for check in validacoes)
    alertas = sum(len(check["alertas"]) for check in validacoes)

    return {
        "status_geral": "aprovado" if erros == 0 else "reprovado",
        "pode_promover_dw": erros == 0,
        "erros": erros,
        "alertas": alertas,
        "linhas": {
            "stg_vendas": len(vendas),
            "stg_produtos": len(produtos),
            "stg_metas": len(metas),
        },
        "validacoes": validacoes,
    }


def imprimir_relatorio(relatorio: dict) -> None:
    print("\nValidacao de qualidade da staging")
    print("-" * 40)
    print(f"status_geral: {relatorio['status_geral']}")
    print(f"pode_promover_dw: {relatorio['pode_promover_dw']}")
    print(f"erros: {relatorio['erros']} | alertas: {relatorio['alertas']}")
    print(
        "linhas: "
        f"stg_vendas={relatorio['linhas']['stg_vendas']}, "
        f"stg_produtos={relatorio['linhas']['stg_produtos']}, "
        f"stg_metas={relatorio['linhas']['stg_metas']}"
    )

    for check in relatorio["validacoes"]:
        print(f"\n[{check['status']}] {check['nome']}")
        for chave, valor in check["metricas"].items():
            print(f"  {chave}: {valor}")
        for mensagem in check["erros"]:
            print(f"  ERRO: {mensagem}")
        for mensagem in check["alertas"]:
            print(f"  ALERTA: {mensagem}")

    if relatorio["pode_promover_dw"]:
        print("\nParecer: OK para promover staging para DW.")
    else:
        print("\nParecer: NAO promover para DW antes de corrigir os erros.")


def self_test() -> None:
    produto = {
        "produto_id": "P1",
        "produto": "Top treino",
        "categoria": "Tops",
        "custo_padrao": Decimal("10.00"),
        "preco_lista": Decimal("30.00"),
    }
    venda = {
        "fonte": "teste",
        "id_venda": "V1",
        "data_venda": "2026-01-10",
        "produto_id": "P1",
        "quantidade": 2,
        "valor_bruto": Decimal("60.00"),
        "valor_desconto": Decimal("0.00"),
        "valor_liquido": Decimal("60.00"),
        "custo_total": Decimal("20.00"),
        "margem_bruta": Decimal("40.00"),
        "status_pedido": "concluida",
        "canal": "loja_fisica",
        "unidade_id": "LOJA-1",
    }
    meta = {
        "ano_mes": "2026-01",
        "canal": "loja_fisica",
        "unidade_id": "LOJA-1",
        "meta_receita_liquida": Decimal("1000.00"),
        "meta_pedidos": 10,
        "meta_ticket_medio": Decimal("100.00"),
        "meta_margem_bruta_pct": Decimal("40.00"),
        "meta_taxa_devolucao_pct": Decimal("2.00"),
    }
    resultado = {
        "staging": {"stg_vendas": [venda], "stg_produtos": [produto], "stg_metas": [meta]},
        "status_cargas": [{"fonte": "teste", "status": "sucesso", "mensagem": "OK"}],
        "status_staging": [{"fonte": "teste", "status": "sucesso", "mensagem": "OK"}],
    }

    relatorio = validar_staging(resultado)
    assert relatorio["pode_promover_dw"] is True

    resultado["staging"]["stg_vendas"][0]["produto_id"] = "P2"
    relatorio = validar_staging(resultado)
    assert relatorio["pode_promover_dw"] is False
    assert relatorio["erros"] > 0

    vendas = []
    for indice in range(200):
        venda_com_centavo = venda.copy()
        venda_com_centavo["id_venda"] = f"V{indice}"
        venda_com_centavo["produto_id"] = "P1"
        venda_com_centavo["margem_bruta"] = Decimal("40.01")
        vendas.append(venda_com_centavo)
    resultado["staging"]["stg_vendas"] = vendas
    resultado["staging"]["stg_produtos"] = [produto]
    resultado["staging"]["stg_metas"] = [meta]
    relatorio = validar_staging(resultado)
    assert relatorio["pode_promover_dw"] is False
    assert any(check["nome"] == "arredondamento_agregado" and check["status"] == "erro" for check in relatorio["validacoes"])
    print("self-test: OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        imprimir_relatorio(validar_staging())
