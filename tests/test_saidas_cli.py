"""# Codigos de saida da auditoria e da staging

## Cenario isolado
Executa os scripts reais em subprocessos, com cinco fontes pequenas em uma
pasta temporaria. Nao depende de vendas, .env ou backups da maquina do usuario.
"""
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class SaidaDosComandosPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        pasta_teste = tempfile.TemporaryDirectory(prefix="xfit-cli-test-")
        self.addCleanup(pasta_teste.cleanup)
        self.projeto_teste = Path(pasta_teste.name).resolve()
        projeto_original = Path(__file__).resolve().parents[1]
        (self.projeto_teste / "src").mkdir()
        for script in ["data_lake_audit.py", "validate_staging.py", "staging_data.py", "extract_data_lake.py", "source_contract.py"]:
            shutil.copy2(projeto_original / "src" / script, self.projeto_teste / "src" / script)

        venda = {
            "id_venda": "BQ-1", "data_venda": "2020-01-10", "hora_venda": "10:00:00",
            "cliente_id": "CLIENTE-TESTE", "produto_id": "P1", "quantidade": 1,
            "valor_bruto": "30.00", "valor_desconto": "0.00", "valor_liquido": "30.00",
            "custo_total": "10.00", "margem_bruta": "20.00", "status_pedido": "concluida",
            "canal": "loja_fisica", "loja_id": "LJ-BQ",
        }
        produto = {"produto_id": "P1", "produto": "Top teste", "categoria": "Tops",
                   "custo_padrao": "10.00", "preco_lista": "30.00"}
        metas = []
        for unidade in ["LJ-BQ", "LJ-CL", "EC-BR"]:
            metas.append({
                "ano_mes": "2020-01", "unidade_id": unidade,
                "canal": "ecommerce" if unidade == "EC-BR" else "loja_fisica",
                "meta_receita_liquida": "300.00", "meta_pedidos": 10,
                "meta_ticket_medio": "30.00", "meta_margem_bruta_pct": "60.00",
                "meta_taxa_devolucao_pct": "2.00", "inicio_operacao": "2020-01-01",
            })

        fontes_teste = [
            ("vendas_barbacena", "XFIT_VENDAS_BARBACENA_PATH", "vendas_barbacena.csv", "csv", [venda]),
            ("vendas_conselheiro_lafaiete", "XFIT_VENDAS_LAFAIETE_PATH", "vendas_lafaiete.csv", "csv", [dict(venda, id_venda="CL-1", loja_id="LJ-CL")]),
            ("vendas_ecommerce", "XFIT_ECOMMERCE_JSON_PATH", "vendas_online.json", "json_records", [dict(venda, id_venda="ONL-1", canal="ecommerce", pedido_online_id="WEB-1")]),
            ("produtos", "XFIT_PRODUTOS_PATH", "produtos.csv", "csv", [produto]),
            ("metas_mensais", "XFIT_METAS_PATH", "metas.csv", "csv", metas),
        ]
        contrato = []
        configuracao = []
        for nome_fonte, variavel, arquivo_fonte, tipo_fonte, registros in fontes_teste:
            caminho_fonte = self.projeto_teste / arquivo_fonte
            if caminho_fonte.suffix == ".json":
                caminho_fonte.write_text(json.dumps({"records": registros}), encoding="utf-8")
            else:
                with caminho_fonte.open("w", encoding="utf-8-sig", newline="") as arquivo_csv:
                    gravador_csv = csv.DictWriter(arquivo_csv, fieldnames=list(registros[0]), delimiter=";")
                    gravador_csv.writeheader()
                    gravador_csv.writerows(registros)
            contrato.append({"name": nome_fonte, "path": arquivo_fonte, "type": tipo_fonte, "required": True})
            configuracao.append(f"{variavel}={arquivo_fonte}")
        (self.projeto_teste / ".env").write_text("\n".join(configuracao), encoding="utf-8")
        (self.projeto_teste / "config").mkdir()
        self.contrato_fontes = self.projeto_teste / "config/data_sources.json"
        self.contrato_fontes.write_text(json.dumps({"data_sources": contrato}), encoding="utf-8")

    def executar_comando_pipeline(self, script: str, *argumentos: str) -> subprocess.CompletedProcess:
        # NOTE: o extrator respeita variaveis ja exportadas. Remover somente
        # XFIT_ no processo filho impede que o teste leia as fontes do usuario.
        ambiente_teste = {nome: valor for nome, valor in os.environ.items() if not nome.upper().startswith("XFIT_")}
        ambiente_teste["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-B", str(self.projeto_teste / "src" / script), *argumentos],
            cwd=self.projeto_teste, env=ambiente_teste, capture_output=True,
            text=True, encoding="utf-8", timeout=30,
        )

    def test_fontes_aprovadas_retornam_zero(self) -> None:
        for script, mensagem in [("data_lake_audit.py", "status: sucesso"),
                                 ("validate_staging.py", "status_geral: aprovado")]:
            with self.subTest(script=script):
                processo = self.executar_comando_pipeline(script)
                self.assertEqual(processo.returncode, 0, processo.stdout + processo.stderr)
                self.assertIn(mensagem, processo.stdout)

    def test_manifesto_auditado_aprova_mesmo_snapshot_na_staging(self) -> None:
        auditoria = self.executar_comando_pipeline("data_lake_audit.py", "--carga-id", "snapshot-ok")
        self.assertEqual(auditoria.returncode, 0, auditoria.stdout + auditoria.stderr)

        validacao = self.executar_comando_pipeline(
            "validate_staging.py",
            "--manifesto",
            "data/processed/manifests/snapshot-ok.json",
        )

        self.assertEqual(validacao.returncode, 0, validacao.stdout + validacao.stderr)
        self.assertIn("[ok] snapshot_auditoria_carga", validacao.stdout)

    def test_fonte_alterada_depois_da_auditoria_bloqueia_promocao(self) -> None:
        auditoria = self.executar_comando_pipeline("data_lake_audit.py", "--carga-id", "snapshot-diverge")
        self.assertEqual(auditoria.returncode, 0, auditoria.stdout + auditoria.stderr)

        produtos = self.projeto_teste / "produtos.csv"
        conteudo = produtos.read_text(encoding="utf-8-sig")
        produtos.write_text(conteudo.replace("Top teste", "Top teste alterado"), encoding="utf-8-sig")

        validacao = self.executar_comando_pipeline(
            "validate_staging.py",
            "--manifesto",
            "data/processed/manifests/snapshot-diverge.json",
        )

        self.assertEqual(validacao.returncode, 1, validacao.stdout + validacao.stderr)
        self.assertIn("[erro] snapshot_auditoria_carga", validacao.stdout)
        self.assertIn("snapshot da extracao diverge do manifesto auditado", validacao.stdout)

    def test_fonte_ausente_reprova_com_codigo_um(self) -> None:
        (self.projeto_teste / "vendas_barbacena.csv").unlink()
        for script in ["data_lake_audit.py", "validate_staging.py"]:
            with self.subTest(script=script):
                processo = self.executar_comando_pipeline(script)
                self.assertEqual(processo.returncode, 1, processo.stdout + processo.stderr)
        self.assertIn("pode_promover_dw: False", processo.stdout)
        self.assertIn("stg_vendas=2", processo.stdout)
        manifestos = list((self.projeto_teste / "data/processed/manifests").glob("*.json"))
        self.assertEqual(len(manifestos), 1)
        self.assertEqual(json.loads(manifestos[0].read_text(encoding="utf-8"))["status"], "erro")

    def test_configuracao_invalida_retorna_dois_sem_traceback(self) -> None:
        self.contrato_fontes.write_text("{", encoding="utf-8")
        (self.projeto_teste / ".env").unlink()
        for script in ["data_lake_audit.py", "validate_staging.py"]:
            with self.subTest(script=script):
                processo = self.executar_comando_pipeline(script)
                self.assertEqual(processo.returncode, 2)
                saida = processo.stdout + processo.stderr
                self.assertNotIn("Traceback", saida)
                self.assertNotIn(str(self.projeto_teste), saida)

    def test_staging_sem_registros_reprova_com_codigo_um(self) -> None:
        # Arquivos existem, mas nao ha uma carga historica a promover.
        for fonte_csv in self.projeto_teste.glob("*.csv"):
            cabecalho = fonte_csv.read_text(encoding="utf-8-sig").splitlines()[0]
            fonte_csv.write_text(cabecalho + "\n", encoding="utf-8-sig")
        (self.projeto_teste / "vendas_online.json").write_text('{"records": []}', encoding="utf-8")
        processo = self.executar_comando_pipeline("validate_staging.py")
        self.assertEqual(processo.returncode, 1, processo.stdout + processo.stderr)
        self.assertIn("[erro] completude_staging", processo.stdout)
        self.assertIn("stg_vendas=0, stg_produtos=0, stg_metas=0", processo.stdout)
        self.assertNotIn("Traceback", processo.stderr)

    def test_argumento_desconhecido_retorna_dois(self) -> None:
        for script in ["data_lake_audit.py", "validate_staging.py"]:
            with self.subTest(script=script):
                processo = self.executar_comando_pipeline(script, "--opcao-inexistente")
                self.assertEqual(processo.returncode, 2)
        self.assertFalse((self.projeto_teste / "data/processed").exists())

    def test_self_tests_continuam_retornando_zero(self) -> None:
        for script in ["data_lake_audit.py", "validate_staging.py"]:
            with self.subTest(script=script):
                processo = self.executar_comando_pipeline(script, "--self-test")
                self.assertEqual(processo.returncode, 0, processo.stdout + processo.stderr)
                self.assertIn("self-test: OK", processo.stdout)


if __name__ == "__main__":
    unittest.main()
