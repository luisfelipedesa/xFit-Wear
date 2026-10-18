import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import validar_carga_airflow as fluxo


class ValidarCargaAirflowTest(unittest.TestCase):
    def test_reprovacao_bloqueia_execucao_sem_expor_detalhe(self):
        saida = io.StringIO()
        with patch.object(sys, 'argv', ['validar', '--carga-id', 'airflow-teste']), \
             patch.object(fluxo, 'preparar_staging_aprovada',
                          side_effect=ValueError('identificador-privado')), \
             contextlib.redirect_stdout(saida):
            self.assertEqual(fluxo.executar_cli(), 2)
        self.assertNotIn('identificador-privado', saida.getvalue())

    def test_identificador_invalido_nao_cria_snapshot(self):
        with patch.object(sys, 'argv', ['validar', '--carga-id', '../invalido']), \
             patch.object(fluxo, 'preparar_staging_aprovada') as preparar, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fluxo.executar_cli(), 2)
            preparar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
