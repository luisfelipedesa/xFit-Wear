# xFit Wear - Pipeline de Dados e BI Comercial

Projeto de Engenharia de Dados e BI para uma operação comercial de roupas fitness. A proposta é estruturar um pipeline comercial completo, saindo de fontes operacionais demonstrativas, passando por auditoria, staging, validação de qualidade e modelagem dimensional em SQL para consumo analítico futuro.

Para apresentação pública de portfólio, o repositório utiliza dados demonstrativos e sem identificação real de clientes, preservando privacidade e confidencialidade. A documentação, o desenho técnico e os critérios de operação tratam o projeto como uma entrega real: fontes brutas, manifestos, backups, logs, variáveis locais e artefatos de DW ficam fora do Git.

## Objetivo

Demonstrar competências práticas de dados em um cenário comercial:

- ingestão de CSV e JSON/API mock;
- padronização de vendas, produtos e metas;
- validação de qualidade, completude e materialidade financeira;
- auditoria de arquivos com hash SHA-256, manifesto e backup local;
- contrato de fontes versionável;
- schema dimensional em PostgreSQL/Supabase;
- preparação para orquestração com Airflow;
- base futura para dashboard em Python e deploy.

## Contexto de Negócio

A xFit Wear representa uma operação comercial de roupas fitness com:

- loja física em Barbacena, MG;
- loja física em Conselheiro Lafaiete, MG;
- canal de ecommerce;
- metas mensais por canal/unidade;
- cadastro de produtos;
- indicadores como receita líquida, margem bruta, ticket médio, pedidos, itens vendidos, devoluções, cancelamentos e atingimento de metas.

Os dados publicados são demonstrativos para portfólio e não expõem clientes, pedidos ou informações comerciais reais. O pipeline, porém, foi desenhado com cuidados de operação, segurança e rastreabilidade esperados em uma entrega profissional.

## Arquitetura Atual

```text
Fontes demonstrativas
  -> contrato de fontes
  -> auditoria do data lake local
  -> extração Python
  -> staging validada em memória
  -> validação de qualidade
  -> carga da staging privada no Supabase
  -> promoção transacional em SQL
  -> DW PostgreSQL/Supabase reconciliado
```

Responsabilidades por camada:

- `gerar_fontes_xfit.py`: gera as fontes demonstrativas locais.
- `config/data_sources.json`: define o contrato versionável das fontes.
- `src/source_contract.py`: centraliza leitura do contrato, caminhos, contagem e hash.
- `src/data_lake_audit.py`: gera manifesto, log e backup opcional da carga.
- `src/extract_data_lake.py`: lê as fontes contratadas.
- `src/staging_data.py`: padroniza vendas, produtos e metas.
- `src/validate_staging.py`: valida completude, identidade dos itens, materialidade e snapshot auditado.
- `src/preparar_dim_data_dw.py`: prepara parâmetros seguros para a carga SQL da `dim_data`.
- `sql/schema_dw.sql`: define schemas, tabelas e funções SQL do modelo dimensional.
- `sql/validar_dw.sql`: contém consultas de validação para conferir o DW após a carga.
- `src/preparar_carga_supabase.py`: audita, confere o backup e prepara lotes SQL privados da staging aprovada.
- `src/carregar_postgres.py`: automatiza auditoria, backup, envio parametrizado e promoção transacional no PostgreSQL.
- `supabase/migrations/`: mantém o histórico versionado do schema aplicado.
- `sql/carregar_dw.sql`: promove as dimensões e fatos com reconciliação e registro da carga.
- `sql/testar_supabase.sql`: testa bloqueio de acesso e reprocessamento em transação com rollback.
- `tests/`: cobre regras de auditoria, staging, mensagens seguras, SQL e preparo de carga.

## Fontes de Dados

As fontes locais não são versionadas no GitHub, mas podem ser geradas pelo script do projeto.

Fontes esperadas:

- vendas da loja física de Barbacena;
- vendas da loja física de Conselheiro Lafaiete;
- vendas online em JSON, consumíveis por API mock local;
- metas mensais;
- cadastro de produtos;
- dicionário de dados.

Volume da base local validada:

- 71.575 vendas;
- 12 produtos;
- 277 metas mensais;
- período de vendas de 2018-11-01 a 2026-07-31;
- metas até 2026-12.

## Modelo Dimensional

O modelo mínimo está definido em SQL para PostgreSQL/Supabase:

- `stg.stg_vendas`
- `stg.stg_produtos`
- `stg.stg_metas`
- `etl.cargas_dw`
- `dw.dim_data`
- `dw.dim_produto`
- `dw.dim_unidade`
- `dw.fato_vendas`
- `dw.fato_metas`

Decisões importantes:

- `fato_vendas` está no grão de item vendido.
- `id_venda` continua disponível para calcular pedidos com `count(distinct id_venda)`.
- `venda_item_id` é uma chave técnica determinística enquanto a origem não possuir `item_id` nativo.
- `dim_produto` é cadastral e não guarda métricas transacionais.
- `dim_unidade` concentra canal, unidade, cidade e UF; ecommerce permanece como unidade única `EC-BR`.
- `fato_metas` é mensal por unidade, evitando multiplicar metas por item vendido.
- `cliente_id` permanece fora da fato mínima para reduzir exposição no consumo analítico.

## Segurança e Governança

Controles já presentes no projeto:

- `.env` fora do Git;
- fontes brutas e dados processados fora do Git;
- backups, logs, manifestos e DW local ignorados;
- validação de caminhos para reduzir risco de path traversal;
- bloqueio de sobrescrita acidental de backups e manifestos;
- mensagens públicas sem ecoar IDs sensíveis, payloads ou caminhos locais;
- RLS habilitado nas nove tabelas aplicadas no Supabase;
- ausência de policies/grants para `anon` e `authenticated` nesta fase, mantendo deny-by-default.

O job utiliza o papel dedicado `xfit_pipeline`, sem privilégios administrativos, bypass de RLS, DELETE ou TRUNCATE. Grants e policies de leitura, inserção e atualização são específicos para suas nove tabelas internas. A conexão exige TLS com certificado e hostname verificados (`verify-full`), usando conexão direta ou pooler de sessão na porta 5432.

Testes executados no Postgres confirmaram o bloqueio de leitura, escrita e execução das funções de carga para `anon` e `authenticated`, além das restrições do job. O Security Advisor não retornou alertas na verificação de 2026-10-01. Acesso de usuário final, dashboard público e deploy continuam pendentes.

## Como Executar Localmente

Pré-requisito:

- Python 3.11+ recomendado.

A extração e a validação usam principalmente a biblioteca padrão; a conexão ao PostgreSQL usa Psycopg 3. Instale as dependências nas versões registradas:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip check
```

1. Clone o repositório e entre na pasta:

```powershell
git clone <url-do-repositorio>
cd "xFit Wear"
```

2. Gere as fontes demonstrativas, caso elas ainda não existam:

```powershell
python gerar_fontes_xfit.py
```

Se as fontes já existirem, a geração é bloqueada para evitar sobrescrita acidental. Para sobrescrever intencionalmente, faça backup antes e use:

```powershell
python src\data_lake_audit.py --backup
python gerar_fontes_xfit.py --force
```

3. Rode os testes:

```powershell
python -B -m unittest discover -s tests -v
```

4. Audite o snapshot local:

```powershell
python -B src\data_lake_audit.py --backup --carga-id minha-carga
```

5. Valide a staging contra o manifesto:

```powershell
python -B src\validate_staging.py --manifesto data\processed\manifests\minha-carga.json
```

6. Prepare os parâmetros da `dim_data`:

```powershell
python -B src\preparar_dim_data_dw.py --manifesto data\processed\manifests\minha-carga.json --carga-dw-id dw-minha-carga
```

## Validações Implementadas

O pipeline valida:

- presença de todas as fontes obrigatórias;
- contagem de entrada e saída por fonte;
- status único e bem formado por etapa;
- tabelas obrigatórias não vazias;
- identidade provisória de item vendido;
- rejeição de números não finitos e quantidades fracionárias;
- cadastro de produtos usado nas vendas;
- metas por unidade e mês;
- materialidade financeira por fonte, canal, unidade e mês;
- divergência entre snapshot auditado e staging;
- mensagens de erro sem vazamento de valores brutos ou caminhos locais.

## Carga no Supabase

A primeira carga foi executada e validada em 2026-10-01. A migration inicial está em `supabase/migrations/20261001112805_schema_dw_xfit.sql`; os schemas `stg`, `etl` e `dw` permanecem privados.

### Execução Automática

A migration `supabase/migrations/20261001115245_papel_pipeline_postgres.sql` define o papel restrito e suas permissões. Um administrador deve aplicar as migrations e habilitar LOGIN com uma senha forte, fora do SQL versionado. O ambiente atual já está configurado; em outro ambiente, configure um `.env` local a partir de `.env.example` com `XFIT_PG_HOST`, `XFIT_PG_PORT`, `XFIT_PG_DATABASE`, `XFIT_PG_USER`, `XFIT_PG_PASSWORD` e `XFIT_PG_SSLROOTCERT`.

No pooler Supabase, o usuário segue `xfit_pipeline.<project-ref>`. Obtenha o certificado CA oficial nas configurações do banco e indique seu caminho em `XFIT_PG_SSLROOTCERT`. Restrinja o acesso ao `.env` e não utilize credenciais administrativas ou `service_role` no job. Sem CA explícita, o script tenta as raízes confiáveis do sistema; a conexão falha se o certificado não puder ser verificado.

```powershell
python -B src\carregar_postgres.py --verificar-conexao
python -B src\carregar_postgres.py --carga-id nova-carga
```

Sem `--carga-id`, o comando gera um identificador. Use um ID novo em cada execução: IDs já registrados não são sobrescritos. Não use o pooler de transações (porta 6543), pois o bloqueio do job depende da sessão.

O job registra a execução em `etl.cargas_dw`, bloqueia cargas concorrentes, audita as fontes, cria backup, verifica hashes e valida a staging. Envia os dados por COPY cliente para tabelas temporárias e realiza upsert parametrizado na staging persistente. Contagens, quantidades e valores são reconciliados antes da promoção SQL dimensional.

Staging e DW são confirmados na mesma transação. Falhas anteriores ao commit revertem ambos; o histórico registra `erro` separadamente, quando a conexão permite. Logs locais não expõem payloads ou credenciais. A carga só termina como `sucesso` após a reconciliação das fatos. Este comando automatiza a execução, mas ainda não agenda cargas.

Os testes de integração são opt-in e exigem um banco de teste com migrations aplicadas, fontes demonstrativas e configuração do papel restrito. Eles executam cargas reais, criam backups e registros de histórico; não os rode contra dados de clientes sem um ambiente dedicado:

```powershell
$env:XFIT_TEST_POSTGRES = '1'
python -B -m unittest discover -s tests -p test_postgres_integracao.py -v
Remove-Item Env:XFIT_TEST_POSTGRES
```

### Exportação SQL Opcional

Para inspecionar ou preparar lotes privados para uma execução administrativa:

```powershell
python -B src\preparar_carga_supabase.py --carga-id nova-carga --tamanho-lote 1000
```

O comando cria backup, manifesto, valida a staging contra o snapshot, confere os hashes das cópias e gera os lotes e um resumo em `data/processed/dw/nova-carga/`. Esses arquivos contêm dados e ficam fora do Git. Esse exportador não envia dados; a execução automática recomendada usa `carregar_postgres.py`.

Na implantação inicial, os lotes foram enviados pelo conector administrativo e apenas a promoção dimensional foi transacional. Essa execução histórica é distinta do job atual, que inclui staging e DW na mesma transação.

Depois da promoção, executar `sql/validar_dw.sql` e `sql/testar_supabase.sql`. O último arquivo testa os papéis restritos e o reprocessamento e termina com rollback para preservar os dados. As funções usam upsert por chave de origem; remoções na origem e cargas incrementais ainda precisam de um contrato próprio.

## Status Atual

Concluído:

- geração das fontes demonstrativas;
- contrato versionável das fontes;
- auditoria local do data lake;
- extração e staging em Python;
- validação de qualidade antes da promoção;
- schema dimensional mínimo em SQL;
- validações SQL para o DW;
- testes automatizados de regressão;
- migration inicial aplicada em Supabase/PostgreSQL;
- staging e modelo dimensional carregados no banco;
- promoção transacional com registro de sucesso;
- reconciliação financeira e por item vendido;
- testes de acesso negado e reprocessamento no Postgres.
- carga automática Python/PostgreSQL com papel restrito, TLS verificado e bloqueio de concorrência;
- rollback de staging e DW comprovado após falha injetada na promoção.

Última evidência registrada em 2026-10-01:

- 68 testes na suíte padrão: 63 aprovados, 1 skip de symlink Windows e 4 testes remotos opt-in;
- 4 testes remotos executados separadamente e aprovados;
- staging aprovada com 71.575 vendas, 12 produtos e 277 metas;
- calendário carregado de 2018-11-01 até 2026-12-31, com 2.983 dias;
- 12 produtos, 3 unidades, 71.575 itens vendidos e 277 metas no DW;
- diferença financeira staging → DW igual a zero;
- zero divergências nas conferências de itens, produtos, metas e calendário;
- carga automática `dw-postgres-automatico-20261001` registrada como `sucesso`;
- reprocessamento sem duplicação e acessos privados bloqueados no banco real.

## Próximas Etapas

### Supabase/PostgreSQL

- formalizar cargas incrementais, remoções na origem e recuperação de falhas;
- reconciliar registros `iniciada` após desconexões abruptas e testar recuperação de backup;
- revisar grants, RLS e policies antes de qualquer exposição para dashboard;
- criar views seguras de consumo, em vez de expor tabelas base diretamente.

### Airflow

- criar DAG para auditoria, extração, staging, validação e carga dimensional;
- propagar `carga_id` e `carga_dw_id` entre tarefas;
- interromper o fluxo quando auditoria ou staging forem reprovadas;
- registrar logs e status de execução por etapa;
- separar falha técnica de reprovação de regra de negócio;
- preparar reprocessamento controlado e idempotência das cargas.

### Dashboard e Analytics

- construir dashboard interativo em Python;
- consumir apenas views ou consultas aprovadas do DW;
- apresentar KPIs comerciais: receita líquida, margem, ticket médio, pedidos, devoluções, metas e mix de produto;
- incluir status/freshness das cargas para evitar análise sobre dados incompletos.

### Deploy

- publicar a camada visual futuramente na Vercel;
- manter segredos fora do frontend;
- configurar variáveis de ambiente por ambiente;
- validar CORS, headers, logs e exposição de dados;
- criar um checklist de smoke test pós-deploy.

## O Que Este Projeto Demonstra

- Python aplicado a pipeline de dados;
- modelagem dimensional;
- SQL para PostgreSQL/Supabase;
- validação de dados com critérios de aceite claros;
- mentalidade de produção aplicada a uma entrega apresentada em portfólio;
- testes automatizados;
- documentação técnica;
- separação entre camada bruta, staging, DW e consumo analítico;
- cuidado com segurança, versionamento e rastreabilidade.

## Limites Declarados

Este projeto ainda não deve ser apresentado como um produto em produção.

Ainda faltam:

- Airflow real;
- dashboard;
- deploy;
- autenticação/autorização de usuário final;
- policies finais de RLS para consumo analítico;
- recuperação após perda abrupta de conexão, restauração de backups e contrato de cargas incrementais/remoções.

O rollback cobre alterações transacionais, não garante sequências sem lacunas nem resolve confirmação ambígua se a conexão cair durante o commit. Nessas situações, confira `etl.cargas_dw` e reconcilie o DW antes de uma nova tentativa. O papel do pipeline não deve ser reutilizado como credencial de consumo de um dashboard.

Essa separação é intencional: o repositório mostra o progresso técnico real e o caminho de evolução, sem inflar o que ainda não foi comprovado.
