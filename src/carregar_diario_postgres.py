"""Publica somente staging diaria aprovada, sem reabrir fontes historicas."""

import argparse
from collections import Counter
from datetime import date, datetime, time
import json

import psycopg
from psycopg import sql

from carregar_postgres import (
    CHAVES_STAGING, certificado_postgres, configuracao_postgres, executar_carga_postgres,
)
from tratar_diario import RAIZ, assinatura, carregar_publicacao, ler_lote_aprovado


def conferir_diferencas(cursor, consulta, mensagem):
    cursor.execute(consulta)
    if cursor.fetchone()[0]:
        raise ValueError(mensagem)


def transferir_dia(cursor, staging, data, somente_conferir=False):
    for tabela, chaves in CHAVES_STAGING.items():
        linhas = staging[tabela]
        destino = sql.Identifier('stg', tabela)
        temporaria = sql.Identifier('xfit_diario_' + tabela)
        cursor.execute(sql.SQL('create temporary table {} (like {}) on commit drop').format(temporaria, destino))
        if linhas:
            colunas = tuple(linhas[0])
            campos = sql.SQL(', ').join(map(sql.Identifier, colunas))
            with cursor.copy(sql.SQL('copy {} ({}) from stdin').format(temporaria, campos)) as copia:
                for linha in linhas:
                    copia.write_row(tuple(linha[coluna] for coluna in colunas))
            campos_exatos = [campo for campo in colunas if campo != 'data_processamento']
            cursor.execute(sql.SQL('select {} from {}').format(campos, temporaria))
            recebidos = []
            for registro in cursor.fetchall():
                recebido = dict(zip(colunas, registro))
                for campo in campos_exatos:
                    if isinstance(recebido[campo], (date, datetime, time)):
                        recebido[campo] = recebido[campo].isoformat()
                recebidos.append(tuple(recebido[campo] for campo in campos_exatos))
            esperados = [tuple(linha[campo] for campo in campos_exatos) for linha in linhas]
            if Counter(recebidos) != Counter(esperados):
                raise ValueError('COPY alterou precisao ou conteudo aprovado')
        else:
            cursor.execute(sql.SQL('select * from {} limit 0').format(temporaria))
            campos_exatos = [coluna.name for coluna in cursor.description if coluna.name != 'data_processamento']
        campos_comparacao = sql.SQL(', ').join(map(sql.Identifier, campos_exatos))
        juncao = sql.SQL(' and ').join(sql.SQL('s.{} = t.{}').format(sql.Identifier(chave), sql.Identifier(chave))
                                      for chave in chaves)
        valores_origem = sql.SQL(', ').join(sql.SQL('t.{}').format(sql.Identifier(campo)) for campo in campos_exatos)
        valores_destino = sql.SQL(', ').join(sql.SQL('s.{}').format(sql.Identifier(campo)) for campo in campos_exatos)
        conferir_diferencas(cursor, sql.SQL(
            'select exists (select 1 from {temp} t join {destino} s on {juncao} '
            'where row({origem}) is distinct from row({dest}))'
        ).format(temp=temporaria, destino=destino, juncao=juncao,
                 origem=valores_origem, dest=valores_destino),
            'revisao_necessaria: dados existentes divergem do lote aprovado')
        if tabela == 'stg_vendas':
            cursor.execute(sql.SQL(
                'select exists (select 1 from {destino} s where s.data_venda = %s '
                'and not exists (select 1 from {temp} t where {juncao}))'
            ).format(destino=destino, temp=temporaria, juncao=juncao), (data,))
            if cursor.fetchone()[0]:
                raise ValueError('revisao_necessaria: nova entrega omite itens existentes')
            cursor.execute(sql.SQL(
                'select exists (select 1 from {destino} s join {temp} t '
                'on s.fonte=t.fonte and s.id_venda=t.id_venda where '
                'row(s.data_venda,s.hora_venda,s.cliente_id,s.canal,s.unidade_id,s.status_pedido) '
                'is distinct from row(t.data_venda,t.hora_venda,t.cliente_id,t.canal,t.unidade_id,t.status_pedido))'
            ).format(destino=destino, temp=temporaria))
            if cursor.fetchone()[0]:
                raise ValueError('revisao_necessaria: pedido com cabecalho divergente')
        if not somente_conferir:
            cursor.execute(sql.SQL('insert into {} select * from {} on conflict do nothing').format(destino, temporaria))
        conferir_diferencas(cursor, sql.SQL(
            'select exists (select {campos} from {temp} except all select {campos} from {destino})'
        ).format(campos=campos_comparacao, temp=temporaria, destino=destino),
            'Transferencia diaria diverge do lote aprovado')


def publicar_diario(conexao, manifesto, raiz=RAIZ):
    publicacao, staging = carregar_publicacao(manifesto, raiz)
    identidades = {unidade: ler_lote_aprovado(caminho, raiz)[0]['identidade']
                   for unidade, caminho in publicacao['selecao'].items()}
    carga_id = 'diario-' + publicacao['data_referencia'].replace('-', '')
    identidade_origem = assinatura(json.dumps([publicacao['data_referencia'], identidades],
                                             sort_keys=True).encode())

    def preparar(carga):
        return staging, {'linhas': {tabela: len(linhas) for tabela, linhas in staging.items()}}

    def transferir(cursor, dados, somente_conferir=False):
        transferir_dia(cursor, dados, publicacao['data_referencia'], somente_conferir)

    return executar_carga_postgres(conexao, carga_id, preparar=preparar,
                                   transferir=transferir, reutilizar=True,
                                   identidade_origem=identidade_origem)


def executar_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifesto', required=True)
    args = parser.parse_args()
    try:
        carregar_publicacao(args.manifesto)
        parametros = configuracao_postgres()
        with certificado_postgres() as certificado:
            with psycopg.connect(**parametros, sslrootcert=certificado) as conexao:
                resultado = publicar_diario(conexao, args.manifesto)
    except (psycopg.Error, OSError, ValueError, KeyError, TypeError, ArithmeticError):
        print('Publicacao diaria interrompida; conferir configuracao e reconciliar antes de repetir.')
        return 2
    print(json.dumps(resultado))
    return 0


if __name__ == '__main__':
    raise SystemExit(executar_cli())
