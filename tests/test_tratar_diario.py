import csv
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import alimentar_datalake as lake
import tratar_diario as diario


class CenarioDiario:
    def __init__(self, raiz):
        self.raiz = raiz
        self.data = '2020-01-02'
        self.produtos = [dict(produto_id=produto, produto=produto, categoria='Teste',
                              preco_lista='30', custo_padrao='10') for produto in ('P1', 'P2')]
        self.metas = [dict(ano_mes='2020-01', canal='ecommerce' if unidade == 'ecommerce' else 'loja_fisica',
                          unidade_id=identidade[0], meta_receita_liquida='300', meta_pedidos='10',
                          meta_ticket_medio='30', meta_margem_bruta_pct='60', meta_taxa_devolucao_pct='2',
                          inicio_operacao='2019-01-01') for unidade, identidade in lake.UNIDADES.items()]
        self.referencias()

    def csv(self, linhas, campos=None):
        texto = io.StringIO()
        escritor = csv.DictWriter(texto, fieldnames=campos or list(linhas[0]), delimiter=';')
        escritor.writeheader()
        escritor.writerows(linhas)
        return texto.getvalue().encode()

    def referencias(self):
        pasta = self.raiz / 'config'
        pasta.mkdir(exist_ok=True)
        fontes = []
        for nome, linhas in (('produtos', self.produtos), ('metas_mensais', self.metas)):
            relativo = 'data/reference/' + nome + '.csv'
            destino = self.raiz / relativo
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(self.csv(linhas))
            fontes.append(dict(name=nome, path=relativo, type='csv'))
        (pasta / 'data_sources.json').write_text(json.dumps({'data_sources': fontes}))

    def vendas(self, unidade='barbacena', data=None):
        return [dict(id_venda=unidade + '-V1', data_venda=data or self.data, hora_venda='10:00:00',
                     cliente_id='demonstrativo', produto_id='P1', quantidade=1, valor_bruto='30',
                     valor_desconto='0', valor_liquido='30', custo_total='10', margem_bruta='20',
                     status_pedido='concluida', canal='ecommerce' if unidade == 'ecommerce' else 'loja_fisica',
                     loja_id=lake.UNIDADES[unidade][0], pedido_online_id=unidade + '-P1')]

    def receber(self, unidade='barbacena', carga='recebimento', linhas=None, data=None):
        data = data or self.data
        linhas = self.vendas(unidade, data) if linhas is None else linhas
        pasta = self.raiz / 'data/inbox' / unidade / data
        pasta.mkdir(parents=True, exist_ok=True)
        nome = lake.UNIDADES[unidade][1]
        conteudo = (json.dumps({'records': linhas}).encode() if nome.endswith('.json')
                    else self.csv(linhas, list(self.vendas(unidade)[0])))
        (pasta / nome).write_bytes(conteudo)
        recibo = dict(unidade_id=lake.UNIDADES[unidade][0], data_referencia=data,
                      registros=len(linhas), sem_movimento=not linhas, sha256=sha256(conteudo).hexdigest())
        (pasta / 'recebimento.json').write_text(json.dumps(recibo))
        return lake.receber_unidade(unidade, data, carga, self.raiz)

    def tratar(self, unidade='barbacena', carga='tratamento', recebimento='recebimento', data=None):
        return diario.tratar_unidade(unidade, data or self.data, recebimento, carga, self.raiz)

    def completo(self, carga='completo', zeros=False, data=None):
        selecao = {}
        for unidade in lake.UNIDADES:
            self.receber(unidade, carga, [] if zeros else None, data)
            resultado = self.tratar(unidade, carga, carga, data)
            if resultado['status'] not in {'aprovado', 'reutilizado'}:
                raise AssertionError(resultado)
            selecao[unidade] = resultado['manifesto']
        return diario.consolidar_dia(data or self.data, selecao, carga, self.raiz)


class TratamentoDiarioTest(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory(prefix='xfit-diario-')
        self.addCleanup(pasta.cleanup)
        self.raiz = Path(pasta.name).resolve()
        self.cenario = CenarioDiario(self.raiz)

    def test_td01_ausente_preserva_duas_unidades_sem_publicacao_parcial(self):
        selecao = {}
        for unidade in lake.UNIDADES:
            if unidade != 'barbacena':
                self.cenario.receber(unidade)
            else:
                lake.receber_unidade(unidade, self.cenario.data, 'recebimento', self.raiz)
            resultado = self.cenario.tratar(unidade)
            selecao[unidade] = resultado['manifesto']
            self.assertEqual(resultado['status'], 'pendente' if unidade == 'barbacena' else 'aprovado')
        with self.assertRaises(ValueError):
            diario.consolidar_dia(self.cenario.data, selecao, 'parcial', self.raiz)
        self.assertFalse((self.raiz / diario.BASE / 'publicacoes').exists())

    def test_td02_zero_explicito_sem_venda_artificial(self):
        self.cenario.receber(linhas=[])
        resultado = self.cenario.tratar()
        manifesto, staging = diario.ler_lote_aprovado(resultado['manifesto'], self.raiz)
        self.assertTrue(manifesto['sem_movimento'])
        self.assertEqual(staging['stg_vendas'], [])

    def test_td03_zero_nao_declarado_reprovado(self):
        relatorio = self.cenario.receber(linhas=[])
        pasta = self.raiz / relatorio['destino']
        recibo = json.loads((pasta / 'recebimento.json').read_text())
        recibo['sem_movimento'] = False
        (pasta / 'recebimento.json').write_text(json.dumps(recibo))
        self.assertEqual(self.cenario.tratar()['status'], 'reprovado')

    def test_td04_td06_varios_produtos_por_pedido_e_decimal_exato(self):
        linhas = self.cenario.vendas()
        linhas.append(dict(linhas[0], produto_id='P2'))
        linhas.append(dict(linhas[0], id_venda='outro'))
        self.cenario.receber(linhas=linhas)
        resultado = self.cenario.tratar()
        manifesto, staging = diario.ler_lote_aprovado(resultado['manifesto'], self.raiz)
        self.assertEqual(manifesto['linhas_saida'], 3)
        self.assertEqual(len({venda['id_venda'] for venda in staging['stg_vendas']}), 2)
        self.assertEqual(sum(venda['valor_liquido'] for venda in staging['stg_vendas']), Decimal('90'))
        self.assertIsInstance(staging['stg_vendas'][0]['valor_liquido'], Decimal)

    def test_td05_duplicacao_reprova_inteiro(self):
        linhas = self.cenario.vendas() * 2
        self.cenario.receber(linhas=linhas)
        self.assertEqual(self.cenario.tratar()['status'], 'reprovado')

    def test_td07_margem_acima_da_tolerancia(self):
        linhas = self.cenario.vendas()
        linhas[0]['margem_bruta'] = '20.03'
        self.cenario.receber(linhas=linhas)
        self.assertEqual(self.cenario.tratar()['status'], 'reprovado')

    def test_td08_materialidade_nao_aceita_centavos_acumulados(self):
        linhas = [dict(self.cenario.vendas()[0], id_venda='V' + str(indice),
                       valor_bruto='10', valor_liquido='10', margem_bruta='0.01') for indice in range(100)]
        linhas[0]['margem_bruta'] = '0.02'
        self.cenario.receber(linhas=linhas)
        self.assertEqual(self.cenario.tratar()['status'], 'reprovado')

    def test_td09_repeticao_reutiliza_e_preserva_original(self):
        self.cenario.receber()
        original = self.cenario.tratar()
        antes = (self.raiz / original['manifesto']).read_bytes()
        self.cenario.receber(carga='segunda')
        repetida = self.cenario.tratar(carga='segunda', recebimento='segunda')
        self.assertEqual(repetida['status'], 'reutilizado')
        self.assertEqual((self.raiz / original['manifesto']).read_bytes(), antes)
        self.assertEqual(len(diario.ler_lote_aprovado(repetida['manifesto'], self.raiz)[1]['stg_vendas']), 1)

    def test_td10_omissao_nao_apaga_anterior(self):
        self.cenario.receber()
        original = self.cenario.tratar()
        self.cenario.receber(carga='correcao', linhas=[])
        resultado = self.cenario.tratar(carga='correcao', recebimento='correcao')
        self.assertEqual(resultado['status'], 'revisao_necessaria')
        self.assertEqual(len(diario.ler_lote_aprovado(original['manifesto'], self.raiz)[1]['stg_vendas']), 1)

    def test_td11_referencia_nova_exige_revisao(self):
        self.cenario.receber()
        self.cenario.tratar()
        self.cenario.produtos[0]['produto'] = 'Cadastro atualizado'
        self.cenario.referencias()
        resultado = self.cenario.tratar(carga='referencia-nova')
        self.assertEqual(resultado['status'], 'revisao_necessaria')

    def test_td12_hash_bruto_e_saida_alterados_bloqueiam(self):
        relatorio = self.cenario.receber()
        (self.raiz / relatorio['destino'] / 'vendas.csv').write_text('alterado')
        self.assertEqual(self.cenario.tratar()['status'], 'reprovado')
        self.cenario.receber(carga='nova')
        resultado = self.cenario.tratar(carga='nova', recebimento='nova')
        (self.raiz / resultado['manifesto']).parent.joinpath('stg_vendas.jsonl').write_text('')
        with self.assertRaisesRegex(ValueError, 'alterada'):
            diario.ler_lote_aprovado(resultado['manifesto'], self.raiz)

    def test_td13_interrupcao_antes_do_manifesto_nao_publica(self):
        self.cenario.receber()
        with patch.object(diario, 'gravar_json', side_effect=OSError('falha simulada')):
            with self.assertRaises(OSError):
                self.cenario.tratar()
        relativo = diario.BASE / 'barbacena' / self.cenario.data / 'tratamento/manifesto.json'
        self.assertFalse((self.raiz / relativo).exists())
        with self.assertRaises(ValueError):
            diario.ler_lote_aprovado(relativo, self.raiz)
        self.assertEqual(self.cenario.tratar(carga='recuperacao')['status'], 'aprovado')

    def test_td14_dia_completo_com_uma_unidade_zero(self):
        selecao = {}
        for unidade in lake.UNIDADES:
            self.cenario.receber(unidade, linhas=[] if unidade == 'ecommerce' else None)
            selecao[unidade] = self.cenario.tratar(unidade)['manifesto']
        manifesto = diario.consolidar_dia(self.cenario.data, selecao, 'publicacao', self.raiz)
        self.assertEqual(len(diario.carregar_publicacao(manifesto, self.raiz)[1]['stg_vendas']), 2)

    def test_td15_data_futura_e_recibo_de_outra_unidade(self):
        with self.assertRaises(ValueError):
            self.cenario.tratar(data='2999-01-01')
        relatorio = self.cenario.receber()
        pasta = self.raiz / relatorio['destino']
        recibo = json.loads((pasta / 'recebimento.json').read_text())
        recibo['unidade_id'] = 'LJ-CL'
        (pasta / 'recebimento.json').write_text(json.dumps(recibo))
        self.assertEqual(self.cenario.tratar()['status'], 'reprovado')

    def test_td16_numeros_invalidos_nao_sao_normalizados_silenciosamente(self):
        for indice, (campo, valor) in enumerate([('quantidade', True), ('quantidade', '1.5'),
                                               ('valor_liquido', 'NaN'), ('custo_total', 'Infinity')]):
            with self.subTest(campo=campo, valor=valor):
                linhas = self.cenario.vendas('ecommerce')
                linhas[0][campo] = valor
                carga = 'invalido-' + str(indice)
                self.cenario.receber('ecommerce', carga=carga, linhas=linhas)
                self.assertEqual(self.cenario.tratar('ecommerce', carga=carga, recebimento=carga)['status'], 'reprovado')

    def test_td17_cadastro_meta_ausentes_e_duplicados(self):
        for indice, tipo in enumerate(('produto', 'meta', 'duplicado')):
            with self.subTest(tipo=tipo):
                linhas = self.cenario.vendas()
                if tipo == 'produto':
                    linhas[0]['produto_id'] = 'ausente'
                elif tipo == 'meta':
                    self.cenario.metas = self.cenario.metas[1:]
                else:
                    self.cenario.produtos.append(deepcopy(self.cenario.produtos[0]))
                self.cenario.referencias()
                carga = 'sem-cadastro-' + str(indice)
                self.cenario.receber(carga=carga, linhas=linhas)
                self.assertEqual(self.cenario.tratar(carga=carga, recebimento=carga)['status'], 'reprovado')

    def test_td18_traversal_e_symlink_bloqueados(self):
        self.cenario.receber()
        with self.assertRaises(ValueError):
            self.cenario.tratar(carga='../fora')
        origem = self.raiz / 'data/reference/produtos.csv'
        copia = origem.with_suffix('.copia')
        origem.rename(copia)
        try:
            origem.symlink_to(copia)
        except OSError:
            self.skipTest('Symlink nao permitido no Windows')
        self.assertEqual(self.cenario.tratar()['status'], 'reprovado')

    def test_td19_tres_zeros_formam_dia_completo(self):
        manifesto = self.cenario.completo(zeros=True)
        self.assertEqual(diario.carregar_publicacao(manifesto, self.raiz)[1]['stg_vendas'], [])

    def test_td20_pedido_reaparecendo_em_outro_dia_exige_revisao(self):
        self.cenario.receber()
        self.cenario.tratar()
        self.cenario.receber(carga='outro-dia', data='2020-01-03')
        self.assertEqual(self.cenario.tratar(carga='outro-dia', recebimento='outro-dia',
                                           data='2020-01-03')['status'], 'revisao_necessaria')

    def test_referencias_incompativeis_e_selecao_de_outra_data_bloqueiam(self):
        selecao = {}
        for unidade in lake.UNIDADES:
            self.cenario.produtos[0]['produto'] += '-novo'
            self.cenario.referencias()
            self.cenario.receber(unidade)
            selecao[unidade] = self.cenario.tratar(unidade)['manifesto']
        with self.assertRaises(ValueError):
            diario.consolidar_dia(self.cenario.data, selecao, 'incompativel', self.raiz)
        with self.assertRaises(ValueError):
            diario.consolidar_dia('2020-01-03', selecao, 'outra-data', self.raiz)

    def test_pasta_e_id_exclusivos_e_bloqueio_de_concorrencia(self):
        self.cenario.receber()
        original = self.cenario.tratar()
        with self.assertRaises(FileExistsError):
            self.cenario.tratar()
        with diario.bloquear_tratamento('barbacena', self.raiz):
            with self.assertRaises(FileExistsError):
                self.cenario.tratar(carga='concorrente')
        self.assertEqual(diario.ler_lote_aprovado(original['manifesto'], self.raiz)[0]['status'], 'aprovado')


if __name__ == '__main__':
    unittest.main()
