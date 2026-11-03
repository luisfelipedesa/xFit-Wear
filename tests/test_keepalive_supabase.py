from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import textwrap
import unittest
import socket
import ssl
import urllib.error
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

    def executar_main(self, consulta, evento='schedule', relogio=None):
        ambiente = {'SUPABASE_URL': 'https://hnjeknbdgvkzfdwrupau.supabase.co',
                    'SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_NAO_EXIBIR', 'EVENTO': evento}
        saida = io.StringIO()
        substituicoes = {'consultar_supabase': consulta}
        if relogio is not None:
            substituicoes['datetime'] = relogio
        with patch.dict(self.modulo, substituicoes), patch.dict(os.environ, ambiente, clear=True), redirect_stdout(saida):
            resultado = self.modulo['main']()
        return resultado, saida.getvalue()

    def test_toda_execucao_consulta_inclusive_dias_antes_ignorados(self):
        for evento in ('schedule', 'workflow_dispatch'):
            for dia in ('2026-10-19', '2026-10-31', '2026-11-01', '2026-11-02'):
                with self.subTest(evento=evento, dia=dia):
                    relogio = MagicMock()
                    relogio.now.return_value = datetime.fromisoformat(dia).replace(tzinfo=timezone.utc)
                    consultar = MagicMock()
                    resultado, saida = self.executar_main(consultar, evento, relogio)
                    self.assertEqual(resultado, 0)
                    consultar.assert_called_once()
                    self.assertIn('HTTP 200', saida)
                    self.assertNotIn('sb_publishable_NAO_EXIBIR', saida)

    def test_logs_distinguem_status_http_sem_expor_corpo_ou_chave(self):
        for status, orientacao in ((401, 'chave'), (403, 'permiss'), (404, 'RPC'),
                                   (429, 'limite'), (503, 'pausado'), (302, 'redirecionamento')):
            with self.subTest(status=status):
                erro = urllib.error.HTTPError('https://NAO_EXIBIR', status, 'NAO_EXIBIR', {}, io.BytesIO(b'NAO_EXIBIR'))
                resultado, saida = self.executar_main(MagicMock(side_effect=erro))
                self.assertEqual(resultado, 1)
                self.assertIn('::error::', saida)
                self.assertIn(f'HTTP {status}', saida)
                self.assertIn(orientacao, saida)
                self.assertNotIn('NAO_EXIBIR', saida)

    def test_logs_distinguem_rede_tls_dns_timeout_e_resposta_invalida(self):
        casos = [(urllib.error.URLError(socket.gaierror('NAO_EXIBIR')), 'DNS'),
                 (urllib.error.URLError(ssl.SSLError('NAO_EXIBIR')), 'TLS'),
                 (urllib.error.URLError(TimeoutError('NAO_EXIBIR')), 'tempo'),
                 (TimeoutError('NAO_EXIBIR'), 'tempo'),
                 (urllib.error.URLError(OSError('NAO_EXIBIR')), 'rede'),
                 (OSError('NAO_EXIBIR'), 'rede'),
                 (ValueError('NAO_EXIBIR'), 'configuracao'),
                 (RuntimeError('NAO_EXIBIR'), 'resposta')]
        for erro, orientacao in casos:
            with self.subTest(erro=type(erro).__name__, orientacao=orientacao):
                resultado, saida = self.executar_main(MagicMock(side_effect=erro))
                self.assertEqual(resultado, 1)
                self.assertIn('::error::', saida)
                self.assertIn(orientacao, saida)
                self.assertNotIn('NAO_EXIBIR', saida)

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
            with self.assertRaises(RuntimeError):
                self.modulo['consultar_supabase']('https://hnjeknbdgvkzfdwrupau.supabase.co', 'sb_publishable_teste')
        self.assertIsNone(self.modulo['SemRedirecionamento']().redirect_request(None, None, 302, '', {}, 'https://outro.example'))

    def test_workflow_nao_recebe_segredos_nem_permissoes_de_escrita(self):
        self.assertIn('permissions: {}', self.workflow)
        self.assertNotIn('secrets.', self.workflow)
        self.assertNotIn('uses:', self.workflow)
        self.assertIn("cron: '17 10 * * *'", self.workflow)


if __name__ == '__main__':
    unittest.main()
