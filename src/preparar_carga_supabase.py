"""Prepara lotes SQL privados a partir da staging aprovada; nao define o DW."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

from data_lake_audit import auditar_fontes_da_carga, validar_destino_auditoria
from preparar_dim_data_dw import calcular_janela_calendario_dim_data, gerar_carga_dw_id
from staging_data import gerar_staging
from validate_staging import validar_staging

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / 'data' / 'processed' / 'dw'


def literal_sql(valor):
    if valor is None:
        return 'NULL'
    if isinstance(valor, (int, Decimal)):
        return str(valor)
    return "'" + str(valor).replace("'", "''") + "'"


def preparar_staging_aprovada(carga_id):
    manifesto = auditar_fontes_da_carga(carga_id, criar_snapshot_backup=True)
    if manifesto['status'] != 'sucesso' or manifesto['backup']['arquivos_ausentes']:
        raise ValueError('Snapshot incompleto')
    resultado = gerar_staging()
    relatorio = validar_staging(resultado, manifesto_auditoria=manifesto)
    if not relatorio['pode_promover_dw']:
        raise ValueError('Staging reprovada; transferencia bloqueada')

    # NOTE: conferir as copias antes de liberar o snapshot para transferencia.
    from hashlib import sha256
    backup = RAIZ / manifesto['backup']['backup_dir']
    for item in manifesto['arquivos']:
        copia = backup / item['path']
        if sha256(copia.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Backup diverge do manifesto')

    return resultado['staging'], relatorio


def preparar_lotes(carga_id, tamanho_lote=1000):
    if not 1 <= tamanho_lote <= 5000:
        raise ValueError('Tamanho de lote invalido')
    pasta = validar_destino_auditoria(DESTINO / carga_id, DESTINO)
    if pasta.exists():
        raise FileExistsError('Carga ja preparada; use outro identificador')
    staging, relatorio = preparar_staging_aprovada(carga_id)

    pasta.mkdir(parents=True, exist_ok=False)
    arquivos = []
    for tabela in ('stg_produtos', 'stg_metas', 'stg_vendas'):
        linhas = staging[tabela]
        colunas = list(linhas[0])
        chave = {'stg_produtos': 'produto_id', 'stg_metas': 'unidade_id, ano_mes',
                 'stg_vendas': 'fonte, id_venda, produto_id'}[tabela]
        atualizar = ', '.join(f'{c} = excluded.{c}' for c in colunas if c not in chave.split(', '))
        for inicio in range(0, len(linhas), tamanho_lote):
            valores = ',\n'.join('(' + ','.join(literal_sql(linha[c]) for c in colunas) + ')'
                                  for linha in linhas[inicio:inicio + tamanho_lote])
            sql = ("begin;\nset local standard_conforming_strings = on;\n"
                   f"insert into stg.{tabela} ({', '.join(colunas)}) values\n{valores}\n"
                   f"on conflict ({chave}) do update set {atualizar};\ncommit;\n")
            nome = f'{len(arquivos):03d}_{tabela}.sql'
            with (pasta / nome).open('x', encoding='utf-8') as arquivo:
                arquivo.write(sql)
            arquivos.append(nome)

    inicio, fim = calcular_janela_calendario_dim_data(staging['stg_vendas'], staging['stg_metas'])
    resumo = {'carga_id': carga_id, 'linhas': relatorio['linhas'], 'arquivos': arquivos,
              'data_inicial': str(inicio), 'data_final': str(fim),
              'dias_previstos': (fim - inicio).days + 1,
              'valor_liquido': str(sum(v['valor_liquido'] for v in staging['stg_vendas']))}
    with (pasta / 'resumo.json').open('x', encoding='utf-8') as arquivo:
        json.dump(resumo, arquivo, indent=2)
    # NOTE: lotes exportados servem para inspecao; carregar_postgres usa COPY parametrizado.
    return resumo


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--carga-id', default=gerar_carga_dw_id())
    parser.add_argument('--tamanho-lote', type=int, default=1000)
    args = parser.parse_args()
    try:
        resumo = preparar_lotes(args.carga_id, args.tamanho_lote)
    except (OSError, ValueError, KeyError, TypeError) as erro:
        print(f'Preparo interrompido ({erro.__class__.__name__}); confira auditoria e staging.')
        raise SystemExit(2)
    print(json.dumps(resumo, indent=2))
