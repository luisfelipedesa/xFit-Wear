"""Valida o snapshot local com backup, sem conectar ao DW."""

import argparse
import json

from data_lake_audit import validar_formato_id_carga
from preparar_carga_supabase import preparar_staging_aprovada


def executar_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--carga-id', required=True)
    args = parser.parse_args()
    try:
        validar_formato_id_carga(args.carga_id)
        _, relatorio = preparar_staging_aprovada(args.carga_id)
    except (OSError, ValueError, KeyError, TypeError) as erro:
        print(f'Validacao interrompida ({type(erro).__name__}); promocao bloqueada.')
        return 2
    print(json.dumps({'status': 'sucesso', 'carga_id': args.carga_id,
                      'linhas': relatorio['linhas']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(executar_cli())
