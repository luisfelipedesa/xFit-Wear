from datetime import date, timedelta
from pathlib import Path
import textwrap
import unittest
from unittest.mock import MagicMock, patch


class DisponibilidadeSupabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (Path(__file__).resolve().parents[1] /
                        '.github/workflows/supabase-disponibilidade.yml').read_text(encoding='utf-8')
        bloco = textwrap.dedent(cls.workflow.split('        run: |\n', 1)[1])
        cls.codigo = bloco.split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        cls.modulo = {'__name__': 'workflow_disponibilidade'}
        exec(compile(cls.codigo, '<workflow_disponibilidade>', 'exec'), cls.modulo)

    def test_intervalo_exato_de_cinco_dias_inclusive_virada_de_mes(self):
        inicio = date(2026, 10, 18)
        dias = [inicio + timedelta(days=indice) for indice in range(400)]
        selecionados = [dia for dia in dias if self.modulo['deve_consultar'](dia, 'schedule')]
        self.assertTrue(all((depois - antes).days == 5 for antes, depois in zip(selecionados, selecionados[1:])))
        self.assertFalse(self.modulo['deve_consultar'](inicio - timedelta(days=1), 'schedule'))

    def test_manual_independe_do_intervalo(self):
        self.assertTrue(self.modulo['deve_consultar'](date(2026, 10, 19), 'workflow_dispatch'))

    def test_apenas_chave_publicavel_e_destino_exato(self):
        for url, chave in [('https://outro.example', 'sb_publishable_teste'),
                           ('https://hnjeknbdgvkzfdwrupau.supabase.co', 'service_role'),
                           ('http://hnjeknbdgvkzfdwrupau.supabase.co', 'sb_publishable_teste')]:
            with self.assertRaises(ValueError):
                self.modulo['consultar_supabase'](url, chave)

    def test_chamada_confere_resultado_e_nao_segue_redirecionamento(self):
        resposta = MagicMock(status=200)
        resposta.read.return_value = b'1'
        cliente = MagicMock()
        cliente.open.return_value.__enter__.return_value = resposta
        with patch('urllib.request.build_opener', return_value=cliente):
            self.modulo['consultar_supabase']('https://hnjeknbdgvkzfdwrupau.supabase.co', 'sb_publishable_teste')
            request = cliente.open.call_args.args[0]
            self.assertEqual(request.data, b'{}')
            self.assertEqual(cliente.open.call_args.kwargs['timeout'], 20)
            resposta.read.return_value = b'0'
            with self.assertRaises(ValueError):
                self.modulo['consultar_supabase']('https://hnjeknbdgvkzfdwrupau.supabase.co', 'sb_publishable_teste')
        self.assertIsNone(self.modulo['SemRedirecionamento']().redirect_request(None, None, 302, '', {}, 'https://outro.example'))

    def test_workflow_nao_recebe_segredos_nem_permissoes_de_escrita(self):
        self.assertIn('permissions: {}', self.workflow)
        self.assertNotIn('secrets.', self.workflow)
        self.assertNotIn('uses:', self.workflow)
        self.assertIn("cron: '17 10 * * *'", self.workflow)


if __name__ == '__main__':
    unittest.main()
