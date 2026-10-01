"""# Carga historica automatizada para PostgreSQL

Python valida e envia staging; a promocao dimensional continua em SQL.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import ssl
import tempfile

import psycopg
from psycopg import sql

from data_lake_audit import (
    registrar_execucao_auditoria, validar_destino_auditoria, validar_formato_id_carga,
)
from extract_data_lake import carregar_env
from preparar_carga_supabase import DESTINO, preparar_staging_aprovada
from preparar_dim_data_dw import gerar_carga_dw_id

RAIZ = Path(__file__).resolve().parents[1]
PAPEL_PIPELINE = 'xfit_pipeline'
CHAVE_BLOQUEIO = 867530901
CHAVES_STAGING = {
    'stg_produtos': ('produto_id',),
    'stg_metas': ('unidade_id', 'ano_mes'),
    'stg_vendas': ('fonte', 'id_venda', 'produto_id'),
}
CAMPOS_CONFERENCIA = {
    'stg_produtos': ('preco_lista', 'custo_padrao'),
    'stg_metas': ('meta_receita_liquida', 'meta_pedidos', 'meta_ticket_medio',
                  'meta_margem_bruta_pct', 'meta_taxa_devolucao_pct'),
    'stg_vendas': ('quantidade', 'valor_bruto', 'valor_desconto', 'valor_liquido',
                   'custo_total', 'margem_bruta'),
}


def configuracao_postgres():
    carregar_env()
    nomes = {'host': 'HOST', 'port': 'PORT', 'dbname': 'DATABASE',
             'user': 'USER', 'password': 'PASSWORD'}
    parametros = {chave: os.environ.get('XFIT_PG_' + nome, '') for chave, nome in nomes.items()}
    if not all(parametros.values()):
        raise ValueError('Configuracao XFIT_PG incompleta; confira o .env local')
    if parametros['user'].split('.')[0] != PAPEL_PIPELINE:
        raise ValueError('A carga exige o usuario restrito xfit_pipeline')
    # NOTE: o bloqueio de sessao exige conexao direta ou pooler de sessao (5432).
    if parametros['port'] != '5432':
        raise ValueError('Use conexao direta ou pooler de sessao na porta 5432')
    parametros.update(sslmode='verify-full', connect_timeout=15,
                      application_name='xfit-pipeline', prepare_threshold=None,
                      autocommit=True)
    return parametros


@contextmanager
def certificado_postgres():
    certificado = os.environ.get('XFIT_PG_SSLROOTCERT')
    if certificado:
        caminho = Path(certificado)
        if not caminho.is_absolute():
            caminho = RAIZ / caminho
        if not caminho.is_file():
            raise ValueError('Certificado CA configurado nao encontrado')
        yield str(caminho)
        return
    # Sem CA explicita, tentar as raizes do sistema sem desligar TLS/hostname checks.
    # Se a CA do servidor nao estiver nesse conjunto, configurar o certificado oficial.
    raizes = ssl.create_default_context().get_ca_certs(binary_form=True)
    if not raizes:
        raise ValueError('Sistema sem certificados CA confiaveis')
    destino = validar_destino_auditoria(DESTINO / 'tls', DESTINO)
    destino.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ca-', dir=destino) as pasta:
        caminho = Path(pasta) / 'roots.pem'
        caminho.write_text(''.join(ssl.DER_cert_to_PEM_cert(ca) for ca in raizes), encoding='ascii')
        yield str(caminho)


def conferir_papel_conexao(conexao):
    papel = conexao.execute(
        'select current_user, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls '
        'from pg_roles where rolname = current_user'
    ).fetchone()
    if not papel or papel[0] != PAPEL_PIPELINE or any(papel[1:]):
        raise ValueError('Conexao sem o papel restrito esperado')
    # NOTE: pg_stat_ssl mostra o trecho pooler->banco, nao o TLS deste cliente.
    if not conexao.pgconn.ssl_in_use:
        raise ValueError('Conexao PostgreSQL sem TLS')


def enviar_staging_postgres(cursor, staging):
    for tabela, chaves in CHAVES_STAGING.items():
        linhas = staging[tabela]
        colunas = tuple(linhas[0])
        temporaria = sql.Identifier('xfit_' + tabela)
        destino = sql.Identifier('stg', tabela)
        campos = sql.SQL(', ').join(map(sql.Identifier, colunas))
        cursor.execute(sql.SQL('create temporary table {} (like {}) on commit drop').format(temporaria, destino))
        with cursor.copy(sql.SQL('copy {} ({}) from stdin').format(temporaria, campos)) as copia:
            for linha in linhas:
                copia.write_row(tuple(linha[coluna] for coluna in colunas))
        atualizacoes = sql.SQL(', ').join(
            sql.SQL('{} = excluded.{}').format(sql.Identifier(c), sql.Identifier(c))
            for c in colunas if c not in chaves
        )
        cursor.execute(sql.SQL(
            'insert into {} ({}) select {} from {} where true '
            'on conflict ({}) do update set {}'
        ).format(destino, campos, campos, temporaria,
                 sql.SQL(', ').join(map(sql.Identifier, chaves)), atualizacoes))


def conferir_transferencia_staging(cursor, staging):
    for tabela, campos in CAMPOS_CONFERENCIA.items():
        somas = sql.SQL(', ').join(
            sql.SQL('coalesce(sum({}), 0)').format(sql.Identifier(c)) for c in campos
        )
        cursor.execute(sql.SQL('select count(*), {} from {}').format(
            somas, sql.Identifier('stg', tabela)))
        esperado = (len(staging[tabela]),) + tuple(
            sum((linha[c] for linha in staging[tabela]), Decimal(0)) for c in campos
        )
        if cursor.fetchone() != esperado:
            raise ValueError('Staging remota diverge do snapshot aprovado')


def registrar_status_local(carga_id, status, mensagem):
    registrar_execucao_auditoria({'carga_id': carga_id, 'etapa': 'postgres',
        'status': status, 'mensagem': mensagem,
        'data': datetime.now(timezone.utc).isoformat()})


def promover_dw_postgres(cursor, carga_dw_id):
    cursor.execute("select set_config('xfit.carga_dw_id', %s, true)", (carga_dw_id,))
    cursor.execute((RAIZ / 'sql' / 'carregar_dw.sql').read_text(encoding='utf-8'))
    cursor.execute('select status from etl.cargas_dw where carga_dw_id = %s', (carga_dw_id,))
    if cursor.fetchone() != ('sucesso',):
        raise ValueError('Promocao dimensional nao foi aprovada')


def executar_carga_postgres(conexao, carga_id):
    validar_formato_id_carga(carga_id)
    conferir_papel_conexao(conexao)
    carga_dw_id = 'dw-' + carga_id
    if not conexao.execute('select pg_try_advisory_lock(%s)', (CHAVE_BLOQUEIO,)).fetchone()[0]:
        raise ValueError('Outra carga do pipeline esta em execucao')
    registrada = False
    try:
        conexao.execute(
            "insert into etl.cargas_dw (carga_dw_id, carga_origem_id, etapa, status) "
            "values (%s, %s, 'validacao', 'iniciada')", (carga_dw_id, carga_id))
        registrada = True
        staging, relatorio = preparar_staging_aprovada(carga_id)
        with conexao.transaction():
            with conexao.cursor() as cursor:
                cursor.execute("set local statement_timeout = '10min'")
                cursor.execute("set local lock_timeout = '15s'")
                cursor.execute("set local timezone = 'UTC'")
                enviar_staging_postgres(cursor, staging)
                conferir_transferencia_staging(cursor, staging)
                promover_dw_postgres(cursor, carga_dw_id)
        resultado = {'status': 'sucesso', 'carga_id': carga_id, 'carga_dw_id': carga_dw_id,
                     'linhas_staging': relatorio['linhas']}
        # NOTE: erro de log depois do commit nao deve marcar uma carga concluida como erro.
    except Exception as erro:
        mensagem = f'Carga interrompida ({type(erro).__name__}); dados anteriores preservados'
        if registrada:
            try:
                conexao.execute("update etl.cargas_dw set status = 'erro', mensagem_publica = %s, "
                                'atualizado_em = now() where carga_dw_id = %s', (mensagem, carga_dw_id))
            except psycopg.Error:
                # TODO: reconciliar cargas iniciadas quando a conexao cair antes do registro da falha.
                pass
        try:
            registrar_status_local(carga_id, 'erro', mensagem)
        except OSError:
            pass
        raise
    finally:
        if not conexao.closed:
            try:
                conexao.execute('select pg_advisory_unlock(%s)', (CHAVE_BLOQUEIO,))
            except psycopg.Error:
                # Fechar a conexao tambem libera o bloqueio; preservar o erro original.
                pass
    try:
        registrar_status_local(carga_id, 'sucesso', 'Staging e DW confirmados na mesma transacao')
    except OSError:
        resultado['aviso'] = 'Carga confirmada; registro local de log indisponivel'
    return resultado


def executar_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--carga-id', default=gerar_carga_dw_id())
    parser.add_argument('--verificar-conexao', action='store_true')
    args = parser.parse_args()
    try:
        parametros = configuracao_postgres()
        with certificado_postgres() as certificado:
            with psycopg.connect(**parametros, sslrootcert=certificado) as conexao:
                if args.verificar_conexao:
                    conferir_papel_conexao(conexao)
                    resultado = {'status': 'sucesso', 'papel': PAPEL_PIPELINE, 'tls_verificado': True}
                else:
                    resultado = executar_carga_postgres(conexao, args.carga_id)
    except (psycopg.Error, OSError, ValueError, KeyError, TypeError) as erro:
        # Nunca imprimir str(erro): o driver pode incluir host, credencial ou linha rejeitada.
        print(f'Automacao interrompida ({type(erro).__name__}); confira configuracao e registros da carga.')
        return 2
    print(json.dumps(resultado, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(executar_cli())
