from __future__ import annotations

# Primeira versao da extracao do data lake local.
# A ideia aqui ainda nao e transformar os dados: primeiro eu quero provar que
# as fontes existem, que o contrato minimo esta de pe e que a carga tem volume.
#
# TODO: quando o Airflow entrar, revisar se esse arquivo continua como tarefa
# PythonOperator ou se vira modulo chamado por um script de carga separado.
# NOTE: agora a carga e parcial por fonte. Se Barbacena falhar, Lafaiete e
# ecommerce ainda podem seguir, mas o BI precisa mostrar o status da falha.

import csv
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from source_contract import (
        carregar_contrato_fontes,
        levantar_assinatura_fonte,
        listar_fontes_de_dados,
        localizar_arquivo_fonte,
        caminho_pertence_ao_projeto,
    )
except ModuleNotFoundError:
    # FIXME: manter compatibilidade enquanto src ainda nao e pacote instalavel.
    from src.source_contract import (
        carregar_contrato_fontes,
        levantar_assinatura_fonte,
        listar_fontes_de_dados,
        localizar_arquivo_fonte,
        caminho_pertence_ao_projeto,
    )


BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / ".env"


COLUNAS_VENDAS = {
    "id_venda",
    "data_venda",
    "cliente_id",
    "produto_id",
    "quantidade",
    "valor_liquido",
    "status_pedido",
    "canal",
}

COLUNAS_METAS = {
    "ano_mes",
    "canal",
    "unidade_id",
    "meta_receita_liquida",
    "meta_pedidos",
}

COLUNAS_PRODUTOS = {
    "produto_id",
    "produto",
    "categoria",
    "preco_lista",
    "custo_padrao",
}


REGRAS_EXTRACAO_POR_FONTE = {
    "vendas_barbacena": {
        "env": "XFIT_VENDAS_BARBACENA_PATH",
        "grupo": "vendas",
        "colunas": COLUNAS_VENDAS | {"loja_id"},
        "campo_data": "data_venda",
    },
    "vendas_conselheiro_lafaiete": {
        "env": "XFIT_VENDAS_LAFAIETE_PATH",
        "grupo": "vendas",
        "colunas": COLUNAS_VENDAS | {"loja_id"},
        "campo_data": "data_venda",
    },
    "vendas_ecommerce": {
        "env": "XFIT_ECOMMERCE_JSON_PATH",
        "grupo": "vendas",
        "colunas": COLUNAS_VENDAS | {"pedido_online_id"},
        "campo_data": "data_venda",
    },
    "metas_mensais": {
        "env": "XFIT_METAS_PATH",
        "grupo": "cadastros",
        "colunas": COLUNAS_METAS,
        "campo_data": "ano_mes",
    },
    "produtos": {
        "env": "XFIT_PRODUTOS_PATH",
        "grupo": "cadastros",
        "colunas": COLUNAS_PRODUTOS,
        "campo_data": None,
    },
}


def carregar_env(caminho: Path = ENV_FILE) -> None:
    # FIXME: parser de .env bem simples. Serve para KEY=VALUE, mas nao tenta
    # cobrir todos os casos que uma lib tipo python-dotenv cobriria.
    if not caminho.exists():
        return

    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue

        if "=" not in linha:
            # TODO: trocar por log estruturado quando o Airflow entrar.
            print("Linha ignorada no .env sem formato KEY=VALUE")
            continue

        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def caminho_env(nome_variavel: str) -> Path | None:
    # NOTE: aceitamos caminho relativo para o projeto nao depender do D:\ local.
    # Se um caminho absoluto aparecer no .env, ele ainda precisa ficar dentro
    # da pasta do projeto. Isso evita leitura acidental de arquivo fora da base.
    valor = os.environ.get(nome_variavel)
    if not valor:
        return None

    caminho = Path(valor)
    if not caminho.is_absolute():
        caminho = BASE_DIR / caminho

    caminho = caminho.resolve()
    if not caminho_pertence_ao_projeto(caminho, BASE_DIR):
        raise ValueError(f"Caminho fora do projeto bloqueado: {nome_variavel}")

    return caminho


def ler_csv(caminho: Path) -> list[dict]:
    # NOTE: mantive csv da stdlib de proposito. Pandas entra depois, se a
    # transformacao realmente pedir dataframe.
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {caminho}")

    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=";")
        return list(leitor)


def ler_json(caminho: Path) -> dict:
    # TODO: hoje o ecommerce vem do JSON mock. Quando for endpoint HTTP mesmo,
    # tratar timeout, pagina, retry e erro 500 sem esconder falha de carga.
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {caminho}")

    with caminho.open("r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def validar_colunas(nome_fonte: str, linhas: list[dict], colunas_obrigatorias: set[str]) -> None:
    # TODO: esta validacao ainda e estrutural. No staging vamos validar tipos,
    # datas invalidas, numeros negativos e status fora do dominio esperado.
    if not linhas:
        raise ValueError(f"Fonte sem dados: {nome_fonte}")

    colunas_encontradas = set(linhas[0].keys())
    faltando = colunas_obrigatorias - colunas_encontradas

    if faltando:
        raise ValueError(f"Fonte {nome_fonte} sem colunas obrigatorias: {sorted(faltando)}")


def resumir_periodo(linhas: list[dict], campo_data: str | None) -> tuple[str | None, str | None]:
    if not campo_data:
        return None, None

    # NOTE: datas estao em ISO yyyy-mm-dd, entao min/max por texto funciona.
    # Se mudar o formato da fonte, essa economia vira bug e precisa virar date().
    datas = [linha[campo_data] for linha in linhas if linha.get(campo_data)]
    if not datas:
        return None, None

    return min(datas), max(datas)


def status_fonte(
    nome_fonte: str,
    status: str,
    linhas_lidas: int = 0,
    data_minima: str | None = None,
    data_maxima: str | None = None,
    mensagem: str = "OK",
) -> dict:
    return {
        "fonte": nome_fonte,
        "status": status,
        "linhas_lidas": linhas_lidas,
        "data_minima": data_minima,
        "data_maxima": data_maxima,
        "mensagem": mensagem,
        "data_execucao": datetime.now().isoformat(timespec="seconds"),
    }


def mensagem_segura(erro: Exception) -> str:
    # NOTE: antes a gente tentava mascarar caminho em str(erro). Isso ainda
    # podia vazar valor da fonte. Para log publico, fica so a categoria.
    return f"Falha ao carregar fonte ({erro.__class__.__name__})"


def fontes_contratadas_para_extracao() -> dict:
    contrato = carregar_contrato_fontes()
    fontes = {}
    for fonte in listar_fontes_de_dados(contrato, incluir_markdown=False):
        nome_fonte = fonte.get("name")
        regra = REGRAS_EXTRACAO_POR_FONTE.get(nome_fonte)
        if regra is None:
            raise ValueError(f"Fonte sem regra de extracao: {nome_fonte}")
        fontes[nome_fonte] = {**fonte, **regra}
    return fontes


def caminho_fonte_contratada_ou_env(fonte: dict) -> Path:
    caminho_sobrescrito = caminho_env(fonte["env"])
    if caminho_sobrescrito is not None:
        # NOTE: mantemos o override por .env para testes e operacao local, mas
        # o snapshot no status denuncia quando nao bate com o contrato auditado.
        return caminho_sobrescrito
    return localizar_arquivo_fonte(fonte, BASE_DIR)


def ler_fonte(nome_fonte: str, config: dict) -> tuple[list[dict], dict]:
    caminho = caminho_fonte_contratada_ou_env(config)
    assinatura = levantar_assinatura_fonte(config, BASE_DIR, caminho_lido=caminho)

    tipo_fonte = config.get("type")
    if tipo_fonte == "csv":
        return ler_csv(caminho), assinatura

    if tipo_fonte in {"json_records", "json_api"}:
        payload = ler_json(caminho)
        return payload.get("records", []), assinatura

    raise ValueError(f"Tipo de fonte nao suportado: {tipo_fonte}")


def tentar_carregar_fonte(nome_fonte: str, config: dict) -> tuple[str, list[dict], dict]:
    try:
        linhas, assinatura = ler_fonte(nome_fonte, config)
        validar_colunas(nome_fonte, linhas, config["colunas"])
        data_minima, data_maxima = resumir_periodo(linhas, config["campo_data"])
        status = status_fonte(
            nome_fonte,
            "sucesso",
            linhas_lidas=len(linhas),
            data_minima=data_minima,
            data_maxima=data_maxima,
        )
        status.update({
            "path": assinatura["path"],
            "sha256": assinatura["sha256"],
            "tamanho_bytes": assinatura["tamanho_bytes"],
            "linhas_ou_registros": assinatura["linhas_ou_registros"],
        })

        return (
            nome_fonte,
            linhas,
            status,
        )
    except Exception as erro:
        # FIXME: ainda nao temos tabela de auditoria. Quando tiver, talvez seja
        # util gravar erro_tecnico separado de mensagem_usuario.
        return (
            nome_fonte,
            [],
            status_fonte(nome_fonte, "falha", mensagem=mensagem_segura(erro)),
        )


def carregar_data_lake() -> dict:
    carregar_env()
    fontes = fontes_contratadas_para_extracao()

    resultado = {
        "dados": {},
        "status_cargas": [],
        "contrato_fontes": "config/data_sources.json",
    }

    for nome_fonte, config in fontes.items():
        nome, linhas, status = tentar_carregar_fonte(nome_fonte, config)
        resultado["status_cargas"].append(status)

        if status["status"] == "sucesso":
            resultado["dados"][nome] = linhas

    return resultado


def imprimir_resumo(resultado: dict) -> None:
    print("\nResumo de carga do data lake")
    print("-" * 32)

    for item in resultado["status_cargas"]:
        periodo = ""
        if item["data_minima"] and item["data_maxima"]:
            periodo = f" ({item['data_minima']} ate {item['data_maxima']})"

        print(
            f"{item['fonte']}: {item['status']} | "
            f"{item['linhas_lidas']} linhas{periodo} | {item['mensagem']}"
        )


if __name__ == "__main__":
    resumo_carga = carregar_data_lake()
    imprimir_resumo(resumo_carga)
