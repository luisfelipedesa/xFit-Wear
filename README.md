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
  -> staging em memória
  -> validação de qualidade
  -> preparo de parâmetros para SQL
  -> schema dimensional PostgreSQL/Supabase
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
- RLS habilitado no SQL planejado para Supabase;
- ausência de policies/grants para `anon` e `authenticated` nesta fase, mantendo deny-by-default.

Limite atual: ainda não existe Supabase real aplicado, usuário, autenticação, autorização, dashboard público ou deploy validado. A segurança atual cobre o pipeline local e o contrato SQL planejado.

## Como Executar Localmente

Pré-requisito:

- Python 3.11+ recomendado.

Este projeto usa principalmente biblioteca padrão do Python.

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
python -B src\data_lake_audit.py --carga-id minha-carga
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

## Status Atual

Concluído:

- geração das fontes demonstrativas;
- contrato versionável das fontes;
- auditoria local do data lake;
- extração e staging em Python;
- validação de qualidade antes da promoção;
- schema dimensional mínimo em SQL;
- validações SQL para o DW;
- testes automatizados de regressão.

Última evidência registrada no projeto local:

- 56 testes aprovados;
- 1 teste de symlink ignorado por permissão no Windows;
- staging aprovada com 71.575 vendas, 12 produtos e 277 metas;
- preparo da `dim_data` aprovado para 2018-11-01 até 2026-12-31, com 2.983 dias previstos.

## Próximas Etapas

### Supabase/PostgreSQL

- instalar/configurar Supabase CLI;
- criar a estrutura oficial de migrations;
- transformar `sql/schema_dw.sql` em migration versionada;
- aplicar o schema em banco PostgreSQL/Supabase real;
- carregar `stg`, `etl` e `dw` no banco;
- executar `sql/validar_dw.sql` contra o banco real;
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

- execução real do SQL em Supabase/PostgreSQL;
- migrations oficiais;
- Airflow real;
- dashboard;
- deploy;
- autenticação/autorização de usuário final;
- policies finais de RLS para consumo analítico;
- testes negativos em banco real.

Essa separação é intencional: o repositório mostra o progresso técnico real e o caminho de evolução, sem inflar o que ainda não foi comprovado.
