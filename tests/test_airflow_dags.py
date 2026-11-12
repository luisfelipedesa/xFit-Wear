from pathlib import Path
from types import SimpleNamespace
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

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
            ti = MagicMock()
            with patch.dict(receber.__globals__, RAIZ=raiz,
                            get_current_context=lambda: {'params': params, 'ti': ti}):
                selecao = {}
                for unidade in ('barbacena', 'lafaiete', 'ecommerce'):
                    recebimento = fluxo.get_task('receber_' + unidade).python_callable('dag-teste', unidade)
                    selecao[unidade] = fluxo.get_task('tratar_' + unidade).python_callable('dag-teste', recebimento, unidade)
                ti.xcom_pull.side_effect = lambda task_ids: selecao[task_ids.removeprefix('tratar_')]
                resultado = fluxo.get_task('publicar_unidades').python_callable('dag-teste')
                self.assertEqual(set(resultado.values()), {'validado_sem_publicacao'})
                for unidade in selecao:
                    self.assertTrue((raiz / 'data/processed/staging_diaria/publicacoes' /
                                     ('dag-teste-' + unidade) / 'manifesto.json').is_file())
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
            if fluxo.dag_id != 'xfit_pipeline_diario':
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
        self.assertEqual(diario.get_task('publicar_unidades').trigger_rule, 'all_done')
        self.assertEqual(diario.get_task('publicar_unidades').upstream_task_ids,
                         {'identificar_carga', 'tratar_barbacena', 'tratar_lafaiete', 'tratar_ecommerce'})
        self.assertFalse(diario.params['publicar_dw'])

    def test_agenda_dispara_as_04h_a_partir_da_primeira_data_programada(self):
        import pendulum
        from airflow.timetables.base import TimeRestriction

        fluxo = DagBag(dag_folder=str(Path(__file__).resolve().parents[1] / 'airflow/dags')).dags['xfit_pipeline_diario']
        timetable = fluxo.timetable
        # Conferir tambem a configuracao serializada que o scheduler usa.
        timetable = type(timetable).deserialize(timetable.serialize())
        restricao = TimeRestriction(earliest=fluxo.start_date, latest=None, catchup=False)
        for agora in (pendulum.datetime(2026, 11, 9, 13, tz='UTC'),
                      pendulum.datetime(2026, 11, 9, 7, 1, tz='UTC')):
            with self.subTest(agora=agora), patch('airflow.timetables.trigger.utcnow', return_value=agora):
                proxima = timetable.next_dagrun_info(last_automated_data_interval=None, restriction=restricao)
                self.assertEqual(proxima.run_after, pendulum.datetime(2026, 11, 10, 7, tz='UTC'))
                seguinte = timetable.next_dagrun_info(last_automated_data_interval=proxima.data_interval,
                                                       restriction=restricao)
                self.assertEqual(seguinte.run_after, pendulum.datetime(2026, 11, 11, 7, tz='UTC'))

    def test_data_automatica_usa_dia_anterior_local_e_publica_unidades_aprovadas(self):
        import pendulum

        fluxo = DagBag(dag_folder=str(Path(__file__).resolve().parents[1] / 'airflow/dags')).dags['xfit_pipeline_diario']
        resolver = fluxo.get_task('receber_barbacena').python_callable.__globals__['parametros_da_ingestao']
        for instante, esperado in (('2026-11-10T07:00:00Z', '2026-11-09'),
                                   ('2027-01-01T07:00:00Z', '2026-12-31'),
                                   ('2026-11-01T02:00:00Z', '2026-10-30')):
            with self.subTest(instante=instante):
                contexto = {'params': {'data_referencia': '2020-01-01', 'publicar_dw': False},
                            'dag_run': SimpleNamespace(run_type='scheduled'),
                            'data_interval_end': pendulum.parse(instante)}
                parametros = resolver(contexto)
                self.assertEqual(parametros['data_referencia'], esperado)
                self.assertTrue(parametros['publicar_dw'])
                self.assertEqual(contexto['params']['data_referencia'], '2020-01-01')
        manual = {'params': {'data_referencia': '2026-10-31', 'publicar_dw': False},
                  'dag_run': SimpleNamespace(run_type='manual')}
        self.assertEqual(resolver(manual), manual['params'])
        manual['params']['data_referencia'] = None
        manual['data_interval_end'] = pendulum.parse('2026-11-10T07:00:00Z')
        self.assertEqual(resolver(manual)['data_referencia'], '2026-11-09')
        self.assertFalse(resolver(manual)['publicar_dw'])

    def test_publicacao_continua_apos_ausencia_e_erro_de_uma_unidade(self):
        fluxo = DagBag(dag_folder=str(Path(__file__).resolve().parents[1] / 'airflow/dags')).dags['xfit_pipeline_diario']
        publicar = fluxo.get_task('publicar_unidades').python_callable
        ti = MagicMock()
        ti.xcom_pull.side_effect = lambda task_ids: None if task_ids == 'tratar_barbacena' else 'lote-aprovado'
        contexto = {'params': {'data_referencia': '2020-01-03', 'publicar_dw': True}, 'ti': ti}
        chamadas = []

        def executar(argumentos, **opcoes):
            chamadas.append(argumentos)
            if '--aprovar-unidade' in argumentos and 'lafaiete' in argumentos:
                import subprocess
                raise subprocess.CalledProcessError(1, argumentos)

        with patch.dict(publicar.__globals__, get_current_context=lambda: contexto), \
                patch('subprocess.run', side_effect=executar):
            with self.assertRaisesRegex(ValueError, 'pendencias'):
                publicar('dag-parcial')
        cargas = [args for args in chamadas if '--manifesto' in args]
        self.assertEqual(len(cargas), 1)
        self.assertIn('dag-parcial-ecommerce', cargas[0][-1])


if __name__ == '__main__':
    unittest.main()
