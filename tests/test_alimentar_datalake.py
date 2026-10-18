import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import alimentar_datalake as lake


class AlimentacaoPorUnidadeTest(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory(prefix='xfit-entregas-')
        self.addCleanup(pasta.cleanup)
        self.raiz = Path(pasta.name).resolve()
        self.data = '2026-07-31'

    def entregar(self, unidade, registros=None, sem_movimento=False, data=None):
        data = data or self.data
        unidade_id, nome = lake.UNIDADES[unidade]
        pasta = self.raiz / 'data/inbox' / unidade / data
        pasta.mkdir(parents=True)
        if registros is None:
            registros = [] if sem_movimento else [
                {'data_venda': data, 'loja_id': unidade_id,
                 'canal': 'ecommerce' if unidade == 'ecommerce' else 'loja_fisica'}]
        if nome.endswith('.json'):
            conteudo = json.dumps({'records': registros}).encode()
        else:
            texto = io.StringIO()
            escritor = csv.DictWriter(texto, fieldnames=['data_venda', 'loja_id', 'canal'], delimiter=';')
            escritor.writeheader()
            escritor.writerows(registros)
            conteudo = texto.getvalue().encode()
        (pasta / nome).write_bytes(conteudo)
        recibo = {'unidade_id': unidade_id, 'data_referencia': data,
                  'registros': len(registros), 'sem_movimento': sem_movimento,
                  'sha256': sha256(conteudo).hexdigest()}
        (pasta / 'recebimento.json').write_text(json.dumps(recibo), encoding='utf-8')
        return pasta

    def test_unidade_ausente_nao_bloqueia_as_demais_e_resumo_sinaliza(self):
        self.entregar('lafaiete')
        self.entregar('ecommerce')
        resultados = [lake.receber_unidade(unidade, self.data, 'parcial', self.raiz)
                      for unidade in lake.UNIDADES]
        self.assertEqual([resultado['status'] for resultado in resultados],
                         ['ausente', 'recebida', 'recebida'])
        resumo = lake.resumir_alimentacao('parcial', self.data, self.raiz)
        self.assertEqual(resumo['status'], 'pendente')
        for resultado in resultados[1:]:
            destino = self.raiz / resultado['destino']
            self.assertTrue((destino / 'recebimento.json').is_file())
            nome = lake.UNIDADES[resultado['unidade']][1]
            self.assertEqual(sha256((destino / nome).read_bytes()).hexdigest(), resultado['sha256'])

    def test_sem_movimento_exige_entrega_explicita_e_nao_vira_ausencia(self):
        self.entregar('barbacena', sem_movimento=True)
        self.assertEqual(lake.receber_unidade('barbacena', self.data, 'zero', self.raiz)['status'],
                         'sem_movimento')

    def test_arquivo_antigo_nao_comprova_entrega_da_data(self):
        self.entregar('barbacena', data='2026-07-30')
        self.assertEqual(lake.receber_unidade('barbacena', self.data, 'atraso', self.raiz)['status'],
                         'ausente')

    def test_hash_data_e_unidade_divergentes_sao_rejeitados(self):
        for unidade, registro in [('barbacena', {'data_venda': '2026-07-30', 'loja_id': 'LJ-BQ', 'canal': 'loja_fisica'}),
                                 ('lafaiete', {'data_venda': self.data, 'loja_id': 'LJ-BQ', 'canal': 'loja_fisica'})]:
            self.entregar(unidade, registros=[registro])
            self.assertEqual(lake.receber_unidade(unidade, self.data, 'invalido', self.raiz)['status'], 'erro')
        pasta = self.entregar('ecommerce')
        (pasta / 'vendas.json').write_text('{"records": []}', encoding='utf-8')
        self.assertEqual(lake.receber_unidade('ecommerce', self.data, 'invalido', self.raiz)['status'], 'erro')
        self.assertFalse((self.raiz / 'data/raw/recebimentos').exists())

    def test_repeticao_nao_sobrescreve_entrega_confirmada(self):
        self.entregar('barbacena')
        resultado = lake.receber_unidade('barbacena', self.data, 'unica', self.raiz)
        antes = (self.raiz / resultado['destino'] / 'vendas.csv').read_bytes()
        with self.assertRaises(FileExistsError):
            lake.receber_unidade('barbacena', self.data, 'unica', self.raiz)
        self.assertEqual((self.raiz / resultado['destino'] / 'vendas.csv').read_bytes(), antes)

    def test_traversal_e_data_fora_do_contrato_nao_escrevem(self):
        for unidade, data, carga in [('barbacena', self.data, '../fora'),
                                     ('../fora', self.data, 'valida'),
                                     ('barbacena', '20260731', 'valida')]:
            with self.assertRaises(ValueError):
                lake.receber_unidade(unidade, data, carga, self.raiz)
        self.assertFalse((self.raiz / 'data').exists())


if __name__ == '__main__':
    unittest.main()
