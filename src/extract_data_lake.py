from __future__ import annotations

# Primeira versao da extracao do data lake local.
# A ideia aqui ainda nao e transformar os dados: primeiro eu quero provar que
# as fontes existem, que o contrato minimo esta de pe e que a carga tem volume.
#
# TODO: quando o Airflow entrar, revisar se esse arquivo continua como tarefa
# PythonOperator ou se vira modulo chamado por um script de carga separado.

import csv
import json
import os
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


def resumir_vendas(nome_fonte: str, linhas: list[dict]) -> dict:
    # NOTE: datas estao em ISO yyyy-mm-dd, entao min/max por texto funciona.
    # Se mudar o formato da fonte, essa economia vira bug e precisa virar date().
    datas = [linha["data_venda"] for linha in linhas if linha.get("data_venda")]

    return {
        "fonte": nome_fonte,
        "linhas": len(linhas),
        "data_inicial": min(datas),
        "data_final": max(datas),
    }


def resumir_cadastro(nome_fonte: str, linhas: list[dict]) -> dict:
    return {"fonte": nome_fonte, "linhas": len(linhas)}


def carregar_data_lake() -> dict:
    # Ordem meio explicita mesmo: fica mais facil para revisar no comeco do projeto.
    # Depois, se crescer demais, a gente compacta em um dicionario de fontes.
    carregar_env()

    vendas_barbacena = ler_csv(caminho_env("XFIT_VENDAS_BARBACENA_PATH"))
    vendas_lafaiete = ler_csv(caminho_env("XFIT_VENDAS_LAFAIETE_PATH"))
    metas = ler_csv(caminho_env("XFIT_METAS_PATH"))
    produtos = ler_csv(caminho_env("XFIT_PRODUTOS_PATH"))

    payload_ecommerce = ler_json(caminho_env("XFIT_ECOMMERCE_JSON_PATH"))
    vendas_ecommerce = payload_ecommerce.get("records", [])

    # Nao deixar carga "meio certa" passar. Se o contrato minimo quebrou,
    # melhor falhar aqui do que descobrir pelo Power BI com numero estranho.
    validar_colunas("vendas_barbacena", vendas_barbacena, COLUNAS_VENDAS | {"loja_id"})
    validar_colunas("vendas_conselheiro_lafaiete", vendas_lafaiete, COLUNAS_VENDAS | {"loja_id"})
    validar_colunas("vendas_ecommerce", vendas_ecommerce, COLUNAS_VENDAS | {"pedido_online_id"})
    validar_colunas("metas_mensais", metas, COLUNAS_METAS)
    validar_colunas("produtos", produtos, COLUNAS_PRODUTOS)

    # NOTE: por enquanto so resumimos. A camada staging vem no proximo passo.
    return {
        "vendas": [
            resumir_vendas("vendas_barbacena", vendas_barbacena),
            resumir_vendas("vendas_conselheiro_lafaiete", vendas_lafaiete),
            resumir_vendas("vendas_ecommerce", vendas_ecommerce),
        ],
        "cadastros": [
            resumir_cadastro("metas_mensais", metas),
            resumir_cadastro("produtos", produtos),
        ],
    }


def imprimir_resumo(resumo: dict) -> None:
    print("\nResumo de carga do data lake")
    print("-" * 32)

    for item in resumo["vendas"]:
        print(
            f"{item['fonte']}: {item['linhas']} linhas "
            f"({item['data_inicial']} ate {item['data_final']})"
        )

    for item in resumo["cadastros"]:
        print(f"{item['fonte']}: {item['linhas']} linhas")


if __name__ == "__main__":
    resumo_carga = carregar_data_lake()
    imprimir_resumo(resumo_carga)
