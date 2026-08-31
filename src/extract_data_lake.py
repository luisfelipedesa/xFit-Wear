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


FONTES = {
    "vendas_barbacena": {
        "env": "XFIT_VENDAS_BARBACENA_PATH",
        "tipo": "csv",
        "grupo": "vendas",
        "colunas": COLUNAS_VENDAS | {"loja_id"},
        "campo_data": "data_venda",
    },
    "vendas_conselheiro_lafaiete": {
        "env": "XFIT_VENDAS_LAFAIETE_PATH",
        "tipo": "csv",
        "grupo": "vendas",
        "colunas": COLUNAS_VENDAS | {"loja_id"},
        "campo_data": "data_venda",
    },
    "vendas_ecommerce": {
        "env": "XFIT_ECOMMERCE_JSON_PATH",
        "tipo": "json_api",
        "grupo": "vendas",
        "colunas": COLUNAS_VENDAS | {"pedido_online_id"},
        "campo_data": "data_venda",
    },
    "metas_mensais": {
        "env": "XFIT_METAS_PATH",
        "tipo": "csv",
        "grupo": "cadastros",
        "colunas": COLUNAS_METAS,
        "campo_data": "ano_mes",
    },
    "produtos": {
        "env": "XFIT_PRODUTOS_PATH",
        "tipo": "csv",
        "grupo": "cadastros",
        "colunas": COLUNAS_PRODUTOS,
        "campo_data": None,
    },
}


def carregar_env(caminho: Path = ENV_FILE) -> None:
    # FIXME: parser de .env bem simples. Serve para KEY=VALUE, mas nao tenta
    # cobrir todos os casos que uma lib tipo python-dotenv cobriria.
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo .env nao encontrado: {caminho}")

    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue

        if "=" not in linha:
            # TODO: trocar por log estruturado quando o Airflow entrar.
            print(f"Linha ignorada no .env: {linha}")
            continue

        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def caminho_env(nome_variavel: str) -> Path:
    # NOTE: aceitamos caminho relativo para o projeto nao depender do D:\ local.
    # Se um caminho absoluto aparecer no .env, ele ainda precisa ficar dentro
    # da pasta do projeto. Isso evita leitura acidental de arquivo fora da base.
    valor = os.environ.get(nome_variavel)
    if not valor:
        raise ValueError(f"Variavel obrigatoria ausente no .env: {nome_variavel}")

    caminho = Path(valor)
    if not caminho.is_absolute():
        caminho = BASE_DIR / caminho

    caminho = caminho.resolve()
    raiz = BASE_DIR.resolve()

    if raiz not in caminho.parents and caminho != raiz:
        raise ValueError(f"Caminho fora do projeto bloqueado: {nome_variavel}={caminho}")

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
    # NOTE: erro com caminho absoluto ajuda no debug local, mas pode vazar a
    # estrutura da maquina se isso aparecer no painel de status do BI.
    mensagem = str(erro)
    return mensagem.replace(str(BASE_DIR.resolve()), "<projeto>")


def ler_fonte(nome_fonte: str, config: dict) -> list[dict]:
    caminho = caminho_env(config["env"])

    if config["tipo"] == "csv":
        return ler_csv(caminho)

    if config["tipo"] == "json_api":
        payload = ler_json(caminho)
        return payload.get("records", [])

    raise ValueError(f"Tipo de fonte nao suportado: {config['tipo']}")


def tentar_carregar_fonte(nome_fonte: str, config: dict) -> tuple[str, list[dict], dict]:
    try:
        linhas = ler_fonte(nome_fonte, config)
        validar_colunas(nome_fonte, linhas, config["colunas"])
        data_minima, data_maxima = resumir_periodo(linhas, config["campo_data"])

        return (
            nome_fonte,
            linhas,
            status_fonte(
                nome_fonte,
                "sucesso",
                linhas_lidas=len(linhas),
                data_minima=data_minima,
                data_maxima=data_maxima,
            ),
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

    resultado = {
        "dados": {},
        "status_cargas": [],
    }

    for nome_fonte, config in FONTES.items():
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
