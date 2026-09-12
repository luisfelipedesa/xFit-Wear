from __future__ import annotations

# # Parametros para carga SQL da dim_data
#
# Python nao define o schema do DW. Este modulo so calcula a janela aprovada da
# dim_data a partir da staging validada, para o Airflow/Supabase executar SQL.
#
# NOTE: saida propositalmente pequena e sem IDs de venda/produto/cliente.
# TODO: quando stg_vendas e stg_metas existirem no Postgres, mover este calculo
# para SQL e deixar Python apenas disparar a etapa orquestrada.

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

try:
    from staging_data import gerar_staging
    from validate_staging import carregar_manifesto_auditoria, validar_staging
except ModuleNotFoundError:
    # FIXME: compatibilidade enquanto src ainda nao e pacote instalavel.
    from src.staging_data import gerar_staging
    from src.validate_staging import carregar_manifesto_auditoria, validar_staging


def gerar_carga_dw_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex


def ultimo_dia_do_mes_staging(ano_mes: str) -> date:
    ano, mes = (int(parte) for parte in ano_mes.split("-"))
    if mes == 12:
        primeiro_dia_mes_seguinte = date(ano + 1, 1, 1)
    else:
        primeiro_dia_mes_seguinte = date(ano, mes + 1, 1)
    return primeiro_dia_mes_seguinte - timedelta(days=1)


def calcular_janela_calendario_dim_data(vendas: list[dict], metas: list[dict]) -> tuple[date, date]:
    datas_vendas = [date.fromisoformat(venda["data_venda"]) for venda in vendas]
    fins_de_mes_meta = [ultimo_dia_do_mes_staging(meta["ano_mes"]) for meta in metas]

    if not datas_vendas and not fins_de_mes_meta:
        raise ValueError("staging sem datas para dim_data")

    data_inicial = min(datas_vendas) if datas_vendas else min(fins_de_mes_meta)
    data_final_vendas = max(datas_vendas) if datas_vendas else data_inicial
    data_final_metas = max(fins_de_mes_meta) if fins_de_mes_meta else data_inicial
    return data_inicial, max(data_final_vendas, data_final_metas)


def preparar_chamada_sql_dim_data(manifesto_auditoria: dict | None = None, carga_dw_id: str | None = None) -> dict:
    resultado_staging = gerar_staging()
    relatorio_staging = validar_staging(resultado_staging, manifesto_auditoria=manifesto_auditoria)
    carga_dw_id = carga_dw_id or gerar_carga_dw_id()

    if not relatorio_staging["pode_promover_dw"]:
        return {
            "status": "erro",
            "pode_executar_sql": False,
            "carga_dw_id": carga_dw_id,
            "mensagem": "staging reprovada; nao executar carga SQL da dim_data.",
        }

    staging = resultado_staging["staging"]
    data_inicial, data_final = calcular_janela_calendario_dim_data(
        staging["stg_vendas"],
        staging["stg_metas"],
    )
    dias_previstos = (data_final - data_inicial).days + 1

    return {
        "status": "sucesso",
        "pode_executar_sql": True,
        "carga_dw_id": carga_dw_id,
        "data_inicial": data_inicial.isoformat(),
        "data_final": data_final.isoformat(),
        "dias_previstos": dias_previstos,
        "sql_schema": "sql/schema_dw.sql",
        "sql_funcao": "select dw.carregar_dim_data(:data_inicial, :data_final);",
    }


def imprimir_parametros_dim_data(resultado: dict) -> None:
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


def executar_preparo_dim_data_cli() -> int:
    argumentos = argparse.ArgumentParser(description="Prepara parametros seguros para a carga SQL da dim_data.")
    argumentos.add_argument("--manifesto", help="manifesto de auditoria em data/processed/manifests/<carga_id>.json")
    argumentos.add_argument("--carga-dw-id", default=gerar_carga_dw_id(), help="identificador da carga SQL no DW")
    opcoes = argumentos.parse_args()

    try:
        manifesto = carregar_manifesto_auditoria(opcoes.manifesto) if opcoes.manifesto else None
        resultado = preparar_chamada_sql_dim_data(manifesto_auditoria=manifesto, carga_dw_id=opcoes.carga_dw_id)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError) as erro:
        print(f"Preparo da dim_data interrompido ({erro.__class__.__name__}); confira staging e manifesto.", file=sys.stderr)
        return 2

    imprimir_parametros_dim_data(resultado)
    return 0 if resultado["pode_executar_sql"] else 1


if __name__ == "__main__":
    raise SystemExit(executar_preparo_dim_data_cli())
