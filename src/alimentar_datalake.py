"""Recebe entregas locais por unidade/data e registra pendencias independentes."""

import argparse
import csv
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import io
from pathlib import Path

from data_lake_audit import validar_formato_id_carga

RAIZ = Path(__file__).resolve().parents[1]
UNIDADES = {'barbacena': ('LJ-BQ', 'vendas.csv'),
            'lafaiete': ('LJ-CL', 'vendas.csv'),
            'ecommerce': ('EC-BR', 'vendas.json')}


def caminho_local(relativo, raiz):
    caminho = raiz / relativo
    if caminho.absolute() != caminho.resolve() or raiz.resolve() not in caminho.resolve().parents:
        raise ValueError('Caminho de entrega redirecionado ou fora do projeto')
    return caminho


def conferir_data_referencia(valor):
    if not isinstance(valor, str) or date.fromisoformat(valor).isoformat() != valor:
        raise ValueError('Data de referencia deve usar YYYY-MM-DD')
    return valor


def conferir_entrega(pasta, unidade, data_referencia, raiz):
    recibo = json.loads(caminho_local(pasta / 'recebimento.json', raiz).read_text(encoding='utf-8'))
    unidade_id, nome_arquivo = UNIDADES[unidade]
    if recibo.get('unidade_id') != unidade_id or recibo.get('data_referencia') != data_referencia:
        raise ValueError('Recibo de outra unidade ou data')
    quantidade = recibo.get('registros')
    sem_movimento = recibo.get('sem_movimento')
    if type(quantidade) is not int or quantidade < 0 or type(sem_movimento) is not bool:
        raise ValueError('Recibo sem volume e declaracao de movimento validos')
    if sem_movimento != (quantidade == 0):
        raise ValueError('Declaracao de movimento diverge do volume')
    origem = caminho_local(pasta / nome_arquivo, raiz)
    if origem.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Entrega excede o limite local de 128 MiB')
    conteudo = origem.read_bytes()
    assinatura = sha256(conteudo).hexdigest()
    if recibo.get('sha256') != assinatura:
        raise ValueError('Entrega incompleta ou divergente do recibo')
    if nome_arquivo.endswith('.csv'):
        leitor = csv.DictReader(io.StringIO(conteudo.decode('utf-8-sig')), delimiter=';')
        if not {'data_venda', 'loja_id', 'canal'}.issubset(leitor.fieldnames or []):
            raise ValueError('Entrega sem colunas de unidade/data')
        registros = list(leitor)
    else:
        registros = json.loads(conteudo).get('records')
    if not isinstance(registros, list) or len(registros) != quantidade:
        raise ValueError('Quantidade recebida diverge do recibo')
    for registro in registros:
        if not isinstance(registro, dict) or registro.get('data_venda') != data_referencia:
            raise ValueError('Registro fora da data declarada')
        if unidade == 'ecommerce':
            if registro.get('canal') != 'ecommerce':
                raise ValueError('Registro fora da unidade declarada')
        elif registro.get('loja_id') != unidade_id or registro.get('canal') != 'loja_fisica':
            raise ValueError('Registro fora da unidade declarada')
    return recibo, conteudo, assinatura, nome_arquivo


def receber_unidade(unidade, data_referencia, carga_id, raiz=RAIZ):
    validar_formato_id_carga(carga_id)
    conferir_data_referencia(data_referencia)
    if unidade not in UNIDADES:
        raise ValueError('Unidade desconhecida')
    raiz = raiz.resolve()
    relatorio = {'unidade': unidade, 'data_referencia': data_referencia,
                 'carga_id': carga_id, 'status': 'ausente',
                 'verificado_em': datetime.now(timezone.utc).isoformat()}
    destino_relatorio = caminho_local(
        Path('data/processed/manifests/alimentacao') / carga_id / f'{unidade}.json', raiz)
    destino_relatorio.parent.mkdir(parents=True, exist_ok=True)
    with destino_relatorio.open('x', encoding='utf-8') as arquivo_relatorio:
        pasta = Path('data/inbox') / unidade / data_referencia
        try:
            recibo, conteudo, assinatura, nome_arquivo = conferir_entrega(
                pasta, unidade, data_referencia, raiz)
            destino = caminho_local(
                Path('data/raw/recebimentos') / unidade / data_referencia / carga_id, raiz)
            destino.mkdir(parents=True, exist_ok=False)
            with (destino / nome_arquivo).open('xb') as arquivo:
                arquivo.write(conteudo)
            if sha256((destino / nome_arquivo).read_bytes()).hexdigest() != assinatura:
                raise ValueError('Copia recebida diverge do recibo')
            with (destino / 'recebimento.json').open('x', encoding='utf-8') as arquivo:
                json.dump(recibo, arquivo)
            relatorio.update(status='sem_movimento' if recibo['sem_movimento'] else 'recebida',
                             registros=recibo['registros'], sha256=assinatura,
                             destino=destino.relative_to(raiz).as_posix())
        except FileNotFoundError:
            relatorio['mensagem'] = 'Entrega da unidade/data nao encontrada'
        except (OSError, ValueError, TypeError, AttributeError) as erro:
            relatorio.update(status='erro', mensagem=f'Entrega rejeitada ({type(erro).__name__})')
        json.dump(relatorio, arquivo_relatorio, indent=2)
    return relatorio


def resumir_alimentacao(carga_id, data_referencia, raiz=RAIZ):
    validar_formato_id_carga(carga_id)
    conferir_data_referencia(data_referencia)
    unidades = {}
    for unidade in UNIDADES:
        caminho = caminho_local(
            Path('data/processed/manifests/alimentacao') / carga_id / f'{unidade}.json', raiz)
        try:
            relatorio = json.loads(caminho.read_text(encoding='utf-8'))
            if relatorio['carga_id'] != carga_id or relatorio['data_referencia'] != data_referencia:
                raise ValueError('Relatorio de outra carga')
            unidades[unidade] = relatorio['status']
        except (OSError, ValueError, KeyError, TypeError):
            unidades[unidade] = 'erro'
    return {'carga_id': carga_id, 'data_referencia': data_referencia, 'unidades': unidades,
            'status': 'sucesso' if all(status in {'recebida', 'sem_movimento'}
                                      for status in unidades.values()) else 'pendente'}


def executar_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--carga-id', required=True)
    parser.add_argument('--data-referencia', required=True)
    parser.add_argument('--unidade', choices=UNIDADES)
    args = parser.parse_args()
    try:
        resultado = (receber_unidade(args.unidade, args.data_referencia, args.carga_id)
                     if args.unidade else resumir_alimentacao(args.carga_id, args.data_referencia))
    except (OSError, ValueError, TypeError) as erro:
        print(f'Alimentacao interrompida ({type(erro).__name__}); conferir recibos locais.')
        return 2
    print(json.dumps(resultado, indent=2))
    return 0 if resultado['status'] in {'recebida', 'sem_movimento', 'sucesso'} else 1


if __name__ == '__main__':
    raise SystemExit(executar_cli())
