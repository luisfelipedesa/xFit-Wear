from __future__ import annotations

# # Contrato compartilhado das fontes locais
#
# Auditoria e extracao precisam olhar para o mesmo mapa de arquivos. Antes
# disso, cada etapa tinha sua propria lista e a gente podia auditar uma coisa
# e carregar outra sem perceber.
#
# NOTE: este modulo nao decide regra de negocio da staging. Ele so resolve
# caminho, conta registros e calcula assinatura do arquivo local.

import csv
import hashlib
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_SOURCES_FILE = BASE_DIR / "config" / "data_sources.json"


def caminho_pertence_ao_projeto(caminho: Path, base_dir: Path = BASE_DIR) -> bool:
    caminho_resolvido = caminho.resolve()
    raiz = base_dir.resolve()
    return caminho_resolvido == raiz or raiz in caminho_resolvido.parents


def caminho_relativo_ao_projeto(caminho: Path, base_dir: Path = BASE_DIR) -> str:
    return caminho.resolve().relative_to(base_dir.resolve()).as_posix()


def carregar_contrato_fontes(caminho_config: Path = DATA_SOURCES_FILE) -> dict:
    if not caminho_config.exists():
        raise FileNotFoundError("Contrato de fontes nao encontrado")

    contrato = json.loads(caminho_config.read_text(encoding="utf-8"))
    fontes = contrato.get("data_sources", [])
    if not isinstance(fontes, list) or not fontes:
        raise ValueError("Contrato de fontes sem data_sources")

    return contrato


def listar_fontes_de_dados(contrato: dict, incluir_markdown: bool = True) -> list[dict]:
    fontes = contrato.get("data_sources", [])
    if incluir_markdown:
        return list(fontes)
    return [fonte for fonte in fontes if fonte.get("type") != "markdown"]


def localizar_arquivo_fonte(fonte: dict, base_dir: Path = BASE_DIR) -> Path:
    caminho_relativo_fonte = fonte.get("path")
    if not caminho_relativo_fonte:
        raise ValueError("Fonte sem path configurado")

    caminho = Path(caminho_relativo_fonte)
    if caminho.is_absolute():
        raise ValueError("Fonte com path absoluto bloqueado")

    caminho_resolvido = (base_dir / caminho).resolve()
    if not caminho_pertence_ao_projeto(caminho_resolvido, base_dir):
        raise ValueError("Fonte fora do projeto bloqueada")

    return caminho_resolvido


def calcular_sha256_arquivo(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def contar_linhas_csv(caminho: Path) -> int:
    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        return max(0, sum(1 for _ in arquivo) - 1)


def contar_registros_json(caminho: Path) -> int | None:
    payload = json.loads(caminho.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return len(payload["records"])
    return None


def contar_registros_da_fonte(fonte: dict, caminho: Path) -> int | None:
    tipo = fonte.get("type")
    if tipo == "csv" or caminho.suffix.lower() == ".csv":
        return contar_linhas_csv(caminho)
    if tipo in {"json_records", "json_api"} or caminho.suffix.lower() == ".json":
        return contar_registros_json(caminho)
    return None


def levantar_assinatura_fonte(fonte: dict, base_dir: Path = BASE_DIR, caminho_lido: Path | None = None) -> dict:
    caminho = caminho_lido or localizar_arquivo_fonte(fonte, base_dir)
    assinatura = {
        "fonte": fonte.get("name"),
        "path": caminho_relativo_ao_projeto(caminho, base_dir),
        "tipo": fonte.get("type"),
        "obrigatoria": bool(fonte.get("required", True)),
        "existe": caminho.exists(),
        "tamanho_bytes": None,
        "sha256": None,
        "linhas_ou_registros": None,
        "erro": None,
    }

    if not caminho_pertence_ao_projeto(caminho, base_dir):
        assinatura["erro"] = "caminho fora do projeto"
        return assinatura

    if not caminho.exists():
        assinatura["erro"] = "arquivo ausente"
        return assinatura

    if not caminho.is_file():
        assinatura["erro"] = "fonte nao e arquivo regular"
        return assinatura

    assinatura["tamanho_bytes"] = caminho.stat().st_size
    assinatura["sha256"] = calcular_sha256_arquivo(caminho)

    try:
        assinatura["linhas_ou_registros"] = contar_registros_da_fonte(fonte, caminho)
    except Exception as erro:
        # TODO: quando A07 fechar, separar detalhe tecnico de mensagem publica.
        assinatura["erro"] = f"falha ao contar registros: {erro.__class__.__name__}"

    return assinatura
