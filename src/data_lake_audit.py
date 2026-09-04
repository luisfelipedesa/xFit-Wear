from __future__ import annotations

# Data lake audit - manifestos, checksums, backup snapshots and run logs.
#
# TODO: persistir manifestos em etl.manifestos_arquivo quando houver banco.
# TODO: substituir backup em arquivo por carga transacional com rollback.
# NOTE: data/processed fica fora do Git porque guarda trilha operacional local.

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ID = "xfit_wear"
PROJECT_NAME = "xFit Wear"
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_SOURCES_FILE = BASE_DIR / "config" / "data_sources.json"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
MANIFEST_DIR = PROCESSED_DIR / "manifests"
BACKUP_DIR = PROCESSED_DIR / "backups"
LOG_DIR = PROCESSED_DIR / "logs"
RUN_LOG = LOG_DIR / "etl_runs.jsonl"


def agora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def novo_carga_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def caminho_relativo(caminho: Path) -> str:
    return caminho.resolve().relative_to(BASE_DIR.resolve()).as_posix()


def dentro_do_projeto(caminho: Path) -> bool:
    caminho_resolvido = caminho.resolve()
    raiz = BASE_DIR.resolve()
    return caminho_resolvido == raiz or raiz in caminho_resolvido.parents


def carregar_contrato_fontes(caminho_config: Path = DATA_SOURCES_FILE) -> dict:
    if not caminho_config.exists():
        raise FileNotFoundError(f"Contrato de fontes nao encontrado: {caminho_relativo(caminho_config)}")

    contrato = json.loads(caminho_config.read_text(encoding="utf-8"))
    fontes = contrato.get("data_sources", [])
    if not isinstance(fontes, list) or not fontes:
        raise ValueError("Contrato de fontes sem data_sources")

    return contrato


def resolver_fonte(fonte: dict) -> Path:
    caminho_relativo_fonte = fonte.get("path")
    if not caminho_relativo_fonte:
        raise ValueError(f"Fonte sem path configurado: {fonte.get('name')}")

    caminho = Path(caminho_relativo_fonte)
    if caminho.is_absolute():
        raise ValueError(f"Fonte com path absoluto bloqueado: {fonte.get('name')}")

    caminho_resolvido = (BASE_DIR / caminho).resolve()
    if not dentro_do_projeto(caminho_resolvido):
        raise ValueError(f"Fonte fora do projeto bloqueada: {fonte.get('name')}")

    return caminho_resolvido


def sha256_arquivo(caminho: Path) -> str:
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


def inventariar_arquivo(fonte: dict) -> dict:
    caminho = resolver_fonte(fonte)
    item = {
        "fonte": fonte.get("name"),
        "path": caminho_relativo(caminho),
        "tipo": fonte.get("type"),
        "obrigatoria": bool(fonte.get("required", True)),
        "existe": caminho.exists(),
        "tamanho_bytes": None,
        "sha256": None,
        "linhas_ou_registros": None,
        "erro": None,
    }

    if not dentro_do_projeto(caminho):
        item["erro"] = "caminho fora do projeto"
        return item

    if not caminho.exists():
        item["erro"] = "arquivo ausente"
        return item

    item["tamanho_bytes"] = caminho.stat().st_size
    item["sha256"] = sha256_arquivo(caminho)

    try:
        if caminho.suffix.lower() == ".csv":
            item["linhas_ou_registros"] = contar_linhas_csv(caminho)
        elif caminho.suffix.lower() == ".json":
            item["linhas_ou_registros"] = contar_registros_json(caminho)
    except Exception as erro:
        # FIXME: separar erro_tecnico quando existir tabela etl.erros.
        item["erro"] = f"falha ao contar registros: {erro.__class__.__name__}"

    return item


def registrar_log(evento: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(evento, ensure_ascii=False, default=str) + "\n")


def criar_backup(carga_id: str, fontes: list[dict]) -> dict:
    destino_raiz = BACKUP_DIR / carga_id
    arquivos_copiados = []
    arquivos_ausentes = []

    for fonte in fontes:
        caminho = resolver_fonte(fonte)

        if not caminho.exists():
            arquivos_ausentes.append(caminho_relativo(caminho))
            continue

        destino = destino_raiz / caminho.relative_to(BASE_DIR)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(caminho, destino)
        arquivos_copiados.append(caminho_relativo(caminho))

    return {
        "backup_dir": caminho_relativo(destino_raiz),
        "arquivos_copiados": arquivos_copiados,
        "arquivos_ausentes": arquivos_ausentes,
    }


def gerar_manifesto(carga_id: str, criar_snapshot_backup: bool = False) -> dict:
    inicio = agora_utc()
    contrato = carregar_contrato_fontes()
    fontes = contrato["data_sources"]
    arquivos = [inventariar_arquivo(fonte) for fonte in fontes]
    erros = [item for item in arquivos if item["erro"]]
    backup = criar_backup(carga_id, fontes) if criar_snapshot_backup else None
    fim = agora_utc()

    manifesto = {
        "project_id": contrato.get("project_id", PROJECT_ID),
        "project_name": contrato.get("project_name", PROJECT_NAME),
        "ambiente": contrato.get("environment", "local"),
        "politica_operacional": "tratar_fontes_locais_com_controles_de_producao",
        "contrato_fontes": caminho_relativo(DATA_SOURCES_FILE),
        "carga_id": carga_id,
        "status": "erro" if erros else "sucesso",
        "inicio": inicio,
        "fim": fim,
        "arquivos": arquivos,
        "backup": backup,
    }

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    caminho_manifesto = MANIFEST_DIR / f"{carga_id}.json"
    caminho_manifesto.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    registrar_log(
        {
            "project_id": PROJECT_ID,
            "project_name": PROJECT_NAME,
            "carga_id": carga_id,
            "etapa": "data_lake_audit",
            "status": manifesto["status"],
            "inicio": inicio,
            "fim": fim,
            "manifesto": caminho_relativo(caminho_manifesto),
            "arquivos_avaliados": len(arquivos),
            "arquivos_com_erro": len(erros),
        }
    )
    return manifesto


def imprimir_resumo(manifesto: dict) -> None:
    print("\nAuditoria local do data lake")
    print("-" * 32)
    print(f"project_id: {manifesto['project_id']}")
    print(f"carga_id: {manifesto['carga_id']}")
    print(f"status: {manifesto['status']}")
    print(f"arquivos: {len(manifesto['arquivos'])}")

    for item in manifesto["arquivos"]:
        status = "ok" if not item["erro"] else f"erro: {item['erro']}"
        print(
            f"{item['path']}: {status} | "
            f"{item['linhas_ou_registros']} registros | {item['tamanho_bytes']} bytes"
        )

    if manifesto["backup"]:
        print(f"backup_dir: {manifesto['backup']['backup_dir']}")
        print(f"arquivos_copiados: {len(manifesto['backup']['arquivos_copiados'])}")


def self_test() -> None:
    contrato = carregar_contrato_fontes()
    fontes = contrato["data_sources"]
    item = inventariar_arquivo(fontes[0])
    assert item["path"].endswith("vendas_barbacena.csv")
    assert item["existe"] is True
    assert item["sha256"]
    assert item["linhas_ou_registros"] is not None
    assert dentro_do_projeto(BASE_DIR / "data")
    try:
        resolver_fonte({"name": "fora", "path": "../fora.csv"})
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal deveria ser bloqueado")
    print("self-test: OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera manifesto, log e backup opcional do data lake local.")
    parser.add_argument("--backup", action="store_true", help="copia as fontes atuais para data/processed/backups/<carga_id>")
    parser.add_argument("--carga-id", default=novo_carga_id(), help="identificador da execucao")
    parser.add_argument("--self-test", action="store_true", help="executa validacao rapida do script")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    manifesto = gerar_manifesto(args.carga_id, criar_snapshot_backup=args.backup)
    imprimir_resumo(manifesto)


if __name__ == "__main__":
    main()
