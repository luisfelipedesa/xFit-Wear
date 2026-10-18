# Homologacao diaria no Airflow e Supabase

Data: 2026-10-18. Resultado: aprovado no escopo abaixo.

## Ambiente e criterio

Execucoes reais de `xfit_pipeline_diario` no scheduler/Celery worker do Docker
Desktop, com destino ao projeto xFit Wear no Supabase. Nao foi usado `dag.test`,
mock de banco, troca de credenciais ou escrita administrativa para publicar.
A conexao efetiva usa `xfit_pipeline` e TLS verificado pelo executor existente.

O lote principal recorta vendas demonstrativas de 2026-07-31 das fontes originais:
13 itens de Barbacena, 16 de Lafaiete e 16 do ecommerce. Sao 45 itens ja presentes
no historico, com receita liquida de R$ 6.246,85. Nao foram inventados pedidos,
alteradas datas de vendas ou reexecutado o gerador de fontes.

Antes dos disparos, foram exportadas as nove tabelas de stg/etl/dw para JSONL
protegido e conferidos hashes das copias. As fontes originais tambem receberam
hash para conferencia posterior. Os recibos de teste foram criados pelo operador
no host: o volume do inbox permanece somente leitura dentro do Airflow.

## Execucoes e resultados

Todos os run IDs comecam com `homologacao-diaria-20261018-`.

| Sufixo | Referencia | Publicar DW | Resultado observado |
|---|---|---|---|
| validar | 2026-07-31 | false | Nove tasks success; tres lotes aprovados; nenhum registro novo no DW/etl |
| publicar | 2026-07-31 | true | Nove tasks success; recebimentos selecionados explicitamente; carga diaria sucesso |
| repetir | 2026-07-31 | true | Nove tasks success; lotes reutilizados; nenhum item ou registro de carga duplicado |
| ausente | 2026-07-30 | true | Falha intencional em receber_barbacena; outras unidades recebidas/tratadas; DW bloqueado |
| zero | 2026-08-01 | true | Nove tasks success; tres recibos explicitos sem movimento; nenhuma venda artificial |

Na ausencia, Lafaiete entregou 16 itens e ecommerce 19, ambos aprovados. As tasks
`aprovar_dia` e `publicar_dia` ficaram `upstream_failed`, sem serem executadas.
O run vermelho desse cenario e o resultado esperado do teste negativo, nao uma
falha a ser limpa para forcar sucesso. Nenhuma carga `dw-diario-20260730` nasceu.

No zero, a data e um cenario demonstrativo explicitamente declarado pelo operador;
nao e inferencia automatica de que domingo ou ausencia de registros significa zero.

## Conferencia e preservacao

- Snapshot inicial: 71.575 itens, 277 metas, 12 produtos, 3 unidades e 2.983 dias.
- Apos os cinco cenarios: mesmos volumes e receita liquida global R$ 8.782.224,66.
- Igualdade de conteudo verificada por hash canonico de todos os registros das
  oito tabelas de negocio, nao somente por contagem/soma. Excluidos somente
  `criado_em`, `atualizado_em` e `data_processamento`, que sao metadados tecnicos.
- Os cinco registros anteriores de `etl.cargas_dw` permaneceram intactos;
  somente `dw-diario-20260731` e `dw-diario-20260801` foram acrescentados, ambos
  com status sucesso. A repeticao usa o mesmo registro diario.
- Antes de publicar, um preflight com COPY temporario, precisao e confronto com
  a staging remota confirmou os 45 itens sem alterar tabelas persistentes.
- Manifestos, recibos, snapshots de referencias e hashes foram relidos e
  conferidos; fontes originais e backup inicial permaneceram intactos.
- As tasks bem-sucedidas registraram o hostname do worker real. Ao terminar,
  nao havia tasks ativas/enfileiradas, e a DAG voltou ao estado pausado original.

## Evidencias locais protegidas

Arquivos fora do Git:

- `data/processed/backups/homologacao-diaria-20261018/`: exportacoes JSONL iniciais.
- `data/processed/dw/homologacao-diaria-20261018/antes.json`: hashes, volumes e entregas.
- `data/processed/dw/homologacao-diaria-20261018/preflight.json`: aprovacao antes da carga.
- `data/processed/dw/homologacao-diaria-20261018/runs.jsonl`: estados, horarios e worker por task.
- `data/processed/dw/homologacao-diaria-20261018/resultado.json`: reconciliacao final.
- Recibos, copias recebidas e staging diaria nos diretorios operacionais existentes.

Os runs tambem podem ser consultados na interface Airflow pelo DAG e run ID.

## Limites e proxima etapa

Comprovados remotamente: orquestracao, selecao de lotes, publicacao/reprocessamento
de dados existentes, idempotencia, isolamento da unidade ausente, barreira conjunta
e zero declarado. Nao foi comprovada nesta rodada a inclusao remota de pedidos
novos em uma data inedita; esse caminho tem testes em PostgreSQL descartavel.
Nao foi executada restauracao do novo backup, apenas exportacao e integridade.

Nenhuma periodicidade comercial foi ativada. O cron GitHub de disponibilidade e
independente das cargas. Proxima fatia funcional: definir e criar views privadas
de indicadores para consumo analitico, antes do dashboard.
