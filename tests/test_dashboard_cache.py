"""Cache real do Streamlit com banco simulado e relógio controlado."""

from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import MagicMock, patch

from streamlit import cache_data

from dashboard import dados


class CacheDashboardTest(unittest.TestCase):
    def setUp(self):
        self.relogio = 1000.0
        # O storage captura o timer ao nascer; recriar evita esperar cinco minutos.
        timer = patch('streamlit.runtime.caching.cache_utils.TTLCACHE_TIMER',
                      new=lambda: self.relogio)
        timer.start()
        self.addCleanup(timer.stop)
        cache_data.clear()
        self.addCleanup(cache_data.clear)
        self.config = {'host': 'banco-teste', 'password': 'segredo-ficticio'}
        configurar = patch.object(dados, 'configuracao_banco', side_effect=lambda: self.config.copy())
        configurar.start()
        self.addCleanup(configurar.stop)
        conectar = patch.object(dados, 'conectar')
        self.conectar = conectar.start()
        self.addCleanup(conectar.stop)
        self.conexao = MagicMock()
        self.conectar.return_value.__enter__.return_value = self.conexao
        self.conexao.execute.return_value.fetchone.return_value = {'ultima_data_venda': date(2026, 9, 30)}
        self.conexao.execute.return_value.fetchall.return_value = [
            {'categoria': 'Camisetas', 'receita_liquida_concluida': Decimal('123.45')}]
        self.inicio, self.fim = date(2026, 9, 1), date(2026, 9, 30)

    def painel(self, **filtros):
        parametros = dict(inicio=self.inicio, fim=self.fim,
                          unidades=['A', 'B'], canais=['loja', 'web'], categoria=None)
        parametros.update(filtros)
        return dados.carregar_painel(**parametros)

    def test_repetir_contexto_e_painel_executa_seis_consultas_uma_vez(self):
        contexto = dados.carregar_contexto()
        painel = self.painel()
        self.assertEqual(dados.carregar_contexto(), contexto)
        self.assertEqual(self.painel(), painel)
        self.assertEqual(self.conectar.call_count, 2)
        self.assertEqual(self.conexao.execute.call_count, 6)
        self.assertEqual(painel[0][0]['receita_liquida_concluida'], Decimal('123.45'))

    def test_ordem_e_duplicatas_das_selecoes_reutilizam_resultado(self):
        original = self.painel()
        self.assertEqual(self.painel(unidades=['B', 'A', 'A'], canais=['web', 'loja']), original)
        self.conectar.assert_called_once()

    def test_cada_filtro_diferente_consulta_o_banco(self):
        self.painel()
        for filtro in ({'inicio': date(2026, 9, 2)}, {'fim': date(2026, 9, 29)},
                       {'unidades': ['A']}, {'canais': ['web']}, {'categoria': 'Camisetas'}):
            with self.subTest(filtro=filtro):
                self.painel(**filtro)
        self.assertEqual(self.conectar.call_count, 6)

    def test_troca_de_origem_ou_credencial_nao_reutiliza_resultado(self):
        for campo in ('host', 'password'):
            with self.subTest(campo=campo):
                dados.carregar_contexto()
                self.painel()
                antes = self.conectar.call_count
                self.config[campo] += '-novo'
                dados.carregar_contexto()
                self.painel()
                self.assertEqual(self.conectar.call_count, antes + 2)

    def test_configuracao_invalida_bloqueia_mesmo_com_cache_aquecido(self):
        dados.carregar_contexto()
        self.painel()
        with patch.object(dados, 'configuracao_banco', side_effect=dados.ConfiguracaoInvalida):
            with self.assertRaises(dados.ConfiguracaoInvalida):
                dados.carregar_contexto()
            with self.assertRaises(dados.ConfiguracaoInvalida):
                self.painel()
        self.assertEqual(self.conectar.call_count, 2)

    def test_resultado_mutavel_nao_contamina_proximo_consumidor(self):
        contexto = dados.carregar_contexto()
        painel = self.painel()
        contexto[2].append('Alterada')
        painel[0][0]['receita_liquida_concluida'] = 0
        self.assertEqual(dados.carregar_contexto()[2], ['Camisetas'])
        self.assertEqual(self.painel()[0][0]['receita_liquida_concluida'], Decimal('123.45'))

    def test_expiracao_renova_contexto_e_painel_na_proxima_consulta(self):
        dados.carregar_contexto()
        self.painel()
        self.relogio += 299
        dados.carregar_contexto()
        self.painel()
        self.assertEqual(self.conectar.call_count, 2)
        self.relogio += 2
        dados.carregar_contexto()
        self.painel()
        self.assertEqual(self.conectar.call_count, 4)

    def test_falha_nao_e_armazenada_e_proxima_tentativa_consulta(self):
        self.conexao.execute.side_effect = dados.psycopg.OperationalError('falha simulada')
        for carregar in (dados.carregar_contexto, self.painel):
            with self.subTest(carregar=carregar.__name__):
                with self.assertRaises(dados.psycopg.OperationalError):
                    carregar()
        self.conexao.execute.side_effect = None
        dados.carregar_contexto()
        self.painel()
        self.assertEqual(self.conectar.call_count, 4)

    def test_limite_de_entradas_descarta_filtro_antigo(self):
        for indice in range(129):
            self.painel(categoria=f'Categoria {indice}')
        self.painel(categoria='Categoria 128')
        self.assertEqual(self.conectar.call_count, 129)
        self.painel(categoria='Categoria 0')
        self.assertEqual(self.conectar.call_count, 130)
