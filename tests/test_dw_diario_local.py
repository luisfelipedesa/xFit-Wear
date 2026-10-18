"""Pipeline diario real em PostgreSQL descartavel, sem credenciais do projeto."""

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import psycopg

import test_dw_local as base
from test_tratar_diario import CenarioDiario
import carregar_diario_postgres as diario
import carregar_postgres as carga
import tratar_diario as tratamento


@unittest.skipUnless(os.environ.get('XFIT_TEST_DW_LOCAL') == '1', 'Postgres descartavel nao solicitado')
class DWDiarioLocalTest(unittest.TestCase):
    setUpClass = classmethod(base.ProtecoesDWLocalTest.setUpClass.__func__)
    tearDownClass = classmethod(base.ProtecoesDWLocalTest.tearDownClass.__func__)

    def setUp(self):
        base.ProtecoesDWLocalTest.setUp(self)
        pasta = tempfile.TemporaryDirectory(prefix='xfit-dw-diario-')
        self.addCleanup(pasta.cleanup)
        self.raiz = Path(pasta.name).resolve()
        self.cenario = CenarioDiario(self.raiz)

    def publicar(self, manifesto):
        with patch.object(carga, 'conferir_papel_conexao'), patch.object(carga, 'registrar_status_local'):
            return diario.publicar_diario(self.conexao, manifesto, self.raiz)

    def resumo(self):
        return self.conexao.execute('select count(*), coalesce(sum(valor_liquido),0) from dw.fato_vendas').fetchone()

    def test_lake_tratamento_dw_e_repeticao_sem_duplicacao(self):
        manifesto = self.cenario.completo()
        self.assertEqual(self.publicar(manifesto)['status'], 'sucesso')
        self.assertEqual(self.resumo(), (3, 90))
        self.assertEqual(self.publicar(manifesto)['status'], 'reutilizado')
        repetido = self.cenario.completo(carga='repetido')
        self.assertEqual(self.publicar(repetido)['status'], 'reutilizado')
        self.assertEqual(self.resumo(), (3, 90))
        self.assertEqual(self.conexao.execute('select count(*) from etl.cargas_dw').fetchone(), (1,))

    def test_data_nova_preserva_historico_e_pedido_conflitante_bloqueia(self):
        self.publicar(self.cenario.completo())
        original = self.cenario.vendas

        def vendas_novas(unidade='barbacena', data=None):
            return [dict(linha, id_venda=linha['id_venda'] + '-novo') for linha in original(unidade, data)]

        with patch.object(self.cenario, 'vendas', side_effect=vendas_novas):
            manifesto = self.cenario.completo(carga='dia-novo', data='2020-01-03')
        self.publicar(manifesto)
        self.assertEqual(self.resumo(), (6, 180))
        publicacao, staging = tratamento.carregar_publicacao(manifesto, self.raiz)
        staging['stg_vendas'][0]['id_venda'] = original()[0]['id_venda']
        with self.assertRaisesRegex(ValueError, 'revisao_necessaria'):
            with self.conexao.transaction():
                diario.transferir_dia(self.conexao.cursor(), staging, '2020-01-03')
        self.assertEqual(self.resumo(), (6, 180))

    def test_correcao_sem_aprovacao_local_nao_substitui_dia_no_banco(self):
        self.publicar(self.cenario.completo())
        with tempfile.TemporaryDirectory() as pasta:
            outro = CenarioDiario(Path(pasta).resolve())
            outro.produtos[0]['produto'] = 'Alterado'
            outro.referencias()
            manifesto = outro.completo()
            with patch.object(carga, 'conferir_papel_conexao'), patch.object(carga, 'registrar_status_local'):
                with self.assertRaisesRegex(ValueError, 'outra identidade'):
                    diario.publicar_diario(self.conexao, manifesto, outro.raiz)
        self.assertEqual(self.resumo(), (3, 90))

    def test_dia_zero_inicial_publica_referencias_sem_criar_vendas(self):
        manifesto = self.cenario.completo(zeros=True)
        self.publicar(manifesto)
        self.assertEqual(self.resumo(), (0, 0))
        self.assertEqual(self.conexao.execute('select count(*) from dw.dim_produto').fetchone(), (2,))
        self.assertEqual(self.conexao.execute('select count(*) from dw.dim_unidade').fetchone(), (3,))
        self.assertEqual(self.conexao.execute('select count(*) from dw.fato_metas').fetchone(), (3,))
        self.assertEqual(self.publicar(manifesto)['status'], 'reutilizado')

    def test_dia_zero_apos_vendas_preserva_dia_anterior(self):
        self.publicar(self.cenario.completo())
        manifesto = self.cenario.completo(carga='dia-zero', zeros=True, data='2020-01-03')
        self.publicar(manifesto)
        self.assertEqual(self.resumo(), (3, 90))

    def test_omissao_de_item_historico_bloqueia_antes_da_promocao(self):
        manifesto = self.cenario.completo()
        self.publicar(manifesto)
        publicacao, staging = tratamento.carregar_publicacao(manifesto, self.raiz)
        staging['stg_vendas'] = staging['stg_vendas'][:2]
        with self.assertRaisesRegex(ValueError, 'omite itens'):
            with self.conexao.transaction():
                diario.transferir_dia(self.conexao.cursor(), staging, publicacao['data_referencia'])
        self.assertEqual(self.resumo(), (3, 90))

    def test_falha_apos_promocao_reverte_inclusive_staging(self):
        manifesto = self.cenario.completo()
        promover = carga.promover_dw_postgres

        def promover_e_falhar(cursor, carga_id):
            promover(cursor, carga_id)
            raise ValueError('falha simulada')

        with patch.object(carga, 'promover_dw_postgres', side_effect=promover_e_falhar):
            with self.assertRaisesRegex(ValueError, 'falha simulada'):
                self.publicar(manifesto)
        self.assertEqual(self.resumo(), (0, 0))
        self.assertEqual(self.conexao.execute('select count(*) from stg.stg_vendas').fetchone(), (0,))
        self.assertEqual(self.conexao.execute('select status from etl.cargas_dw').fetchone(), ('erro',))
        with self.assertRaisesRegex(ValueError, 'reconciliacao'):
            self.publicar(manifesto)

    def test_repeticao_confere_dw_nao_apenas_historico_de_sucesso(self):
        manifesto = self.cenario.completo()
        self.publicar(manifesto)
        self.conexao.execute('update dw.fato_vendas set valor_liquido=valor_liquido+1')
        with self.assertRaisesRegex(psycopg.errors.RaiseException, 'Reconciliacao'):
            self.publicar(manifesto)
        self.assertEqual(self.conexao.execute('select status from etl.cargas_dw').fetchone(), ('sucesso',))

    def test_precisao_na_transferencia_e_conteudo_corrompido_bloqueiam(self):
        manifesto = self.cenario.completo()
        original = diario.conferir_diferencas

        def corromper(cursor, consulta, mensagem):
            if mensagem.startswith('Transferencia'):
                cursor.execute('update stg.stg_vendas set valor_liquido=valor_liquido+1')
            original(cursor, consulta, mensagem)

        with patch.object(diario, 'conferir_diferencas', side_effect=corromper):
            with self.assertRaisesRegex(ValueError, 'Transferencia'):
                self.publicar(manifesto)
        self.assertEqual(self.resumo(), (0, 0))

    def test_colunas_com_precisao_excedente_nao_sofrem_arredondamento_silencioso(self):
        manifesto = self.cenario.completo()
        publicacao, staging = tratamento.carregar_publicacao(manifesto, self.raiz)
        from decimal import Decimal
        staging = deepcopy(staging)
        staging['stg_vendas'][0]['valor_bruto'] = Decimal('30.001')
        with self.assertRaisesRegex(ValueError, 'precisao'):
            with self.conexao.transaction():
                diario.transferir_dia(self.conexao.cursor(), staging, publicacao['data_referencia'])
        self.assertEqual(self.resumo(), (0, 0))


if __name__ == '__main__':
    unittest.main()
