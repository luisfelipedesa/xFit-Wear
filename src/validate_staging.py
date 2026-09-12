from __future__ import annotations

# Validacao de qualidade da staging antes de promover para DW.
#
# Esta etapa ainda nao cria dim/fato. A ideia e barrar erro silencioso:
# produto vendido sem cadastro, unidade sem meta, valor incoerente etc.
#
# TODO: quando existir banco, gravar este resultado em etl.validacoes_staging.
# NOTE: os self-tests cobrem regras financeiras; testes de completude ficam
# em tests/test_completude_staging.py, sem depender das fontes locais.
# NOTE: mensagens deste relatorio nao mostram caminhos locais nem conteudo do .env.

import argparse
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from typing import Iterable
import sys

try:
    from staging_data import gerar_staging, FONTES_VENDAS, FONTE_PRODUTOS, FONTE_METAS
except ModuleNotFoundError:
    # FIXME: manter compatibilidade enquanto src ainda nao e pacote instalavel.
    from src.staging_data import gerar_staging, FONTES_VENDAS, FONTE_PRODUTOS, FONTE_METAS


LIMITE_EXEMPLOS = 5
BASE_DIR = Path(__file__).resolve().parents[1]
MANIFEST_DIR = BASE_DIR / "data" / "processed" / "manifests"
TOLERANCIA_CENTAVOS = Decimal("0.02")
MATERIALIDADE_ABSOLUTA_GRUPO = Decimal("1.00")
MATERIALIDADE_RELATIVA_RECEITA = Decimal("0.0001")
FONTES_DA_CARGA_HISTORICA = set(FONTES_VENDAS) | {FONTE_PRODUTOS, FONTE_METAS}
TABELAS_OBRIGATORIAS_STAGING = {
    "stg_vendas": FONTES_VENDAS,
    "stg_produtos": [FONTE_PRODUTOS],
    "stg_metas": [FONTE_METAS],
}
CAMPOS_IDENTIDADE_VENDA = (
    "fonte",
    "id_venda",
    "data_venda",
    "hora_venda",
    "cliente_id",
    "canal",
    "unidade_id",
    "status_pedido",
    "produto_id",
)


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


def mensagem_com_total(descricao: str, total: int) -> str:
    # NOTE: relatorio pode ir para log ou job scheduler. Deixar IDs fora da
    # mensagem; quem precisar investigar deve usar rejeicoes controladas depois.
    return f"{descricao}: {total} ocorrencias"


def contar_linhas_reais_da_staging_historica(conferencia: dict, tabelas_staging: dict) -> tuple[dict, Counter]:
    linhas_por_fonte = Counter()
    linhas_por_tabela = dict.fromkeys(TABELAS_OBRIGATORIAS_STAGING, 0)

    # NOTE: todas as fontes sao obrigatorias nesta carga historica completa.
    # Carga incremental sem movimento exigira outro contrato; nao presumir isso.
    for nome_tabela, fontes_da_tabela in TABELAS_OBRIGATORIAS_STAGING.items():
        linhas_staging = tabelas_staging.get(nome_tabela)
        if not isinstance(linhas_staging, list) or not linhas_staging:
            adicionar_erro(conferencia, f"{nome_tabela}: tabela ausente, vazia ou fora do formato esperado.")
            continue

        linhas_por_tabela[nome_tabela] = len(linhas_staging)
        if any(not isinstance(linha, dict) for linha in linhas_staging):
            adicionar_erro(conferencia, f"{nome_tabela}: registro fora do formato esperado.")
            continue

        if nome_tabela == "stg_vendas":
            vendas_sem_fonte_reconhecida = 0
            for venda in linhas_staging:
                fonte_venda = venda.get("fonte")
                if not isinstance(fonte_venda, str) or fonte_venda not in fontes_da_tabela:
                    vendas_sem_fonte_reconhecida += 1
                else:
                    linhas_por_fonte[fonte_venda] += 1
            if vendas_sem_fonte_reconhecida:
                adicionar_erro(
                    conferencia,
                    f"stg_vendas: {vendas_sem_fonte_reconhecida} registros sem fonte reconhecida.",
                )
        else:
            linhas_por_fonte[fontes_da_tabela[0]] = len(linhas_staging)

    return linhas_por_tabela, linhas_por_fonte


def mapear_status_obrigatorio_por_fonte(
    conferencia: dict,
    resultado: dict,
    nome_lista_status: str,
    campos_de_volume: tuple[str, ...],
) -> dict:
    status_por_fonte = {}
    status_da_etapa = resultado.get(nome_lista_status)
    if not isinstance(status_da_etapa, list):
        adicionar_erro(conferencia, f"{nome_lista_status}: lista de status ausente ou invalida.")
        status_da_etapa = []

    for item_status in status_da_etapa:
        fonte_status = item_status.get("fonte") if isinstance(item_status, dict) else None
        if not isinstance(fonte_status, str) or fonte_status not in FONTES_DA_CARGA_HISTORICA:
            adicionar_erro(conferencia, f"{nome_lista_status}: status sem fonte reconhecida.")
            continue
        if fonte_status in status_por_fonte:
            adicionar_erro(conferencia, f"{nome_lista_status}: mais de um status para {fonte_status}.")
            continue

        status_por_fonte[fonte_status] = item_status
        if item_status.get("status") != "sucesso":
            adicionar_erro(conferencia, f"{nome_lista_status}: {fonte_status} nao concluiu com sucesso.")

        for campo_volume in campos_de_volume:
            volume_declarado = item_status.get(campo_volume)
            if type(volume_declarado) is not int or volume_declarado <= 0:
                adicionar_erro(
                    conferencia,
                    f"{nome_lista_status}: {fonte_status} precisa de {campo_volume} inteiro e positivo.",
                )

    for fonte_esperada in sorted(FONTES_DA_CARGA_HISTORICA - status_por_fonte.keys()):
        adicionar_erro(conferencia, f"{nome_lista_status}: status obrigatorio ausente para {fonte_esperada}.")

    return status_por_fonte


def conferir_volume_por_fonte_da_carga_historica(
    conferencia: dict,
    status_cargas_por_fonte: dict,
    status_staging_por_fonte: dict,
    linhas_por_fonte: Counter,
) -> None:
    # NOTE: conferir por fonte, nao apenas pelo total de stg_vendas. Uma loja
    # com linhas a mais nao pode compensar registros perdidos de outra loja.
    for fonte_esperada in sorted(FONTES_DA_CARGA_HISTORICA):
        status_extracao = status_cargas_por_fonte.get(fonte_esperada, {})
        status_staging = status_staging_por_fonte.get(fonte_esperada, {})
        volumes_da_fonte = [
            status_extracao.get("linhas_lidas"),
            status_staging.get("linhas_entrada"),
            status_staging.get("linhas_saida"),
            linhas_por_fonte[fonte_esperada],
        ]
        if any(type(total) is not int or total <= 0 for total in volumes_da_fonte):
            adicionar_erro(conferencia, f"{fonte_esperada}: volume nao comprovado nas etapas da carga.")
        elif len(set(volumes_da_fonte)) != 1:
            adicionar_erro(
                conferencia,
                f"{fonte_esperada}: contagens divergem entre extracao, staging e tabela.",
            )


# ## Completude da carga historica antes das regras de negocio
def conferir_completude_staging(resultado: dict) -> dict:
    conferencia = novo_check("completude_staging")
    linhas_por_fonte = Counter()
    linhas_por_tabela = dict.fromkeys(TABELAS_OBRIGATORIAS_STAGING, 0)
    conferencia["metricas"]["linhas_por_tabela"] = linhas_por_tabela
    tabelas_staging = resultado.get("staging")
    if not isinstance(tabelas_staging, dict):
        adicionar_erro(conferencia, "Bloco staging ausente ou fora do formato esperado.")
        tabelas_staging = {}

    linhas_por_tabela, linhas_por_fonte = contar_linhas_reais_da_staging_historica(conferencia, tabelas_staging)
    conferencia["metricas"]["linhas_por_tabela"] = linhas_por_tabela

    status_cargas_por_fonte = mapear_status_obrigatorio_por_fonte(
        conferencia,
        resultado,
        "status_cargas",
        ("linhas_lidas",),
    )
    status_staging_por_fonte = mapear_status_obrigatorio_por_fonte(
        conferencia,
        resultado,
        "status_staging",
        ("linhas_entrada", "linhas_saida"),
    )
    conferir_volume_por_fonte_da_carga_historica(
        conferencia,
        status_cargas_por_fonte,
        status_staging_por_fonte,
        linhas_por_fonte,
    )

    conferencia["metricas"]["linhas_por_fonte"] = dict(linhas_por_fonte)
    # TODO: reconciliar com o snapshot auditado quando a carga tiver identidade
    # compartilhada. Contagens consistentes nao provam a identidade dos itens.
    return conferencia


def validar_manifesto_da_mesma_carga(resultado: dict, manifesto: dict) -> dict:
    check = novo_check("snapshot_auditoria_carga")
    arquivos_manifesto = {
        arquivo.get("fonte"): arquivo
        for arquivo in manifesto.get("arquivos", [])
        if isinstance(arquivo, dict) and arquivo.get("fonte") in FONTES_DA_CARGA_HISTORICA
    }
    status_extraidos = {
        status.get("fonte"): status
        for status in resultado.get("status_cargas", [])
        if isinstance(status, dict) and status.get("fonte") in FONTES_DA_CARGA_HISTORICA
    }
    campos_snapshot = ("path", "sha256", "tamanho_bytes", "linhas_ou_registros")

    check["metricas"] = {
        "carga_id": manifesto.get("carga_id"),
        "fontes_manifesto": len(arquivos_manifesto),
        "fontes_extraidas": len(status_extraidos),
        "fontes_com_snapshot_divergente": 0,
    }

    if manifesto.get("status") != "sucesso":
        adicionar_erro(check, "manifesto da auditoria nao esta com status sucesso.")

    for fonte in sorted(FONTES_DA_CARGA_HISTORICA):
        assinatura_auditada = arquivos_manifesto.get(fonte)
        assinatura_extraida = status_extraidos.get(fonte)
        if not assinatura_auditada or not assinatura_extraida:
            adicionar_erro(check, f"{fonte}: snapshot ausente na auditoria ou na extracao.")
            continue

        for campo in campos_snapshot:
            if assinatura_auditada.get(campo) != assinatura_extraida.get(campo):
                check["metricas"]["fontes_com_snapshot_divergente"] += 1
                adicionar_erro(check, f"{fonte}: snapshot da extracao diverge do manifesto auditado.")
                break

    # TODO: exigir carga_id no resultado da extracao quando o orquestrador local
    # existir. Hoje o manifesto e passado ao validador como prova externa.
    return check


def validar_identidade_itens_vendidos(vendas: list[dict]) -> dict:
    check = novo_check("identidade_itens_vendidos")
    cabecalho_por_pedido = {}
    produtos_por_pedido = defaultdict(set)
    itens_por_pedido_produto = Counter()
    vendas_sem_identidade = 0
    pedidos_com_cabecalho_conflitante = set()

    for venda in vendas:
        if any(venda.get(campo) in (None, "") for campo in CAMPOS_IDENTIDADE_VENDA):
            vendas_sem_identidade += 1
            continue

        chave_pedido = (venda["fonte"], venda["id_venda"])
        cabecalho_pedido = (
            venda["fonte"],
            venda["id_venda"],
            venda["data_venda"],
            venda["hora_venda"],
            venda["cliente_id"],
            venda["canal"],
            venda["unidade_id"],
            venda["status_pedido"],
        )
        if chave_pedido in cabecalho_por_pedido and cabecalho_por_pedido[chave_pedido] != cabecalho_pedido:
            pedidos_com_cabecalho_conflitante.add(chave_pedido)
        else:
            cabecalho_por_pedido[chave_pedido] = cabecalho_pedido

        produtos_por_pedido[chave_pedido].add(venda["produto_id"])
        # NOTE: a staging ainda nao preserva item_id, tamanho ou cor. Por isso
        # fonte+pedido+produto repetido fica ambiguo e deve ser resolvido antes
        # de gerar venda_item_id no DW.
        itens_por_pedido_produto[(venda["fonte"], venda["id_venda"], venda["produto_id"])] += 1

    itens_ambiguos = [
        chave_item
        for chave_item, total in itens_por_pedido_produto.items()
        if total > 1
    ]
    pedidos_multiplos_itens = [
        chave_pedido
        for chave_pedido, produtos in produtos_por_pedido.items()
        if len(produtos) > 1
    ]

    check["metricas"] = {
        "linhas_vendas_avaliadas": len(vendas),
        "pedidos_distintos": len(cabecalho_por_pedido),
        "pedidos_com_multiplos_produtos": len(pedidos_multiplos_itens),
        "itens_sem_chave_confiavel": len(itens_ambiguos),
        "pedidos_com_cabecalho_conflitante": len(pedidos_com_cabecalho_conflitante),
        "vendas_sem_campos_identidade": vendas_sem_identidade,
    }

    if vendas_sem_identidade:
        adicionar_erro(check, "vendas sem campos obrigatorios para identificar pedido e item.")

    if pedidos_com_cabecalho_conflitante:
        adicionar_erro(check, "id_venda reaproveitado com cabecalho de pedido divergente.")

    if itens_ambiguos:
        adicionar_erro(check, "fonte/id_venda/produto_id repetido; nao ha item_id para diferenciar as linhas.")

    # TODO: quando a fonte trouxer item_id ou numero_linha_pedido, esta regra
    # deve migrar para essa chave natural e liberar repeticoes hoje ambiguas.
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
        adicionar_erro(check, mensagem_com_total("produto_id duplicado no cadastro", len(duplicados)))

    if sem_cadastro:
        adicionar_erro(check, mensagem_com_total("produto_id vendido sem cadastro", len(sem_cadastro)))

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
        adicionar_erro(check, mensagem_com_total("unidade_id com venda e sem meta", len(unidades_sem_meta)))

    if canais_conflitantes:
        adicionar_erro(
            check,
            mensagem_com_total("unidade_id com canal divergente entre venda/meta", len(canais_conflitantes)),
        )

    if metas_sem_venda:
        adicionar_alerta(check, mensagem_com_total("unidade_id com meta mas sem venda no periodo", len(metas_sem_venda)))

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
        adicionar_erro(check, mensagem_com_total("unidade/mes com venda e sem meta", len(vendas_sem_meta)))

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
        adicionar_erro(check, mensagem_com_total("vendas com quantidade/valor invalido", len(set(vendas_negativas))))

    if margens_inconsistentes:
        adicionar_erro(
            check,
            mensagem_com_total("vendas com margem/custo inconsistente", len(set(margens_inconsistentes))),
        )

    if canceladas_com_valor:
        adicionar_erro(check, mensagem_com_total("vendas canceladas com receita liquida", len(set(canceladas_com_valor))))

    if metas_invalidas:
        adicionar_erro(check, mensagem_com_total("metas com valor invalido", len(set(metas_invalidas))))

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
        adicionar_erro(check, mensagem_com_total("grupos acima da materialidade", len(grupos_acima)))

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
        adicionar_erro(check, mensagem_com_total("vendas com data futura", len(vendas_futuras)))

    if metas_duplicadas:
        adicionar_erro(check, mensagem_com_total("metas duplicadas por unidade/mes", len(metas_duplicadas)))

    return check


def validar_staging(resultado: dict | None = None, manifesto_auditoria: dict | None = None) -> dict:
    if resultado is None:
        resultado = gerar_staging()

    completude = conferir_completude_staging(resultado)
    validacoes = [completude]
    if manifesto_auditoria is not None:
        validacoes.append(validar_manifesto_da_mesma_carga(resultado, manifesto_auditoria))
    if completude["status"] == "ok":
        staging = resultado["staging"]
        vendas = staging["stg_vendas"]
        produtos = staging["stg_produtos"]
        metas = staging["stg_metas"]
        validacoes.extend([
            validar_identidade_itens_vendidos(vendas),
            validar_produtos(vendas, produtos),
            validar_unidades_e_metas(vendas, metas),
            validar_cobertura_mensal(vendas, metas),
            validar_valores(vendas, produtos, metas),
            validar_arredondamento_agregado(vendas),
            validar_status_e_datas(vendas, metas),
        ])
    # Sem estrutura/volume completo, nao emitir pareceres de negocio parciais.
    erros = sum(len(check["erros"]) for check in validacoes)
    alertas = sum(len(check["alertas"]) for check in validacoes)

    return {
        "status_geral": "aprovado" if erros == 0 else "reprovado",
        "pode_promover_dw": erros == 0,
        "erros": erros,
        "alertas": alertas,
        "linhas": completude["metricas"]["linhas_por_tabela"],
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
        "fonte": FONTES_VENDAS[0],
        "id_venda": "V1",
        "data_venda": "2026-01-10",
        "hora_venda": "10:00:00",
        "cliente_id": "CLI-00001",
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
        "staging": {
            "stg_vendas": [dict(venda, fonte=fonte, id_venda=f"V{indice}")
                           for indice, fonte in enumerate(FONTES_VENDAS)],
            "stg_produtos": [produto],
            "stg_metas": [meta],
        },
        "status_cargas": [
            {"fonte": fonte, "status": "sucesso", "linhas_lidas": 1}
            for fonte in [*FONTES_VENDAS, FONTE_PRODUTOS, FONTE_METAS]
        ],
        "status_staging": [
            {"fonte": fonte, "status": "sucesso", "linhas_entrada": 1, "linhas_saida": 1}
            for fonte in [*FONTES_VENDAS, FONTE_PRODUTOS, FONTE_METAS]
        ],
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
    resultado["staging"]["stg_vendas"] = vendas + resultado["staging"]["stg_vendas"][1:]
    resultado["status_cargas"][0]["linhas_lidas"] = 200
    resultado["status_staging"][0].update(linhas_entrada=200, linhas_saida=200)
    resultado["staging"]["stg_produtos"] = [produto]
    resultado["staging"]["stg_metas"] = [meta]
    relatorio = validar_staging(resultado)
    assert relatorio["pode_promover_dw"] is False
    assert any(check["nome"] == "arredondamento_agregado" and check["status"] == "erro" for check in relatorio["validacoes"])
    print("self-test: OK")


def carregar_manifesto_auditoria(caminho_informado: str) -> dict:
    caminho = Path(caminho_informado)
    if not caminho.is_absolute():
        caminho = BASE_DIR / caminho
    caminho = caminho.resolve()
    raiz_manifestos = MANIFEST_DIR.resolve()
    if caminho != raiz_manifestos and raiz_manifestos not in caminho.parents:
        raise ValueError("Manifesto fora do diretorio operacional permitido")
    return json.loads(caminho.read_text(encoding="utf-8"))


# ## Resultado da validacao para o processo que chamou o comando
def executar_validacao_staging_cli() -> int:
    argumentos = argparse.ArgumentParser(description="Valida a staging antes da promocao para DW.")
    argumentos.add_argument("--self-test", action="store_true", help="testa as regras de validacao")
    argumentos.add_argument("--manifesto", help="manifesto de auditoria em data/processed/manifests/<carga_id>.json")
    opcoes = argumentos.parse_args()

    if opcoes.self_test:
        self_test()
        return 0

    try:
        manifesto = carregar_manifesto_auditoria(opcoes.manifesto) if opcoes.manifesto else None
        relatorio_staging = validar_staging(manifesto_auditoria=manifesto)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError) as erro:
        # NOTE: sem relatorio confiavel, devolver falha tecnica. Nao imprimir
        # a excecao completa, pois ela pode conter valores da fonte ou caminhos.
        print(f"Validacao da staging interrompida ({type(erro).__name__}); confira a configuracao e as fontes locais.", file=sys.stderr)
        return 2

    imprimir_relatorio(relatorio_staging)
    # NOTE: exibir 'reprovado' nao basta para um agendador interromper a carga.
    # Alertas continuam seguindo a regra existente de pode_promover_dw.
    return 0 if relatorio_staging["pode_promover_dw"] else 1


if __name__ == "__main__":
    raise SystemExit(executar_validacao_staging_cli())
