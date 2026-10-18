"""Tratamento de entregas confirmadas e selecao completa para publicacao diaria."""

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import io
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from alimentar_datalake import (
    RAIZ, UNIDADES, caminho_local, conferir_data_referencia, conferir_entrega,
)
from data_lake_audit import validar_formato_id_carga
from source_contract import carregar_contrato_fontes
from staging_data import padronizar_meta, padronizar_produto, padronizar_venda
from validate_staging import (
    validar_arredondamento_agregado, validar_cobertura_mensal,
    validar_identidade_itens_vendidos, validar_produtos, validar_unidades_e_metas,
    validar_valores,
)

VERSAO = '1'
FONTES = {'barbacena': 'vendas_barbacena', 'lafaiete': 'vendas_conselheiro_lafaiete',
          'ecommerce': 'vendas_ecommerce'}
BASE = Path('data/processed/staging_diaria')
CAMPOS_DECIMAIS = {
    'stg_vendas': ('valor_bruto', 'valor_desconto', 'valor_liquido', 'custo_total', 'margem_bruta'),
    'stg_produtos': ('preco_lista', 'custo_padrao'),
    'stg_metas': ('meta_receita_liquida', 'meta_ticket_medio', 'meta_margem_bruta_pct',
                  'meta_taxa_devolucao_pct'),
}


def assinatura(conteudo):
    return sha256(conteudo).hexdigest()


def ler_arquivo_local(relativo, raiz):
    caminho = caminho_local(Path(relativo), raiz)
    if not caminho.is_file() or caminho.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Arquivo irregular ou acima do limite')
    return caminho.read_bytes()


def ler_json_local(relativo, raiz):
    return json.loads(ler_arquivo_local(relativo, raiz))


def gravar_json(caminho, documento):
    with caminho.open('x', encoding='utf-8') as arquivo:
        json.dump(documento, arquivo, ensure_ascii=False, indent=2, default=str, allow_nan=False)


@contextmanager
def bloquear_tratamento(unidade, raiz):
    destino = caminho_local(BASE / 'bloqueios' / (unidade + '.lock'), raiz)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open('x', encoding='utf-8'):
        try:
            yield
        finally:
            destino.unlink()


def carregar_referencias(raiz):
    contrato = carregar_contrato_fontes(raiz / 'config/data_sources.json')
    referencias = {}
    staging = {}
    for fonte, tabela, padronizar in (
            ('produtos', 'stg_produtos', padronizar_produto),
            ('metas_mensais', 'stg_metas', padronizar_meta)):
        opcoes = [item for item in contrato['data_sources'] if item['name'] == fonte]
        if len(opcoes) != 1 or Path(opcoes[0]['path']).is_absolute():
            raise ValueError('Referencia ausente ou ambigua')
        conteudo = ler_arquivo_local(opcoes[0]['path'], raiz)
        linhas = list(csv.DictReader(io.StringIO(conteudo.decode('utf-8-sig')), delimiter=';'))
        if not linhas:
            raise ValueError('Referencia vazia')
        staging[tabela] = [padronizar(linha) for linha in linhas]
        referencias[fonte] = {'path': opcoes[0]['path'], 'sha256': assinatura(conteudo),
                              'conteudo': conteudo}
    return staging, referencias


def ler_recebimento(unidade, data, carga_recebimento, raiz):
    validar_formato_id_carga(carga_recebimento)
    relatorio = ler_json_local(
        Path('data/processed/manifests/alimentacao') / carga_recebimento / (unidade + '.json'), raiz)
    pasta = Path('data/raw/recebimentos') / unidade / data / carga_recebimento
    if (relatorio.get('unidade') != unidade or relatorio.get('data_referencia') != data
            or relatorio.get('carga_id') != carga_recebimento):
        raise ValueError('Relatorio de outro recebimento')
    if relatorio.get('status') == 'ausente':
        return None
    if relatorio.get('status') not in {'recebida', 'sem_movimento'}:
        raise ValueError('Recebimento nao confirmado')
    if relatorio.get('destino') != pasta.as_posix():
        raise ValueError('Destino de recebimento divergente')
    ler_arquivo_local(pasta / 'recebimento.json', raiz)
    ler_arquivo_local(pasta / UNIDADES[unidade][1], raiz)
    recibo, conteudo, hash_bruto, nome = conferir_entrega(pasta, unidade, data, raiz)
    esperado = 'sem_movimento' if recibo['sem_movimento'] else 'recebida'
    if (relatorio['status'] != esperado or relatorio.get('sha256') != hash_bruto
            or relatorio.get('registros') != recibo['registros']):
        raise ValueError('Relatorio e recibo divergentes')
    if nome.endswith('.json'):
        linhas = json.loads(conteudo, parse_float=Decimal)['records']
    else:
        linhas = list(csv.DictReader(io.StringIO(conteudo.decode('utf-8-sig')), delimiter=';'))
    return recibo, linhas, hash_bruto, pasta / nome


def validar_lote_diario(vendas, produtos, metas, unidade, data):
    unidade_id = UNIDADES[unidade][0]
    canal = 'ecommerce' if unidade == 'ecommerce' else 'loja_fisica'
    if any(venda['unidade_id'] != unidade_id or venda['data_venda'] != data
           or venda['canal'] != canal for venda in vendas):
        raise ValueError('Venda de outra unidade ou data')
    if any(not isinstance(venda[campo], str) or not venda[campo].strip()
           for venda in vendas for campo in ('id_venda', 'cliente_id', 'produto_id')):
        raise ValueError('Identidade de venda invalida')
    if unidade == 'ecommerce' and any(not venda['pedido_online_id'] for venda in vendas):
        raise ValueError('Pedido online obrigatorio')
    chaves_metas = [(meta['unidade_id'], meta['ano_mes']) for meta in metas]
    if any(total > 1 for total in Counter(chaves_metas).values()):
        raise ValueError('Meta duplicada')
    canais_unidades = {identidade[0]: 'ecommerce' if nome == 'ecommerce' else 'loja_fisica'
                       for nome, identidade in UNIDADES.items()}
    if any(canais_unidades.get(meta['unidade_id']) != meta['canal'] for meta in metas):
        raise ValueError('Referencia de unidade/canal invalida')
    if not any(meta['unidade_id'] == unidade_id and meta['ano_mes'] == data[:7]
               and meta['canal'] == canal for meta in metas):
        raise ValueError('Meta mensal da unidade ausente')
    checks = [validar_identidade_itens_vendidos(vendas), validar_produtos(vendas, produtos),
              validar_unidades_e_metas(vendas, metas), validar_cobertura_mensal(vendas, metas),
              validar_valores(vendas, produtos, metas), validar_arredondamento_agregado(vendas)]
    if any(check['erros'] for check in checks):
        raise ValueError('Lote diario reprovado por regra de qualidade')
    return [{'nome': check['nome'], 'status': check['status']} for check in checks]


def ler_lote_aprovado(relativo, raiz=RAIZ):
    relativo = Path(relativo)
    manifesto = ler_json_local(relativo, raiz)
    if manifesto.get('status') == 'reutilizado':
        validar_formato_id_carga(manifesto['carga_id'])
        conferir_data_referencia(manifesto['data_referencia'])
        if (manifesto.get('versao') != VERSAO or manifesto.get('unidade') not in UNIDADES
                or relativo != BASE / manifesto['unidade'] / manifesto['data_referencia']
                / manifesto['carga_id'] / 'manifesto.json'):
            raise ValueError('Manifesto de reutilizacao fora do contrato')
        original = ler_json_local(manifesto['aprovacao'], raiz)
        if any(original.get(campo) != manifesto.get(campo)
               for campo in ('unidade', 'data_referencia', 'identidade')):
            raise ValueError('Reutilizacao divergente')
        relativo = Path(manifesto['aprovacao'])
        manifesto = original
    unidade = manifesto['unidade']
    data = conferir_data_referencia(manifesto['data_referencia'])
    validar_formato_id_carga(manifesto['carga_id'])
    esperado = BASE / unidade / data / manifesto['carga_id'] / 'manifesto.json'
    if (unidade not in UNIDADES or relativo != esperado or manifesto['status'] != 'aprovado'
            or manifesto['versao'] != VERSAO):
        raise ValueError('Manifesto nao aprovado ou fora do contrato')
    staging = {}
    for tabela in CAMPOS_DECIMAIS:
        conteudo = ler_arquivo_local(relativo.parent / (tabela + '.jsonl'), raiz)
        if assinatura(conteudo) != manifesto['arquivos'][tabela]:
            raise ValueError('Staging alterada apos aprovacao')
        staging[tabela] = [json.loads(linha) for linha in conteudo.decode('utf-8').splitlines()]
        for linha in staging[tabela]:
            for campo in CAMPOS_DECIMAIS[tabela]:
                linha[campo] = Decimal(linha[campo])
    for fonte, referencia in manifesto['referencias'].items():
        conteudo = ler_arquivo_local(relativo.parent / (fonte + '.csv'), raiz)
        if assinatura(conteudo) != referencia['sha256']:
            raise ValueError('Snapshot de referencia alterado')
    if len(staging['stg_vendas']) != manifesto['linhas_saida']:
        raise ValueError('Volume de staging divergente')
    return manifesto, staging


def conferir_aprovacoes_anteriores(unidade, data, identidade, vendas, raiz):
    pasta = caminho_local(BASE / unidade, raiz)
    acumuladas = list(vendas)
    for caminho in sorted(pasta.glob('*/*/manifesto.json')):
        relativo = caminho.relative_to(raiz)
        anterior = ler_json_local(relativo, raiz)
        if anterior.get('status') != 'aprovado':
            continue
        anterior, staging = ler_lote_aprovado(relativo, raiz)
        if anterior['data_referencia'] == data:
            if anterior['identidade'] == identidade:
                return relativo.as_posix()
            raise ValueError('revisao_necessaria')
        pedidos = {(venda['fonte'], venda['id_venda']) for venda in staging['stg_vendas']}
        if any((venda['fonte'], venda['id_venda']) in pedidos for venda in vendas):
            raise ValueError('revisao_necessaria')
        acumuladas.extend(staging['stg_vendas'])
    if validar_arredondamento_agregado(acumuladas)['erros']:
        raise ValueError('Materialidade acumulada dos lotes diarios reprovada')
    return None


def tratar_unidade(unidade, data, carga_recebimento, carga_id, raiz=RAIZ):
    raiz = raiz.resolve()
    validar_formato_id_carga(carga_id)
    conferir_data_referencia(data)
    if unidade not in UNIDADES:
        raise ValueError('Unidade desconhecida')
    if data > datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat():
        raise ValueError('Data futura bloqueada')
    pasta = caminho_local(BASE / unidade / data / carga_id, raiz)
    with bloquear_tratamento(unidade, raiz):
        pasta.mkdir(parents=True, exist_ok=False)
        manifesto = {'unidade': unidade, 'data_referencia': data, 'carga_id': carga_id,
                     'carga_recebimento': carga_recebimento, 'versao': VERSAO,
                     'status': 'reprovado'}
        try:
            entrega = ler_recebimento(unidade, data, carga_recebimento, raiz)
            if entrega is None:
                manifesto['status'] = 'pendente'
            else:
                recibo, linhas, hash_bruto, origem = entrega
                staging, referencias = carregar_referencias(raiz)
                staging['stg_vendas'] = [padronizar_venda(FONTES[unidade], linha) for linha in linhas]
                checks = validar_lote_diario(staging['stg_vendas'], staging['stg_produtos'],
                                            staging['stg_metas'], unidade, data)
                hashes = {fonte: referencia['sha256'] for fonte, referencia in referencias.items()}
                identidade = assinatura(json.dumps([unidade, data, hash_bruto, hashes, VERSAO],
                                                   sort_keys=True).encode())
                manifesto.update(identidade=identidade, origem=origem.as_posix(), sha256=hash_bruto,
                                 referencias={fonte: {'path': ref['path'], 'sha256': ref['sha256']}
                                              for fonte, ref in referencias.items()},
                                 linhas_entrada=recibo['registros'], linhas_saida=len(linhas),
                                 sem_movimento=recibo['sem_movimento'], checks=checks,
                                 valor_liquido=str(sum((venda['valor_liquido']
                                                       for venda in staging['stg_vendas']), Decimal(0))))
                anterior = conferir_aprovacoes_anteriores(unidade, data, identidade,
                                                         staging['stg_vendas'], raiz)
                if anterior:
                    manifesto.update(status='reutilizado', aprovacao=anterior)
                else:
                    manifesto['arquivos'] = {}
                    for fonte, referencia in referencias.items():
                        with (pasta / (fonte + '.csv')).open('xb') as arquivo:
                            arquivo.write(referencia['conteudo'])
                    for tabela, registros in staging.items():
                        conteudo = ''.join(json.dumps(linha, default=str, ensure_ascii=False,
                                                     allow_nan=False) + '\n' for linha in registros).encode()
                        with (pasta / (tabela + '.jsonl')).open('xb') as arquivo:
                            arquivo.write(conteudo)
                        if assinatura((pasta / (tabela + '.jsonl')).read_bytes()) != assinatura(conteudo):
                            raise ValueError('Escrita de staging divergente')
                        manifesto['arquivos'][tabela] = assinatura(conteudo)
                    if assinatura(ler_arquivo_local(origem, raiz)) != hash_bruto:
                        raise ValueError('Recebimento alterado durante o tratamento')
                    manifesto['status'] = 'aprovado'
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError) as erro:
            manifesto['status'] = 'revisao_necessaria' if str(erro) == 'revisao_necessaria' else 'reprovado'
            manifesto['mensagem'] = 'Tratamento bloqueado; conferir contrato e artefatos protegidos'
        gravar_json(pasta / 'manifesto.json', manifesto)
    return {'status': manifesto['status'], 'manifesto': (pasta / 'manifesto.json').relative_to(raiz).as_posix()}


def consolidar_dia(data, selecao, carga_id, raiz=RAIZ):
    validar_formato_id_carga(carga_id)
    conferir_data_referencia(data)
    if set(selecao) != set(UNIDADES):
        raise ValueError('Publicacao exige selecao explicita das tres unidades')
    staging = {'stg_vendas': []}
    referencias = None
    for unidade in UNIDADES:
        manifesto, lote = ler_lote_aprovado(selecao[unidade], raiz)
        if manifesto['unidade'] != unidade or manifesto['data_referencia'] != data:
            raise ValueError('Lote selecionado de outra unidade ou data')
        hashes = {fonte: ref['sha256'] for fonte, ref in manifesto['referencias'].items()}
        if referencias is not None and hashes != referencias:
            raise ValueError('Unidades com referencias incompativeis')
        referencias = hashes
        staging['stg_vendas'].extend(lote['stg_vendas'])
        staging.update({tabela: lote[tabela] for tabela in ('stg_produtos', 'stg_metas')})
    if validar_arredondamento_agregado(staging['stg_vendas'])['erros']:
        raise ValueError('Materialidade global da data reprovada')
    pasta = caminho_local(BASE / 'publicacoes' / carga_id, raiz)
    pasta.mkdir(parents=True, exist_ok=False)
    publicacao = {'status': 'aprovado', 'data_referencia': data, 'carga_id': carga_id,
                  'versao': VERSAO, 'selecao': selecao, 'referencias': referencias}
    gravar_json(pasta / 'manifesto.json', publicacao)
    return (pasta / 'manifesto.json').relative_to(raiz).as_posix()


def carregar_publicacao(relativo, raiz=RAIZ):
    publicacao = ler_json_local(relativo, raiz)
    validar_formato_id_carga(publicacao['carga_id'])
    if (Path(relativo) != BASE / 'publicacoes' / publicacao['carga_id'] / 'manifesto.json'
            or publicacao['status'] != 'aprovado' or publicacao['versao'] != VERSAO
            or set(publicacao['selecao']) != set(UNIDADES)):
        raise ValueError('Publicacao nao aprovada')
    staging = {'stg_vendas': []}
    for unidade, caminho in publicacao['selecao'].items():
        manifesto, lote = ler_lote_aprovado(caminho, raiz)
        if (manifesto['unidade'] != unidade or manifesto['data_referencia'] != publicacao['data_referencia']
                or {fonte: ref['sha256'] for fonte, ref in manifesto['referencias'].items()}
                != publicacao['referencias']):
            raise ValueError('Selecao de publicacao divergente')
        staging['stg_vendas'].extend(lote['stg_vendas'])
        staging.update({tabela: lote[tabela] for tabela in ('stg_produtos', 'stg_metas')})
    return publicacao, staging


def executar_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-referencia', required=True)
    parser.add_argument('--carga-id', required=True)
    parser.add_argument('--unidade', choices=UNIDADES)
    parser.add_argument('--carga-recebimento')
    parser.add_argument('--selecao')
    args = parser.parse_args()
    try:
        if args.unidade:
            resultado = tratar_unidade(args.unidade, args.data_referencia,
                                       args.carga_recebimento, args.carga_id)
        else:
            caminho = consolidar_dia(args.data_referencia, json.loads(args.selecao), args.carga_id)
            resultado = {'status': 'aprovado', 'manifesto': caminho}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError):
        print('Tratamento interrompido; conferir selecao e artefatos locais.')
        return 2
    print(json.dumps(resultado))
    return 0 if resultado['status'] in {'aprovado', 'reutilizado'} else 1


if __name__ == '__main__':
    raise SystemExit(executar_cli())
