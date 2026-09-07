"""# Regressao de backups — A01 e A02

## Limite do teste
Usa arquivos descartaveis. Nao altera fontes, .env ou backups do projeto.
"""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import data_lake_audit as audit


class ProtecaoDaCargaTest(unittest.TestCase):
    def setUp(self) -> None:
        temporario = tempfile.TemporaryDirectory(prefix="xfit-backup-test-")
        self.addCleanup(temporario.cleanup)
        self.pasta = Path(temporario.name).resolve()
        self.raiz = self.pasta / "projeto"
        self.raiz.mkdir()
        self.fonte = self.raiz / "fonte.csv"
        self.fonte.write_bytes(b"coluna\noriginal\n")
        self.fontes = [{"name": "teste", "path": "fonte.csv", "type": "csv"}]
        self.backups = self.raiz / "data/processed/backups"
        self.manifestos = self.raiz / "data/processed/manifests"
        self.logs = self.raiz / "data/processed/logs"
        constantes = {
            "BASE_DIR": self.raiz,
            "BACKUP_DIR": self.backups,
            "MANIFEST_DIR": self.manifestos,
            "LOG_DIR": self.logs,
            "RUN_LOG": self.logs / "etl_runs.jsonl",
            "DATA_SOURCES_FILE": self.raiz / "config/data_sources.json",
        }
        for nome, valor in constantes.items():
            troca = patch.object(audit, nome, valor)
            troca.start()
            self.addCleanup(troca.stop)
        contrato = patch.object(audit, "carregar_contrato_fontes", return_value={"data_sources": self.fontes})
        contrato.start()
        self.addCleanup(contrato.stop)

    def test_carga_id_invalido_nao_cria_arquivos(self) -> None:
        # NOTE: ambos os pontos de entrada devem rejeitar antes de mkdir.
        for carga_id in ["", "../fora", "a/b", "a\\b", "C:\\fora", "a:b", "a.",
                         "a b", "CON", "com1", "x" * 81, "á", "id\n", None]:
            with self.subTest(carga_id=carga_id):
                with self.assertRaises(ValueError):
                    audit.copiar_fontes_para_backup(carga_id, self.fontes)
                with self.assertRaises(ValueError):
                    audit.auditar_fontes_da_carga(carga_id, True)
                self.assertFalse((self.raiz / "data").exists())

    def test_destino_e_fonte_fora_da_raiz_nao_escrevem(self) -> None:
        for constante in ["BACKUP_DIR", "MANIFEST_DIR", "LOG_DIR"]:
            with self.subTest(constante=constante):
                with patch.object(audit, constante, self.pasta / "fora"):
                    with self.assertRaises(ValueError):
                        audit.auditar_fontes_da_carga("valida", True)
                self.assertFalse((self.pasta / "fora").exists())
                self.assertFalse((self.raiz / "data").exists())
        fontes_invalidas = self.fontes + [{"name": "fora", "path": "../fora.csv"}]
        with self.assertRaises(ValueError):
            audit.copiar_fontes_para_backup("valida", fontes_invalidas)
        self.assertFalse(self.backups.exists())

    def test_carga_repetida_preserva_backup_manifesto_e_log(self) -> None:
        manifesto = audit.auditar_fontes_da_carga("config-sources-check", True)
        self.assertEqual(manifesto["status"], "sucesso")
        copia = self.backups / "config-sources-check/fonte.csv"
        self.assertEqual(copia.read_bytes(), self.fonte.read_bytes())
        caminhos = [copia, self.manifestos / "config-sources-check.json", self.logs / "etl_runs.jsonl"]
        antes = [p.read_bytes() for p in caminhos]
        self.fonte.write_bytes(b"coluna\nmodificada\n")
        for com_backup in [False, True]:
            with self.assertRaises(FileExistsError):
                audit.auditar_fontes_da_carga("config-sources-check", com_backup)
        with self.assertRaises(FileExistsError):
            audit.copiar_fontes_para_backup("config-sources-check", self.fontes)
        self.assertEqual(antes, [p.read_bytes() for p in caminhos])

    def test_manifesto_sem_backup_tambem_reserva_id(self) -> None:
        audit.auditar_fontes_da_carga("inventario")
        with self.assertRaises(FileExistsError):
            audit.copiar_fontes_para_backup("inventario", self.fontes)
        self.assertFalse(self.backups.exists())

    def test_manifesto_criado_apos_consulta_nao_e_sobrescrito(self) -> None:
        ler_metadados_originais = audit.levantar_metadados_fonte
        destino = self.manifestos / "concorrente.json"

        def simular_manifesto_concorrente(fonte: dict) -> dict:
            destino.parent.mkdir(parents=True)
            destino.write_bytes(b'{"status": "simular_manifesto_concorrente"}')
            return ler_metadados_originais(fonte)

        with patch.object(audit, "levantar_metadados_fonte", side_effect=simular_manifesto_concorrente):
            with self.assertRaises(FileExistsError):
                audit.auditar_fontes_da_carga("concorrente")
        self.assertEqual(destino.read_bytes(), b'{"status": "simular_manifesto_concorrente"}')

    def test_link_na_pasta_operacional_e_bloqueado(self) -> None:
        outro_destino = self.raiz / "outra_pasta"
        outro_destino.mkdir()
        self.backups.parent.mkdir(parents=True)
        try:
            self.backups.symlink_to(outro_destino, target_is_directory=True)
        except OSError:
            self.skipTest("Ambiente sem permissao para criar link simbolico")
        with self.assertRaises(ValueError):
            audit.auditar_fontes_da_carga("link", True)
        self.assertEqual(list(outro_destino.iterdir()), [])

    def test_backup_direto_e_concorrente_nao_sobrescreve(self) -> None:
        def tentar_backup_da_mesma_carga() -> str:
            try:
                audit.copiar_fontes_para_backup("corrida", self.fontes)
            except FileExistsError:
                return "bloqueada"
            return "sucesso"

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: tentar_backup_da_mesma_carga(), range(2)))
        self.assertCountEqual(resultados, ["sucesso", "bloqueada"])
        self.assertEqual((self.backups / "corrida/fonte.csv").read_bytes(), self.fonte.read_bytes())
        with self.assertRaises(FileExistsError):
            audit.auditar_fontes_da_carga("corrida", True)

    def test_falha_de_copia_preserva_carga_parcial(self) -> None:
        # NOTE: pasta parcial nao pode parecer uma nova carga disponivel.
        with patch.object(audit.shutil, "copyfileobj", side_effect=OSError("falha simulada")):
            with self.assertRaises(OSError):
                audit.auditar_fontes_da_carga("parcial", True)
        self.assertTrue((self.backups / "parcial").is_dir())
        self.assertFalse((self.manifestos / "parcial.json").exists())
        with self.assertRaises(FileExistsError):
            audit.auditar_fontes_da_carga("parcial", True)
        self.assertEqual(self.fonte.read_bytes(), b"coluna\noriginal\n")

    def test_cli_rejeita_carga_id_sem_expor_entrada(self) -> None:
        saida = io.StringIO()
        with patch("sys.argv", ["data_lake_audit.py", "--backup", "--carga-id", "../privado"]):
            with contextlib.redirect_stdout(saida), self.assertRaises(SystemExit) as erro:
                audit.main()
        self.assertEqual(erro.exception.code, 2)
        self.assertNotIn("privado", saida.getvalue())
        self.assertFalse(self.backups.exists())


if __name__ == "__main__":
    unittest.main()
