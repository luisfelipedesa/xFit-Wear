# xFit Wear — Engenharia de Dados e BI Comercial

Este repositório é uma cópia para portfólio de um projeto real já entregue. A versão disponibilizada aqui e no dashboard público utiliza dados fictícios, preparados para demonstrar a arquitetura, o tratamento dos dados e os indicadores comerciais, preservando a confidencialidade da entrega original.

O projeto reúne ingestão de arquivos, validação de qualidade, orquestração com Airflow, modelagem dimensional em PostgreSQL e análise em um dashboard Streamlit.

[Acessar o dashboard](https://xfit.3.133.147.43.sslip.io/)

## O cenário de negócio

A demonstração acompanha uma operação de roupas fitness com duas lojas físicas, em Barbacena e Conselheiro Lafaiete, e um canal de ecommerce. Cada unidade fornece seus próprios arquivos de vendas, com produtos e metas mensais como referências para a análise.

O objetivo é reunir essas fontes em uma base consistente e permitir o acompanhamento de receita líquida, margem bruta, pedidos, itens vendidos, ticket médio, devoluções, cancelamentos e atingimento de metas.

As unidades podem enviar os arquivos em momentos diferentes. Por isso, o processamento diário trata cada uma de forma independente. Quando uma unidade deixa de atualizar os arquivos, o dashboard continua exibindo seu último histórico aprovado, com as datas originais dos dados.

## Como os dados chegam ao dashboard

```text
Arquivos CSV e JSON de cada unidade
                  |
                  v
Data lake local, recebimentos e manifestos SHA-256
                  |
                  v
Tratamento e validação em Python
                  |
                  v
Staging privada no PostgreSQL
                  |
                  v
Carga transacional do data warehouse em SQL
                  |
                  v
Views agregadas de BI
                  |
                  v
Dashboard Streamlit com cache, publicado na AWS
```

O Python faz a leitura, a padronização e a validação das fontes. O PostgreSQL concentra as regras de persistência e a promoção dos dados para o modelo dimensional. O Airflow organiza a execução e registra o resultado de cada etapa. O Streamlit consulta as views de BI para apresentar os indicadores.

A fonte de ecommerce utiliza JSON e conta com uma API mock paginada para demonstrar a integração com esse formato de origem.

## Ferramentas e versões

As versões abaixo seguem os arquivos de dependências e as imagens declaradas no projeto. As ferramentas do ambiente local foram consultadas em 12/11/2026.

| Ferramenta | Versão ou referência | Uso |
| --- | --- | --- |
| Python | 3.12.14 no ambiente local; imagem `python:3.12-slim` no dashboard | Pipeline, testes e aplicação web |
| Apache Airflow | 3.3.2 | Orquestração das cargas com `CeleryExecutor` |
| PostgreSQL do Airflow | Imagem `postgres:16` | Banco de metadados do orquestrador |
| Redis | Imagem `redis:7.2-bookworm` | Broker do executor Celery |
| Streamlit | 1.66.1 | Interface do dashboard |
| Altair | 6.3.0 | Gráficos e interação com filtros |
| pandas | 3.0.6 | Manipulação de dados na aplicação |
| Psycopg e Psycopg Binary | 3.3.6 | Conexão com PostgreSQL |
| certifi | 2026.10.23 | Certificados de autoridades confiáveis |
| Pillow | 13.0.0 | Dependência de imagens do dashboard |
| Caddy | Imagem `caddy:2.10.2-alpine` | Proxy reverso e HTTPS |
| Docker Engine | 29.8.2 no ambiente local | Execução dos contêineres |
| Docker Compose | 5.6.0 no ambiente local | Configuração dos serviços |
| Git | 2.56.0.windows.4 no ambiente local | Controle de versão |
| Supabase / PostgreSQL do DW | Serviço gerenciado, sem versão do servidor fixada no repositório | Hospedagem do banco analítico |
| AWS EC2 | Serviço gerenciado | Hospedagem do dashboard e do proxy |
| GitHub Actions | Runner `ubuntu-24.04` | Consulta diária de disponibilidade do Supabase |

As tags `python:3.12-slim`, `postgres:16` e `redis:7.2-bookworm` permitem atualizações dentro dessas referências. A versão exata instalada pode variar conforme a construção ou o download da imagem. O Python do Airflow acompanha a imagem oficial `apache/airflow:3.3.2`.

As dependências Python, incluindo as transitivas do dashboard, estão registradas nos arquivos [requirements.lock](requirements.lock) e [dashboard/requirements.lock](dashboard/requirements.lock). As imagens e os serviços estão definidos no [Dockerfile do Airflow](airflow/Dockerfile), no [Compose do Airflow](airflow/docker-compose.yaml), no [Dockerfile do dashboard](dashboard/Dockerfile) e no [Compose de publicação](deploy/aws/compose.yaml).

## Modelo dimensional

O banco é organizado em quatro schemas.

| Schema | Responsabilidade |
| --- | --- |
| `stg` | Receber os dados padronizados para a carga |
| `etl` | Registrar execuções e informações de controle e auditoria |
| `dw` | Armazenar dimensões e fatos do modelo analítico |
| `bi` | Disponibilizar as views de consumo do dashboard |

O modelo utiliza dimensões compartilhadas pelas tabelas de fatos.

| Tabela | Granularidade e finalidade |
| --- | --- |
| `dw.dim_data` | Uma linha por data, com atributos de calendário |
| `dw.dim_produto` | Cadastro dos produtos e suas categorias |
| `dw.dim_unidade` | Identificação das lojas e do ecommerce |
| `dw.fato_vendas` | Uma linha por item de venda |
| `dw.fato_metas` | Uma linha por unidade e mês de referência |

Essa estrutura permite analisar as vendas por período, produto, categoria, unidade e canal. Para comparar vendas e metas, a aplicação primeiro agrega as vendas por unidade e mês, respeitando a granularidade da meta.

A contagem de pedidos considera a origem e a identificação do pedido. Um pedido com produtos de categorias diferentes pode aparecer em mais de uma categoria, por isso esses subtotais exigem cuidado ao serem somados.

A definição do modelo está em [sql/schema_dw.sql](sql/schema_dw.sql). As evoluções do banco ficam em [supabase/migrations](supabase/migrations).

## Orquestração com Airflow

A DAG `xfit_pipeline_diario` está configurada para executar todos os dias às 04h, no fuso `America/Sao_Paulo`. Nas execuções agendadas, a data de referência é calculada automaticamente como o dia anterior. O agendamento utiliza `catchup=False`.

O Airflow está configurado em Docker no computador de operação. A execução no horário previsto depende desse computador, do Docker e dos serviços do Airflow em funcionamento.

Cada unidade passa por recebimento, tratamento e validação próprios. Os lotes válidos seguem para publicação mesmo quando outra unidade está sem arquivo ou apresenta erro. A pendência fica registrada no resultado da execução para acompanhamento.

Esse desenho atende à forma como os arquivos chegam ao data lake. Uma falha em uma loja preserva o histórico aprovado dessa unidade e permite que as demais continuem atualizando seus dados. A disponibilidade do dashboard também depende do servidor da aplicação e do banco.

| DAG | Acionamento | Finalidade |
| --- | --- | --- |
| `xfit_pipeline_diario` | Diário às 04h ou manual | Processar e publicar os lotes diários por unidade |
| `xfit_alimentar_datalake` | Manual | Receber arquivos independentes por unidade e data |
| `xfit_validar_fontes` | Manual | Auditar e validar as fontes históricas |
| `xfit_carga_dw` | Manual | Executar a carga histórica no PostgreSQL |

Nas execuções manuais, a data pode ser informada explicitamente. O parâmetro `publicar_dw` permite controlar a publicação durante a validação do fluxo diário.

O fluxo e os parâmetros estão descritos em [docs/fluxos_airflow.md](docs/fluxos_airflow.md).

## Tratamento e qualidade dos dados

Os arquivos diários chegam em `data/inbox/<unidade>/<data_referencia>/`, acompanhados de um `recebimento.json`. Esse documento informa a unidade, a data, a quantidade de registros, o hash do arquivo e a indicação de dia sem movimento, quando aplicável.

Antes da carga, o pipeline verifica a estrutura do arquivo, os campos obrigatórios, os tipos, a unidade e a data de referência. Também confere duplicidades de itens, consistência dos pedidos, produtos cadastrados, metas necessárias e relações entre valores financeiros. Os cálculos monetários utilizam `Decimal`.

Um arquivo inválido reprova o lote da unidade e da data correspondente. O recebimento explícito de um dia sem movimento permite distinguir ausência de vendas de ausência de envio. Alterações em arquivos de um dia já aprovado exigem revisão.

Os recebimentos aprovados são preservados no data lake com identificação da carga e manifestos SHA-256. Na publicação, a carga utiliza transações, controles de concorrência e reconciliação entre staging e DW. Em caso de falha na promoção, o rollback preserva a consistência do banco. A identificação dos lotes permite conferir reprocessamentos e evitar duplicação.

As regras estão detalhadas em [docs/contrato_tratamento_diario.md](docs/contrato_tratamento_diario.md).

## Dashboard e cache

O dashboard permite filtrar período, unidade, canal e categoria, além de selecionar informações nos gráficos. Um modal apresenta o projeto na primeira abertura de cada sessão do Streamlit.

A aplicação carrega uma base agregada compartilhada em memória com `st.cache_resource`, validade de 300 segundos e limite de duas entradas por processo. As quatro consultas da base são executadas em uma transação de leitura consistente. Depois disso, os filtros trabalham sobre os dados em memória, reduzindo as consultas repetidas durante a navegação.

A atualização do cache acontece na próxima interação após o vencimento. Reiniciar a aplicação também remove esse conteúdo da memória. A carga do Airflow passa a aparecer quando a base é consultada novamente.

O contrato dos indicadores está em [docs/contrato_dashboard.md](docs/contrato_dashboard.md).

## Segurança e publicação

O acesso público permite consultar os indicadores agregados da base fictícia. As credenciais do PostgreSQL permanecem no servidor da aplicação.

A carga e o dashboard utilizam papéis separados no banco, com permissões específicas para escrita e leitura. O projeto inclui schemas privados, políticas de RLS, SQL parametrizado e conexão TLS com verificação de certificado por `verify-full`.

Na publicação, o dashboard roda em contêiner com usuário sem privilégios, sistema de arquivos somente leitura e restrições de capacidades. O Caddy fornece o acesso HTTPS na instância AWS EC2.

Arquivos de configuração com credenciais, fontes locais, backups, logs, manifestos e artefatos de dados ficam fora do Git. A configuração da publicação está documentada em [docs/deploy_dashboard.md](docs/deploy_dashboard.md).

O GitHub Actions executa diariamente uma consulta SQL de disponibilidade no Supabase, às 10h17 UTC, equivalente a 07h17 em Brasília. A rotina registra falhas de configuração, HTTP, rede, DNS e TLS. O processamento comercial continua sob responsabilidade do Airflow. As condições de pausa e disponibilidade dependem do serviço contratado. Os detalhes estão em [docs/disponibilidade_supabase.md](docs/disponibilidade_supabase.md).

## Executar a demonstração local

A demonstração visual usa dados fictícios internos da aplicação e pode ser aberta sem configurar o banco. Os comandos abaixo usam PowerShell e Python 3.12.

```powershell
git clone https://github.com/luisfelipedesa/xFit-Wear.git
cd xFit-Wear
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r dashboard/requirements.lock
$env:XFIT_DASHBOARD_DEMO = '1'
.\.venv\Scripts\python.exe -m streamlit run dashboard/app.py --server.address=127.0.0.1 --server.port=8501
```

Abra `http://127.0.0.1:8501` no navegador. Esse modo fornece uma prévia da interface com uma base própria de demonstração. Para consultar o DW, siga a configuração de conexão e acesso em [docs/deploy_dashboard.md](docs/deploy_dashboard.md).

A execução do pipeline requer as fontes locais, as configurações de conexão e o banco com as migrations aplicadas. O contrato das fontes está em [config/data_sources.json](config/data_sources.json), e a operação das DAGs está em [docs/fluxos_airflow.md](docs/fluxos_airflow.md).

## Testes

Com as dependências instaladas, execute a suíte a partir da raiz do repositório.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Os testes cobrem regras de tratamento, qualidade, carga, orquestração e comportamento do dashboard. Os testes de integração com PostgreSQL exigem habilitação explícita, configurações próprias e um banco de teste preparado, pois executam cargas reais nesse ambiente.

As consultas de conferência estão em [sql/validar_dw.sql](sql/validar_dw.sql), [sql/conferir_dw_diario.sql](sql/conferir_dw_diario.sql) e [sql/validar_dashboard.sql](sql/validar_dashboard.sql). O registro de homologação do fluxo diário está em [docs/homologacao_pipeline_diario.md](docs/homologacao_pipeline_diario.md).

## Organização do repositório

```text
airflow/               DAGs e configuração do orquestrador
config/                Contrato das fontes
dashboard/             Aplicação Streamlit, indicadores e cache
deploy/aws/            Configuração de publicação e HTTPS
docs/                  Contratos e documentação técnica
sql/                   Modelo dimensional, cargas e conferências
src/                   Ingestão, auditoria, tratamento e carga Python
supabase/migrations/   Evolução versionada do banco
tests/                 Testes automatizados
.github/workflows/     Rotina de disponibilidade do Supabase
```
