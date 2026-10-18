from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from test_tratar_diario import CenarioDiario

try:
    from airflow.models import DagBag
except ModuleNotFoundError:
    DagBag = None


@unittest.skipIf(DagBag is None, 'Executar na imagem xfit-airflow')
class FluxosAirflowTest(unittest.TestCase):
    def test_tasks_diarias_executam_cli_real_sem_acessar_dw(self):
        raiz_projeto = Path(__file__).resolve().parents[1]
        fluxos = DagBag(dag_folder=str(raiz_projeto / 'airflow/dags'))
        fluxo = fluxos.dags['xfit_pipeline_diario']
        with tempfile.TemporaryDirectory(prefix='xfit-airflow-diario-') as pasta:
            raiz = Path(pasta).resolve()
            cenario = CenarioDiario(raiz)
            shutil.copytree(raiz_projeto / 'src', raiz / 'src', ignore=shutil.ignore_patterns('__pycache__'))
            for unidade in ('barbacena', 'lafaiete', 'ecommerce'):
                cenario.receber(unidade)
            params = {'data_referencia': cenario.data, 'recebimentos': {}, 'publicar_dw': False}
            receber = fluxo.get_task('receber_barbacena').python_callable
            with patch.dict(receber.__globals__, RAIZ=raiz,
                            get_current_context=lambda: {'params': params}):
                selecao = {}
                for unidade in ('barbacena', 'lafaiete', 'ecommerce'):
                    recebimento = fluxo.get_task('receber_' + unidade).python_callable('dag-teste', unidade)
                    selecao[unidade] = fluxo.get_task('tratar_' + unidade).python_callable('dag-teste', recebimento, unidade)
                manifesto = fluxo.get_task('aprovar_dia').python_callable('dag-teste', selecao)
                resultado = fluxo.get_task('publicar_dia').python_callable(manifesto)
                self.assertEqual(resultado['status'], 'validado_sem_publicacao')
                self.assertTrue((raiz / manifesto).is_file())
                params['recebimentos'] = {'barbacena': 'recebimento'}
                self.assertEqual(receber('outro-run', 'barbacena'), 'recebimento')

    def test_fluxos_importam_e_bloqueiam_carga_apos_falha(self):
        pasta = Path(__file__).resolve().parents[1] / 'airflow' / 'dags'
        if not pasta.exists():
            pasta = Path('/opt/airflow/dags')
        fluxos = DagBag(dag_folder=str(pasta))
        self.assertEqual(fluxos.import_errors, {})
        self.assertEqual(set(fluxos.dags), {'xfit_validar_fontes', 'xfit_carga_dw',
                                          'xfit_alimentar_datalake', 'xfit_pipeline_diario'})
        for fluxo in fluxos.dags.values():
            self.assertIsNone(fluxo.schedule)
            self.assertEqual(fluxo.max_active_runs, 1)
            self.assertTrue(all(tarefa.retries == 0 for tarefa in fluxo.tasks))
        carga = fluxos.dags['xfit_carga_dw'].get_task('executar_pipeline')
        self.assertEqual(carga.trigger_rule, 'all_success')
        self.assertEqual(carga.upstream_task_ids, {'identificar_carga', 'verificar_conexao'})
        lake = fluxos.dags['xfit_alimentar_datalake']
        for unidade in ('barbacena', 'lafaiete', 'ecommerce'):
            self.assertEqual(lake.get_task('receber_' + unidade).upstream_task_ids, {'identificar_carga'})
        self.assertEqual(lake.get_task('resumir_alimentacao').trigger_rule, 'all_done')
        diario = fluxos.dags['xfit_pipeline_diario']
        for unidade in ('barbacena', 'lafaiete', 'ecommerce'):
            self.assertEqual(diario.get_task('receber_' + unidade).upstream_task_ids, {'identificar_carga'})
            self.assertEqual(diario.get_task('tratar_' + unidade).upstream_task_ids,
                             {'identificar_carga', 'receber_' + unidade})
        self.assertEqual(diario.get_task('aprovar_dia').trigger_rule, 'all_success')
        self.assertEqual(diario.get_task('publicar_dia').upstream_task_ids, {'aprovar_dia'})
        self.assertFalse(diario.params['publicar_dw'])


if __name__ == '__main__':
    unittest.main()
