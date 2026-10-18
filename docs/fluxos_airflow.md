# Alimentacao por unidade e protecoes do DW

## Executar no Docker Desktop do Windows

Usar contêineres Linux no Docker Desktop. No PowerShell:

```powershell
Set-Location 'D:\PROJETOS\xFit Wear\airflow'
docker --context desktop-linux compose up -d
docker --context desktop-linux compose ps
docker --context desktop-linux compose stop
```

Se `docker` ainda nao estiver no PATH do terminal, usar o executavel da instalacao:

```powershell
& "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe" --context desktop-linux compose ps
```

O grupo `airflow` no Docker Desktop contem os servicos; as DAGs ficam no painel
`http://127.0.0.1:8080/dags`. Os arquivos locais continuam em D:\PROJETOS\xFit Wear
e sao montados nos conteineres, incluindo logs, contratos e fontes.

O metadata DB e persistido no volume `airflow_postgres-db-volume` do Desktop.
A instancia antiga no Docker Engine do Ubuntu fica parada, com os dados
preservados para recuperacao. Nao iniciar simultaneamente os dois ambientes.
O backup da migracao esta em
`data/processed/backups/migracao-docker-desktop-20261015/`, ignorado pelo Git e
com ACL restrita. Contem dump PostgreSQL, arquivo de logs/configuracao/DAGs,
imagens e manifesto com hashes/contagens. Credenciais de login existentes sao
preservadas pela restauracao do metadata DB.

## Responsabilidades

`xfit_alimentar_datalake` recebe as entregas locais de Barbacena, Lafaiete e
ecommerce em tarefas independentes. Cada entrega tem unidade, data, volume e
hash declarados. Uma ausencia nao bloqueia os outros recebimentos. O resumo
roda depois de todas as tarefas e fica em falha quando existe pendencia, para
que o painel nao apresente um recebimento incompleto como sucesso.

O fluxo e manual. No disparo, informar `data_referencia` em `YYYY-MM-DD`.
Falta de recibo/arquivo produz `ausente`; entrega divergente produz `erro`;
entrega aceita produz `recebida` ou `sem_movimento`. A sinalizacao aparece no
Airflow e nos relatorios locais; nao envia email ou notificacao externa.

## Contrato de entrega local

Depositar os arquivos em `data/inbox/<unidade>/<data_referencia>/`:

| Unidade | Identificador | Arquivo |
|---|---|---|
| barbacena | LJ-BQ | vendas.csv |
| lafaiete | LJ-CL | vendas.csv |
| ecommerce | EC-BR | vendas.json |

Cada pasta deve conter `recebimento.json`, publicado depois do arquivo de dados:

```json
{
  "unidade_id": "LJ-BQ",
  "data_referencia": "2026-07-31",
  "registros": 100,
  "sem_movimento": false,
  "sha256": "SHA256_DO_ARQUIVO_ENTREGUE"
}
```

CSV usa UTF-8 e separador `;`; JSON usa `{"records": [...]}`. Os registros
precisam pertencer a unidade/data declaradas. O CSV deve conter ao menos
`data_venda`, `loja_id` e `canal`; a validacao comercial completa ocorre depois,
no tratamento. O limite local por arquivo e 128 MiB.

Um dia sem movimento exige recibo com `registros: 0`, `sem_movimento: true` e
arquivo vazio de registros, com estrutura/cabecalho e SHA-256 corretos. Arquivo
antigo ou pasta ausente nao equivalem a dia sem movimento.

O produtor pode obter o hash com `Get-FileHash -Algorithm SHA256`, usando o valor
em letras minusculas no recibo. Os arquivos e recibos nao sao publicados no Git.

## Persistencia e reprocessamento

As entregas aceitas ficam em
`data/raw/recebimentos/<unidade>/<data_referencia>/<carga_id>/`. A copia tem o
hash conferido antes da publicacao de `recebimento.json`. Relatorios por unidade
ficam em `data/processed/manifests/alimentacao/<carga_id>/<unidade>.json`.
Pastas parciais sem confirmacao nao devem ser consumidas. O mesmo identificador
nao sobrescreve uma tentativa anterior. Para uma nova tentativa, disparar outro
run, que recebe novo identificador.

Essas particoes diarias nao substituem os arquivos historicos do contrato atual
nem sao incorporadas automaticamente ao DW. A extracao/staging historica e os
fluxos `xfit_validar_fontes` e `xfit_carga_dw` continuam usando as fontes em
`config/data_sources.json`. O [contrato do tratamento diario v1](contrato_tratamento_diario.md)
e executado por `src/tratar_diario.py` e pela DAG `xfit_pipeline_diario`.
O recebimento isolado prova chegada ao lake, nao qualidade comercial; o tratamento
diario separado verifica qualidade antes de autorizar a publicacao.

## Pipeline diario integrado

No painel, abrir `xfit_pipeline_diario` e informar:

```json
{
  "data_referencia": "2026-07-31",
  "recebimentos": {},
  "publicar_dw": false
}
```

A data e ilustrativa: selecionar a data real das entregas, nao o dia da execucao.
Com `recebimentos={}`, cada tarefa recebe a unidade do inbox daquela data. Para
usar copias ja confirmadas, preencher os identificadores explicitamente, por exemplo:

```json
{
  "barbacena": "carga-confirmada-bq",
  "lafaiete": "carga-confirmada-cl",
  "ecommerce": "carga-confirmada-ec"
}
```

Unidades omitidas desse mapa sao recebidas do inbox. O mapa permite completar
um dia atrasado sem escolher automaticamente a entrega mais recente.

Fluxo: identificar carga -> tres ramos receber/tratar -> aprovar dia -> publicar.
Uma falha nao cancela os outros recebimentos/tratamentos. A barreira e a publicacao
usam `all_success`: nenhuma unidade ausente, reprovada ou em revisao libera o DW.

`publicar_dw=false` executa recebimento, tratamento e aprovacao local, mas nao
abre conexao PostgreSQL. `true` conecta com papel restrito/TLS e publica o conjunto
aprovado; nao reabre os arquivos historicos. A DAG inicia pausada, sem schedule e
sem retries. Despausar no painel quando for executar; nao habilitar carga remota
antes de corrigir/verificar a configuracao local de conexao.

As saidas ficam em `data/processed/staging_diaria/`, fora do Git e com volume de
escrita proprio no Docker. Cada lote inclui vendas, produtos/metas padronizados,
snapshots CSV das referencias, hashes e manifesto publicado por ultimo. Pastas
incompletas nao sao aprovadas. Repeticao identica aponta para a aprovacao anterior.

O executor diario faz COPY parametrizado, verifica precisao/conteudo, preserva o
historico e usa as mesmas transacoes/locks da carga existente. Nao atualiza dados
de negocio existentes divergentes nem transforma omissoes em DELETE. Referencias
alteradas ou uma nova identidade para data ja publicada exigem revisao.
`etl.cargas_dw` registra `dw-diario-YYYYMMDD` e a identidade do conteudo em
`carga_origem_id`. Repetir sucesso reconcilia staging/DW antes de retornar reutilizado.
Dias com tres declaracoes de zero tambem sao registrados, sem venda artificial.

Falha confirmada ou conexao perdida nao autoriza limpar/repetir a publicacao:
reconciliar primeiro o registro da data, manifestos e DW. Um arquivo `.lock`
abandonado apos interrupcao abrupta exige verificar que nao existe processo ativo
antes de remover somente aquele bloqueio; nao ha limpeza automatica de historico.

Testes em PostgreSQL descartavel nao comprovam carga no Supabase. Depois da
restauracao do projeto, a conexao restrita/TLS e a carga historica foram aprovadas.
O fluxo diario tambem foi executado pelo scheduler/worker com lotes controlados,
repeticao, ausencia e zero: [evidencias e limites da homologacao](homologacao_pipeline_diario.md).

## Protecoes na carga do DW

A qualidade comercial e validada em Python antes da transferencia. O SQL do DW
mantem as chaves unicas/estrangeiras, campos obrigatorios e checks estruturais.
Staging e DW sao promovidos na mesma transacao, com rollback em falhas conhecidas.

O executor confere contagens, somas e os registros completos entre as tabelas
temporarias do COPY e a staging persistida. Valores que se compensam nos totais
nao escapam da comparacao. A promocao SQL reconcilia vendas, metas e o cadastro de
produtos antes de marcar sucesso.

O advisory lock impede um segundo job. Locks nas tabelas de staging e DW bloqueiam
escritores concorrentes durante a transferencia/promocao; leituras comuns continuam
permitidas. O processamento de arquivos ocorre antes dessa transacao. O lock tem
timeout de 15 segundos e cada comando SQL tem timeout de 10 minutos.

Cada carga tem identificador unico e status em `etl.cargas_dw`. Nao ha retry
automatico. Se a conexao falhar depois do inicio da transferencia, o log local
registra resultado `indeterminada`; nao afirma que ocorreu rollback nem transforma
um possivel commit concluido em erro. Antes de repetir, consultar o historico
da carga e reconciliar os dados. Esse tratamento sinaliza a incerteza; nao resolve
automaticamente uma queda de conexao durante commit.

Papel restrito `xfit_pipeline`, TLS `verify-full`, certificado validado e grants/RLS
existentes continuam obrigatorios. Nenhum grant foi ampliado nesta etapa.

## Verificacao reproduzivel

Suite local: `python -B -m unittest discover -s tests -v`.

O teste `tests/test_dw_local.py` usa exclusivamente o host Docker
`xfit-dw-verificacao`, database `xfit_dw_test`, e so executa com
`XFIT_TEST_DW_LOCAL=1`. Preparar um PostgreSQL 16 descartavel em uma rede Docker
interna com esse nome, sem publicar portas, e rodar o teste na imagem
`xfit-airflow:3.3.2` com o projeto montado em `/opt/xfit`. O teste nunca le o `.env`
do projeto. A conexao sem TLS existe somente nesse ambiente isolado de teste.

O teste de DAGs em `tests/test_airflow_dags.py` deve rodar na imagem Airflow.
Ele verifica importacao, independencia das tarefas por unidade, resumo `all_done`
e bloqueio da carga quando a verificacao de conexao falha.
