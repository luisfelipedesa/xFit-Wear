"""Cache real do Streamlit com banco simulado e relógio controlado."""

from datetime import date
from decimal import Decimal
from copy import deepcopy
import unittest
from unittest.mock import MagicMock, patch

from streamlit import cache_resource

from dashboard import dados


class CacheDashboardTest(unittest.TestCase):
    def setUp(self):
        self.relogio = 1000.0
        # O storage captura o timer ao nascer; recriar evita esperar cinco minutos.
        timer = patch('streamlit.runtime.caching.cache_utils.TTLCACHE_TIMER',
                      new=lambda: self.relogio)
        timer.start()
        self.addCleanup(timer.stop)
        cache_resource.clear()
        self.addCleanup(cache_resource.clear)
        self.config = {'host': 'banco-teste', 'password': 'segredo-ficticio'}
        configurar = patch.object(dados, 'configuracao_banco', side_effect=lambda: self.config.copy())
        configurar.start()
        self.addCleanup(configurar.stop)
        conectar = patch.object(dados, 'conectar')
        self.conectar = conectar.start()
        self.addCleanup(conectar.stop)
        self.conexao = MagicMock()
        self.conectar.return_value.__enter__.return_value = self.conexao
        self.vendas = [
            {'data_venda': date(2026, 9, 1), 'ano_mes': '2026-09', 'unidade_id': 'A',
             'unidade': 'Loja A', 'canal': 'loja', 'receita_liquida_concluida': Decimal('123.45'), 'pedidos_concluidos': 1},
            {'data_venda': date(2026, 9, 2), 'ano_mes': '2026-09', 'unidade_id': 'B',
             'unidade': 'Loja B', 'canal': 'web', 'receita_liquida_concluida': Decimal('50'), 'pedidos_concluidos': 1}]
        self.categorias = [dict(self.vendas[0], categoria='Camisetas', receita_liquida_concluida=Decimal('100')),
                           dict(self.vendas[0], categoria='Calcas', receita_liquida_concluida=Decimal('23.45')),
                           dict(self.vendas[1], categoria='Camisetas')]
        self.mensais = [dict(linha, meta_receita_liquida=Decimal('300')) for linha in self.vendas]
        self.mensais.append(dict(self.mensais[0], ano_mes='2026-12', tem_registros_vendas=False))
        self.conexao.execute.side_effect = self.executar_consulta
        self.inicio, self.fim = date(2026, 9, 1), date(2026, 9, 30)

    def executar_consulta(self, sql):
        cursor = MagicMock()
        if 'vw_atualizacao' in sql:
            cursor.fetchone.return_value = {'ultima_data_venda': date(2026, 9, 2)}
        elif 'vw_vendas_diarias_categoria' in sql:
            cursor.fetchall.return_value = deepcopy(self.categorias)
        elif 'vw_vendas_diarias' in sql:
            cursor.fetchall.return_value = deepcopy(self.vendas)
        elif 'vw_desempenho_mensal' in sql:
            cursor.fetchall.return_value = deepcopy(self.mensais)
        else:
            raise AssertionError('Consulta inesperada')
        return cursor

    def painel(self, **filtros):
        parametros = dict(inicio=self.inicio, fim=self.fim,
                          unidades=['A', 'B'], canais=['loja', 'web'], categoria=None)
        parametros.update(filtros)
        return dados.carregar_painel(**parametros)

    def test_contexto_e_todos_os_filtros_compartilham_quatro_consultas(self):
        contexto = dados.carregar_contexto()
        painel = self.painel()
        self.assertEqual(dados.carregar_contexto(), contexto)
        self.assertEqual(self.painel(), painel)
        self.assertEqual(self.conectar.call_count, 1)
        self.assertEqual(self.conexao.execute.call_count, 4)
        self.assertEqual(painel[0][0]['receita_liquida_concluida'], Decimal('123.45'))

    def test_ordem_e_duplicatas_das_selecoes_reutilizam_resultado(self):
        original = self.painel()
        self.assertEqual(self.painel(unidades=['B', 'A', 'A'], canais=['web', 'loja']), original)
        self.conectar.assert_called_once()

    def test_filtros_novos_nao_abrem_conexao_nem_executam_sql(self):
        self.painel()
        for filtro in ({'inicio': date(2026, 9, 2)}, {'fim': date(2026, 9, 29)},
                       {'unidades': ['A']}, {'canais': ['web']}, {'categoria': 'Camisetas'}):
            with self.subTest(filtro=filtro):
                self.painel(**filtro)
        self.assertEqual(self.conectar.call_count, 1)
        self.assertEqual(self.conexao.execute.call_count, 4)

    def test_filtro_preserva_datas_canal_unidade_categoria_e_pedidos_nao_aditivos(self):
        vendas, mix, _ = self.painel()
        self.assertEqual(sum(v['pedidos_concluidos'] for v in vendas), 2)
        self.assertEqual(sum(v['receita_liquida_concluida'] for v in mix), Decimal('173.45'))
        vendas, mix, _ = self.painel(categoria='Camisetas', unidades=['A'], canais=['loja'])
        self.assertEqual(sum(v['pedidos_concluidos'] for v in vendas), 1)
        self.assertEqual(mix, [{'categoria': 'Camisetas', 'receita_liquida_concluida': Decimal('100')}])
        self.assertEqual(self.painel(inicio=date(2026, 9, 2))[0], [self.vendas[1]])
        self.assertEqual(self.painel(fim=date(2026, 9, 1))[0], [self.vendas[0]])
        self.assertEqual(self.painel(unidades=[]), ([], [], []))
        self.assertEqual(self.painel(canais=[]), ([], [], []))
        self.assertEqual(self.painel(categoria='Inexistente')[:2], ([], []))

    def test_meta_futura_permanece_no_ano_e_contexto_nao_depende_do_filtro(self):
        contexto = dados.carregar_contexto()
        self.assertEqual([u['ultima_data_disponivel'] for u in contexto[1]],
                         [date(2026, 9, 1), date(2026, 9, 2)])
        _, _, mensais = self.painel(inicio=date(2026, 1, 1), fim=date(2026, 12, 31))
        self.assertEqual(len(mensais), 3)
        self.assertEqual(sum(m['meta_receita_liquida'] for m in mensais), Decimal('900'))
        self.painel(categoria='Camisetas', unidades=['A'])
        self.assertEqual(dados.carregar_contexto(), contexto)

    def test_troca_de_origem_ou_credencial_nao_reutiliza_resultado(self):
        for campo in ('host', 'password'):
            with self.subTest(campo=campo):
                dados.carregar_contexto()
                self.painel()
                antes = self.conectar.call_count
                self.config[campo] += '-novo'
                dados.carregar_contexto()
                self.painel()
                self.assertEqual(self.conectar.call_count, antes + 1)

    def test_configuracao_invalida_bloqueia_mesmo_com_cache_aquecido(self):
        dados.carregar_contexto()
        self.painel()
        with patch.object(dados, 'configuracao_banco', side_effect=dados.ConfiguracaoInvalida):
            with self.assertRaises(dados.ConfiguracaoInvalida):
                dados.carregar_contexto()
            with self.assertRaises(dados.ConfiguracaoInvalida):
                self.painel()
        self.assertEqual(self.conectar.call_count, 1)

    def test_resultado_mutavel_nao_contamina_proximo_consumidor(self):
        contexto = dados.carregar_contexto()
        painel = self.painel()
        contexto[2].append('Alterada')
        painel[0][0]['receita_liquida_concluida'] = 0
        self.assertEqual(dados.carregar_contexto()[2], ['Calcas', 'Camisetas'])
        self.assertEqual(self.painel()[0][0]['receita_liquida_concluida'], Decimal('123.45'))

    def test_base_compartilhada_e_imutavel_inclusive_linhas_e_contexto(self):
        base = dados.carregar_base()
        self.assertIs(dados.carregar_base(), base)
        for destino, campo in ((base, 'vendas'), (base['vendas'][0], 'canal'),
                               (base['contexto'][0], 'ultima_data_venda'),
                               (base['contexto'][1][0], 'unidade')):
            with self.subTest(campo=campo), self.assertRaises(TypeError):
                destino[campo] = 'alterado'
        self.assertIsInstance(base['categorias'], tuple)
        self.assertIsInstance(base['contexto'][2], tuple)

    def test_expiracao_renova_contexto_e_painel_na_proxima_consulta(self):
        dados.carregar_contexto()
        self.painel()
        self.relogio += 299
        dados.carregar_contexto()
        self.painel()
        self.assertEqual(self.conectar.call_count, 1)
        self.relogio += 2
        dados.carregar_contexto()
        self.painel()
        self.assertEqual(self.conectar.call_count, 2)

    def test_falha_nao_e_armazenada_e_proxima_tentativa_consulta(self):
        self.conexao.execute.side_effect = dados.psycopg.OperationalError('falha simulada')
        for carregar in (dados.carregar_contexto, self.painel):
            with self.subTest(carregar=carregar.__name__):
                with self.assertRaises(dados.psycopg.OperationalError):
                    carregar()
        self.conexao.execute.side_effect = self.executar_consulta
        dados.carregar_contexto()
        self.painel()
        self.assertEqual(self.conectar.call_count, 3)

    def test_falha_no_meio_da_carga_nao_publica_base_parcial(self):
        def consultar_com_falha(sql):
            if 'vw_vendas_diarias_categoria' in sql:
                raise dados.psycopg.OperationalError('falha simulada')
            return self.executar_consulta(sql)
        self.conexao.execute.side_effect = consultar_com_falha
        with self.assertRaises(dados.psycopg.OperationalError):
            dados.carregar_base()
        self.conexao.execute.side_effect = self.executar_consulta
        self.assertEqual(len(dados.carregar_base()['categorias']), 3)
        self.assertEqual(self.conectar.call_count, 2)

    def test_limite_de_entradas_descarta_base_de_configuracao_antiga(self):
        for indice in range(3):
            self.config['host'] = f'banco-{indice}'
            self.painel()
        self.painel()
        self.assertEqual(self.conectar.call_count, 3)
        self.config['host'] = 'banco-0'
        self.painel()
        self.assertEqual(self.conectar.call_count, 4)
