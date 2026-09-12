"""# Contrato SQL do DW

Estes testes nao tentam substituir Postgres. Eles impedem a regressao principal:
voltar a definir schema dimensional em Python/CSV depois da decisao de usar SQL
compativel com Supabase.
"""

from pathlib import Path
import re
import unittest


RAIZ_PROJETO = Path(__file__).resolve().parents[1]
SQL_SCHEMA_DW = RAIZ_PROJETO / "sql" / "schema_dw.sql"
SQL_VALIDACAO_DW = RAIZ_PROJETO / "sql" / "validar_dw.sql"


class SchemaDwSqlTest(unittest.TestCase):
    def carregar_schema(self) -> str:
        return SQL_SCHEMA_DW.read_text(encoding="utf-8").lower()

    def bloco_create_table(self, tabela: str) -> str:
        schema = self.carregar_schema()
        padrao = rf"create table if not exists {re.escape(tabela)} \((.*?)\n\);"
        return re.search(padrao, schema, flags=re.S).group(1)

    def test_schema_dw_e_sql_versionavel(self) -> None:
        schema = self.carregar_schema()

        self.assertIn("create schema if not exists stg", schema)
        self.assertIn("create schema if not exists dw", schema)
        self.assertIn("create table if not exists dw.dim_data", schema)
        self.assertIn("create table if not exists dw.dim_produto", schema)
        self.assertIn("create table if not exists dw.dim_unidade", schema)
        self.assertIn("create table if not exists dw.fato_vendas", schema)
        self.assertIn("create table if not exists dw.fato_metas", schema)
        self.assertIn("create or replace function dw.carregar_dim_data", schema)

    def test_dim_data_tem_chave_calendario_e_regras_derivadas(self) -> None:
        schema = self.carregar_schema()

        for trecho in [
            "data_id integer primary key",
            "data date not null unique",
            "constraint dim_data_id_bate_com_data",
            "constraint dim_data_ano_mes_bate_com_data",
            "constraint dim_data_dia_semana_valido",
        ]:
            self.assertIn(trecho, schema)

    def test_dim_data_nao_recebe_metricas_transacionais(self) -> None:
        bloco_dim_data = self.bloco_create_table("dw.dim_data")

        for nome_proibido in ["receita", "valor_liquido", "quantidade", "ticket", "margem"]:
            self.assertNotIn(nome_proibido, bloco_dim_data)

    def test_dim_produto_e_cadastral_sem_metricas_de_venda(self) -> None:
        bloco_dim_produto = self.bloco_create_table("dw.dim_produto")

        self.assertIn("produto_sk bigint generated always as identity primary key", bloco_dim_produto)
        self.assertIn("produto_id text not null unique", bloco_dim_produto)
        self.assertIn("categoria text not null", bloco_dim_produto)
        for nome_proibido in ["receita", "valor_liquido", "quantidade_vendida", "ticket_medio", "margem_bruta"]:
            self.assertNotIn(nome_proibido, bloco_dim_produto)

    def test_dim_unidade_concentra_canal_e_localizacao(self) -> None:
        bloco_dim_unidade = self.bloco_create_table("dw.dim_unidade")

        self.assertIn("unidade_id text not null unique", bloco_dim_unidade)
        self.assertIn("canal text not null", bloco_dim_unidade)
        self.assertIn("cidade text", bloco_dim_unidade)
        self.assertIn("uf char(2)", bloco_dim_unidade)

    def test_fato_vendas_fica_no_grao_item_vendido(self) -> None:
        schema = self.carregar_schema()
        bloco_fato_vendas = self.bloco_create_table("dw.fato_vendas")

        self.assertIn("venda_item_id text primary key", bloco_fato_vendas)
        self.assertIn("id_venda text not null", bloco_fato_vendas)
        self.assertIn("constraint fato_vendas_item_origem_unico unique (fonte, id_venda, produto_id)", bloco_fato_vendas)
        self.assertIn("md5(v.fonte || '|' || v.id_venda || '|' || v.produto_id)", schema)
        self.assertIn("count(distinct id_venda)", schema)
        self.assertNotIn("cliente_id", bloco_fato_vendas)

    def test_fato_metas_e_mensal_por_unidade(self) -> None:
        bloco_fato_metas = self.bloco_create_table("dw.fato_metas")

        self.assertIn("meta_id text primary key", bloco_fato_metas)
        self.assertIn("ano_mes char(7) not null", bloco_fato_metas)
        self.assertIn("unidade_id text not null references dw.dim_unidade(unidade_id)", bloco_fato_metas)
        self.assertIn("constraint fato_metas_unidade_mes_unico unique (unidade_id, ano_mes)", bloco_fato_metas)

    def test_schema_dw_fica_privado_por_padrao_na_supabase(self) -> None:
        schema = self.carregar_schema()

        self.assertIn("alter table dw.dim_data enable row level security", schema)
        self.assertIn("alter table dw.fato_vendas enable row level security", schema)
        self.assertIn("alter table stg.stg_vendas enable row level security", schema)
        self.assertIn("revoke all on schema dw from anon", schema)
        self.assertIn("revoke all on schema dw from authenticated", schema)
        self.assertIn("revoke all on function dw.carregar_fato_vendas()", schema)

    def test_validacao_dw_e_sql_e_procura_buracos_no_calendario(self) -> None:
        validacao = SQL_VALIDACAO_DW.read_text(encoding="utf-8").lower()

        self.assertIn("from dw.dim_data", validacao)
        self.assertIn("from dw.fato_vendas", validacao)
        self.assertIn("from dw.fato_metas", validacao)
        self.assertIn("generate_series", validacao)
        self.assertIn("data_faltante", validacao)
        self.assertIn("diferenca_valor_liquido", validacao)


if __name__ == "__main__":
    unittest.main()
