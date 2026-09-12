from __future__ import annotations

# # Auditoria local do data lake
# Manifestos, checksums, snapshots de backup e logs por carga.
#
# TODO: persistir manifestos em etl.manifestos_arquivo quando houver banco.
# TODO: substituir backup em arquivo por carga transacional com rollback.
# NOTE: data/processed fica fora do Git porque guarda trilha operacional local.

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    from source_contract import (
        carregar_contrato_fontes as carregar_contrato_fontes_compartilhado,
        calcular_sha256_arquivo,
        contar_linhas_csv,
        contar_registros_json,
        levantar_assinatura_fonte,
        localizar_arquivo_fonte as localizar_arquivo_fonte_compartilhado,
        caminho_pertence_ao_projeto as caminho_pertence_ao_projeto_compartilhado,
        caminho_relativo_ao_projeto as caminho_relativo_ao_projeto_compartilhado,
    )
except ModuleNotFoundError:
    # FIXME: manter compatibilidade enquanto src ainda nao e pacote instalavel.
    from src.source_contract import (
        carregar_contrato_fontes as carregar_contrato_fontes_compartilhado,
        calcular_sha256_arquivo,
        contar_linhas_csv,
        contar_registros_json,
        levantar_assinatura_fonte,
        localizar_arquivo_fonte as localizar_arquivo_fonte_compartilhado,
        caminho_pertence_ao_projeto as caminho_pertence_ao_projeto_compartilhado,
        caminho_relativo_ao_projeto as caminho_relativo_ao_projeto_compartilhado,
    )


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


def gerar_id_carga() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex


# ## Identidade da carga e limites de escrita
def validar_formato_id_carga(carga_id: str) -> None:
    # NOTE: nao limpar ou substituir caracteres. Alterar o ID poderia fazer
    # duas entradas diferentes apontarem para o mesmo backup.
    if not isinstance(carga_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", carga_id):
        raise ValueError("carga_id deve ter 1 a 80 letras ASCII, numeros, hifens ou underscores; iniciar com letra ou numero")
    if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", carga_id, re.IGNORECASE):
        raise ValueError("carga_id usa nome reservado pelo sistema operacional")


def validar_destino_auditoria(caminho: Path, raiz: Path) -> Path:
    destino = caminho.resolve()
    raiz_resolvida = raiz.resolve()
    if not caminho_pertence_ao_projeto(raiz_resolvida) or raiz_resolvida not in destino.parents:
        raise ValueError("Destino operacional fora do diretorio permitido")
    # NOTE: links/junctions preexistentes nao devem redirecionar uma escrita,
    # mesmo para outra pasta do projeto. Validar antes de mkdir/open/copy.
    if caminho.absolute() != destino:
        raise ValueError("Destino operacional redirecionado por link ou junction")
    return destino


def caminho_relativo_ao_projeto(caminho: Path) -> str:
    return caminho_relativo_ao_projeto_compartilhado(caminho, BASE_DIR)


def caminho_pertence_ao_projeto(caminho: Path) -> bool:
    return caminho_pertence_ao_projeto_compartilhado(caminho, BASE_DIR)


def carregar_contrato_fontes(caminho_config: Path = DATA_SOURCES_FILE) -> dict:
    return carregar_contrato_fontes_compartilhado(caminho_config)


def localizar_arquivo_fonte(fonte: dict) -> Path:
    return localizar_arquivo_fonte_compartilhado(fonte, BASE_DIR)


def levantar_metadados_fonte(fonte: dict) -> dict:
    return levantar_assinatura_fonte(fonte, BASE_DIR)


def registrar_execucao_auditoria(evento: dict) -> None:
    destino_log = validar_destino_auditoria(RUN_LOG, LOG_DIR)
    destino_log.parent.mkdir(parents=True, exist_ok=True)
    with destino_log.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(evento, ensure_ascii=False, default=str) + "\n")


def copiar_fontes_para_backup(carga_id: str, fontes: list[dict]) -> dict:
    validar_formato_id_carga(carga_id)
    destino_raiz = validar_destino_auditoria(BACKUP_DIR / carga_id, BACKUP_DIR)
    manifesto_existente = validar_destino_auditoria(MANIFEST_DIR / f"{carga_id}.json", MANIFEST_DIR)
    if manifesto_existente.exists():
        raise FileExistsError("Carga ja possui manifesto; use um novo carga_id")
    arquivos_copiados = []
    arquivos_ausentes = []
    copias = []

    # ## Conferir todas as fontes antes de criar a pasta da carga
    for fonte in fontes:
        caminho = localizar_arquivo_fonte(fonte)

        if not caminho.exists():
            arquivos_ausentes.append(caminho_relativo_ao_projeto(caminho))
            continue

        if not caminho.is_file():
            raise ValueError("Fonte de backup deve ser arquivo regular")
        destino = validar_destino_auditoria(destino_raiz / caminho.relative_to(BASE_DIR.resolve()), destino_raiz)
        copias.append((caminho, destino))

    # mkdir exclusivo reserva a carga. Se outra execucao chegou antes, falhar.
    destino_raiz.mkdir(parents=True, exist_ok=False)
    for caminho, destino in copias:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with caminho.open("rb") as origem, destino.open("xb") as copia:
            shutil.copyfileobj(origem, copia)
        shutil.copystat(caminho, destino)
        arquivos_copiados.append(caminho_relativo_ao_projeto(caminho))

    # TODO: registrar estado incompleto e validar hash da copia na mesma carga.
    # Por enquanto, falha preserva a pasta parcial e o ID fica bloqueado.
    return {
        "backup_dir": caminho_relativo_ao_projeto(destino_raiz),
        "arquivos_copiados": arquivos_copiados,
        "arquivos_ausentes": arquivos_ausentes,
    }


def auditar_fontes_da_carga(carga_id: str, criar_snapshot_backup: bool = False) -> dict:
    validar_formato_id_carga(carga_id)
    caminho_manifesto = validar_destino_auditoria(MANIFEST_DIR / f"{carga_id}.json", MANIFEST_DIR)
    caminho_backup = validar_destino_auditoria(BACKUP_DIR / carga_id, BACKUP_DIR)
    validar_destino_auditoria(RUN_LOG, LOG_DIR)
    if caminho_manifesto.exists() or caminho_backup.exists():
        raise FileExistsError("Carga ja existe; use um novo carga_id")

    inicio = agora_utc()
    contrato = carregar_contrato_fontes()
    fontes = contrato["data_sources"]
    arquivos = [levantar_metadados_fonte(fonte) for fonte in fontes]
    erros = [item for item in arquivos if item["erro"]]
    backup = copiar_fontes_para_backup(carga_id, fontes) if criar_snapshot_backup else None
    fim = agora_utc()

    manifesto = {
        "project_id": contrato.get("project_id", PROJECT_ID),
        "project_name": contrato.get("project_name", PROJECT_NAME),
        "ambiente": contrato.get("environment", "local"),
        "politica_operacional": "tratar_fontes_locais_com_controles_de_producao",
        "contrato_fontes": caminho_relativo_ao_projeto(DATA_SOURCES_FILE),
        "carga_id": carga_id,
        "status": "erro" if erros else "sucesso",
        "inicio": inicio,
        "fim": fim,
        "arquivos": arquivos,
        "backup": backup,
    }

    caminho_manifesto.parent.mkdir(parents=True, exist_ok=True)
    # A consulta exists acima melhora a falha normal; modo x impede sobrescrita
    # tambem quando outra execucao cria o arquivo depois daquela consulta.
    with caminho_manifesto.open("x", encoding="utf-8") as arquivo:
        json.dump(manifesto, arquivo, indent=2, ensure_ascii=False, default=str)

    registrar_execucao_auditoria(
        {
            "project_id": PROJECT_ID,
            "project_name": PROJECT_NAME,
            "carga_id": carga_id,
            "etapa": "data_lake_audit",
            "status": manifesto["status"],
            "inicio": inicio,
            "fim": fim,
            "manifesto": caminho_relativo_ao_projeto(caminho_manifesto),
            "arquivos_avaliados": len(arquivos),
            "arquivos_com_erro": len(erros),
        }
    )
    return manifesto


def exibir_resultado_auditoria(manifesto: dict) -> None:
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
    item = levantar_metadados_fonte(fontes[0])
    assert item["path"].endswith("vendas_barbacena.csv")
    assert item["existe"] is True
    assert item["sha256"]
    assert item["linhas_ou_registros"] is not None
    assert caminho_pertence_ao_projeto(BASE_DIR / "data")
    try:
        localizar_arquivo_fonte({"name": "fora", "path": "../fora.csv"})
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal deveria ser bloqueado")
    print("self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera manifesto, log e backup opcional do data lake local.")
    parser.add_argument("--backup", action="store_true", help="copia as fontes atuais para data/processed/backups/<carga_id>")
    parser.add_argument("--carga-id", default=gerar_id_carga(), help="identificador da execucao")
    parser.add_argument("--self-test", action="store_true", help="executa validacao rapida do script")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    try:
        manifesto = auditar_fontes_da_carga(args.carga_id, criar_snapshot_backup=args.backup)
    except (OSError, ValueError) as erro:
        # Nao devolver caminho pessoal nem a entrada invalida na mensagem CLI.
        print(f"Auditoria interrompida ({type(erro).__name__}); confira ID, destinos e permissoes locais.")
        raise SystemExit(2) from None
    exibir_resultado_auditoria(manifesto)
    # NOTE: um manifesto gravado pode registrar fontes com erro. O comando
    # precisa sinalizar essa reprovacao mesmo quando a gravacao funcionou.
    return 0 if manifesto["status"] == "sucesso" else 1


if __name__ == "__main__":
    raise SystemExit(main())
