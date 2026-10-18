# Contrato do tratamento diario - v1

Data: 2026-10-18.
Estado: implementado por `src/tratar_diario.py`, `src/carregar_diario_postgres.py`
e `xfit_pipeline_diario`, com testes isolados. Nao libera cargas parciais no DW.
Integracao remota homologada para reprocessamento controlado, ausencia e zero;
ver `docs/homologacao_pipeline_diario.md` para escopo e evidencias.

## Resultado e escopo

Transformar entregas confirmadas do lake em lotes de staging diarios aprovados,
com origem rastreavel e reprocessamento sem duplicacao.

O recebimento permanece independente por unidade. A publicacao no DW
continua exigindo o conjunto completo selecionado para a data. Ausencia de uma
unidade nao desfaz as entregas das demais, mas impede publicar o dia incompleto.

Leitura das particoes, persistencia da staging e integracao diaria no Airflow/DW
implementam as regras abaixo. A carga historica continua com seu contrato proprio.

## Decisoes iniciais

| Assunto | Regra v1 | Motivo |
|---|---|---|
| Escopo do arquivo | Retrato completo de uma unidade/data | O recibo atual informa data e volume total; nao descreve operacoes incrementais |
| Recebimento | Independente por unidade | Requisito do usuario |
| Sem movimento | Arquivo estruturado e recibo explicito de zero | Ausencia nao comprova dia sem vendas |
| Repeticao identica | Reutilizar lote aprovado, sem acrescentar linhas | Evitar duplicacao |
| Conteudo diferente para unidade/data ja aprovada | Revisao necessaria; preservar anterior | Politica comercial de correcao ainda nao escolhida |
| Remocoes | Nenhuma exclusao automatica | Fora do contrato atual do DW |
| Publicacao no DW | Todas as unidades esperadas aprovadas | Isolamento solicitado somente na alimentacao do lake |

A regra conservadora de correcao e uma protecao inicial da especificacao, nao uma
decisao de que toda correcao futura sera substituicao integral. Antes de automatizar
correcoes, definir substituicao do dia ou alteracoes incrementais, incluindo o
tratamento dos registros que desaparecerem da nova entrega.

## Identidade e selecao

Cada candidato corresponde a uma unidade/data e a um recebimento explicitamente
selecionado. Nao escolher automaticamente pela pasta mais recente, mtime ou run_id.

| Unidade | unidade_id | fonte na staging |
|---|---|---|
| barbacena | LJ-BQ | vendas_barbacena |
| lafaiete | LJ-CL | vendas_conselheiro_lafaiete |
| ecommerce | EC-BR | vendas_ecommerce |

Registrar versao do contrato/tratamento, unidade/data, carga_id do tratamento,
carga_id do recebimento, caminho relativo e SHA-256 bruto, snapshots de produtos
e metas com hashes, e arquivos de saida com hashes quando aprovados.

Data de referencia explicita em YYYY-MM-DD. Rejeitar datas futuras pelo dia civil
de America/Sao_Paulo; permitir datas passadas em reprocessamento controlado.
Nao inferir sem movimento por domingo/feriado: nao ha calendario operacional
aprovado para dispensar automaticamente a entrega.

## Entradas e proveniencia

Ler a copia confirmada em
`data/raw/recebimentos/<unidade>/<data_referencia>/<carga_id_recebimento>/`,
acompanhada do recibo e do relatorio de alimentacao correspondente.

Antes de tratar, exigir:

1. Status de recebimento recebida ou sem_movimento.
2. Unidade/data/carga consistentes entre selecao, relatorio e recibo.
3. Arquivo regular em caminho autorizado, sem redirecionamento por link.
4. Hash e volume efetivos iguais aos declarados.
5. Conteudo imutavel durante a leitura, ou nova conferencia de hash ao termina-la.

Arquivo isolado no inbox, pasta parcial ou copia sem confirmacao nao e entrada
aprovada. Hash comprova correspondencia de conteudo, nao autenticidade do remetente
nem completude do sistema de origem.

Produtos/metas sao referencias compartilhadas. Usar inicialmente as fontes de
`config/data_sources.json`, fixadas em snapshots conferidos por hash. Nao trocar
cadastro no meio da execucao. Uma publicacao diaria deve usar referencias e versoes
compativeis entre suas unidades. Referencia ausente/invalida bloqueia a aprovacao.

## Padronizacao e qualidade

Reutilizar as funcoes de dominio de `src/staging_data.py` e as regras aplicaveis
de `src/validate_staging.py`. O validador historico nao pode ser aplicado sem
adaptacao: exige todas as fontes e volumes positivos, diferentes de um lote diario
explicitamente sem movimento.

Para vendas com movimento, exigir os campos consumidos pelo padronizador atual:
id_venda, data_venda, hora_venda, cliente_id, produto_id, quantidade, valor_bruto,
valor_desconto, valor_liquido, custo_total, margem_bruta, status_pedido e canal.
Lojas fisicas exigem loja_id; ecommerce exige pedido_online_id conforme o contrato
atual de extracao. Campos opcionais seguem o padronizador existente.

O recebimento aceita estrutura minima para identificar unidade/data; isso nao
dispensa os demais campos no tratamento. Recebido nao significa aprovado.

Invariantes:

- Datas/horas validas, quantidade inteira positiva e numeros finitos.
- Dinheiro em Decimal, sem passar por float; quantidade fracionaria nao e truncada.
- Ecommerce permanece EC-BR; local de entrega nao cria unidade operacional.
- Chave provisoria: fonte + id_venda + produto_id. Pedido com produtos distintos
  e permitido; chave repetida e cabecalho divergente no mesmo pedido sao erros.
- Nao deduplicar silenciosamente nem incluir a data na chave para esconder colisao.
- Chave reaparecendo em outro dia com cabecalho divergente exige revisao; nao mover
  nem duplicar automaticamente a venda.
- Produto vendido cadastrado, cadastro sem produto_id duplicado e meta unica para
  unidade/mes. Meta nao e multiplicada pelo numero de itens vendidos.
- Status: concluida, devolvida ou cancelada; canais coerentes com a unidade.
- Bruto, desconto, liquido e custo nao negativos. Cancelada tem liquido/margem zero.
- Para nao canceladas: margem = liquido - custo, tolerancia de R$ 0,02 por linha;
  custo respeita o minimo cadastral da regra atual.
- Desvio acumulado de margem, por fonte/canal/unidade/mes e no total:
  soma das diferencas absolutas <= max(R$ 1,00, 0,0001 * abs(receita liquida)).

As formulas e identidades atuais sao a referencia de corretude. Alteracao comercial
exige revisao do contrato. Um erro reprova o lote inteiro da unidade/data; nao
descartar linhas ruins e aprovar o restante como entrega completa.

## Zero movimento

Aceitar zero somente com recibo valido, sem_movimento=true, volume zero, estrutura
e hash corretos. O lote pode ser aprovado com linhas_saida=0, preservando a
declaracao e as referencias usadas. Nao criar venda artificial de valor zero.

Nova declaracao vazia para dia anteriormente aprovado com vendas exige revisao;
nao apaga dados. Se as tres unidades declararem zero corretamente, o dia e completo
no tratamento. Sua aplicacao ao DW usa a integracao diaria: nao chamar o
executor historico com uma carga historica vazia.

## Saida e publicacao

Destino implementado:
`data/processed/staging_diaria/<unidade>/<data_referencia>/<carga_id_tratamento>/`.

O lote aprovado deve conter `stg_vendas.jsonl` e `manifesto.json`. Dinheiro deve
ser serializado como texto decimal exato e restaurado como Decimal na leitura.
Zero movimento produz staging sem registros, nao linhas artificiais.

Manifesto: proveniencia, versoes, status, sem_movimento, linhas_entrada/saida,
hashes, verificacoes de qualidade e totais financeiros. Entrada = saida = volume
declarado. Nao e uma pasta de dimensoes/fatos nem substitui o DW SQL.

Gravar em destino exclusivo e publicar o manifesto aprovado por ultimo, depois da
conferencia do conteudo. Pasta parcial nunca e consumivel. Falha preserva versoes
anteriores; nova tentativa usa outro identificador sem limpeza destrutiva.

XCom transporta identificadores/referencias pequenas. Dados e detalhes protegidos
ficam fora do Git; logs publicos informam regra/contagem sem reproduzir linhas,
cliente_id, credenciais ou mensagens brutas de erro.

## Repeticao, atrasos e correcoes

Identidade reutilizavel: unidade/data + hash bruto + hashes das referencias +
versao do contrato + versao do tratamento. Run_id e horario de processamento nao
transformam o mesmo conteudo em novo movimento comercial.

| Cenario | Resultado |
|---|---|
| Primeira entrega valida | Tratar e publicar lote aprovado |
| Mesmo conteudo/referencias/versoes ja aprovados | Reutilizar lote e vincular nova tentativa; nao somar linhas |
| Tentativa anterior falhou sem aprovacao | Permitir nova tentativa identificada, preservando anterior |
| Conteudo diferente para unidade/data ja aprovada | revisao_necessaria; manter anterior, sem selecionar ultima versao automaticamente |
| Mudou referencia ou versao do tratamento | Nao reutilizar aprovacao antiga; exigir reavaliacao controlada |
| Entrega atrasada de dia pendente | Tratar a data declarada, sem substitui-la pela data de execucao |
| Arquivo novo omite item anterior | Revisao; omissao nao vira DELETE |

Estados previstos: aprovado, reprovado, pendente, revisao_necessaria e reutilizado.
Reutilizado aponta para aprovacao com identidade compativel; nao e nova aprovacao.
Politica de substituicao/exclusao automatica fica fora da v1.

## Barreira para o DW

Exigir selecao explicita de lotes aprovados ou reutilizados para LJ-BQ, LJ-CL e
EC-BR, com versoes/referencias compativeis, inclusive zero declarado valido.
Pendente, reprovado ou revisao_necessaria impede publicacao conjunta da data.

Isso nao desfaz recebimentos nem altera o historico ja publicado. Nao concatenar
diarios ao historico atual sem consolidacao: poderia duplicar itens ou tratar
correcoes como novas vendas.

O DW recebe o conjunto aprovado e conserva chaves/FKs, transacao, concorrencia
e reconciliacao de transferencia. Nao precisa recalcular qualidade comercial.
A carga diaria consome o lote aprovado, sem chamar novamente o
preparo historico sobre fontes diferentes.

## Criterios de aceite da implementacao

Exemplos abaixo sao ilustrativos; nao sao metricas do dataset do projeto.

| ID | Entrada/acao | Esperado |
|---|---|---|
| TD01 | Uma unidade ausente, duas entregues | Preservar as duas; data nao publicavel no DW |
| TD02 | Zero declarado, estrutura/hash corretos | Aprovado, zero linhas, nenhuma venda artificial |
| TD03 | Arquivo vazio sem declaracao de zero | Reprovado; anterior preservado |
| TD04 | Tres itens, dois produtos do mesmo pedido | Tres itens; aquele pedido contado uma vez |
| TD05 | Mesma fonte/pedido/produto duas vezes | Reprovar inteiro, sem deduplicacao silenciosa |
| TD06 | Liquido 30, custo 10, margem 20 | Margem aprovada |
| TD07 | Liquido 30, custo 10, margem 20,03 | Reprovar diferenca de R$ 0,03 |
| TD08 | Receita do grupo 1.000, desvio absoluto 1,01 | Reprovar: limite max(1, 0,10) = R$ 1,00 |
| TD09 | Repetir tres itens com mesmos hashes/versoes | Reutilizar tres; nunca produzir seis |
| TD10 | Dia aprovado com tres itens, nova entrega com dois | Revisao; manter anterior ate decisao |
| TD11 | Mesmo bruto, cadastro com novo hash | Reavaliar; nao reutilizar aprovacao antiga |
| TD12 | Arquivo/snapshot mudou depois da selecao | Bloquear por hash divergente |
| TD13 | Falha depois da escrita, antes de aprovar manifesto | Pasta nao consumivel; anterior intacto |
| TD14 | Tres unidades aprovadas, uma com zero valido | Elegivel para futura publicacao conjunta |
| TD15 | Registro de outra unidade/data ou futuro | Reprovar, sem alterar unidade/data para encaixar |
| TD16 | Quantidade fracionaria/bool, NaN ou Infinity | Reprovar sem truncar ou converter silenciosamente |
| TD17 | Produto sem cadastro ou unidade/mes sem meta | Reprovar antes do DW |
| TD18 | Caminho externo/redirecionado por link | Bloquear acesso/publicacao |
| TD19 | Tres unidades com zero valido | Dia completo; nao chamar executor historico vazio |
| TD20 | Chave de item em outro dia com cabecalho divergente | Conflito; nao duplicar nem mover automaticamente |

Usar fixtures demonstrativas isoladas. Comparar registros, tipos, totais e hashes;
contagem igual sozinha nao prova conteudo igual. Nas falhas, verificar integridade
dos artefatos anteriores.

## Evidencia desta etapa

Implementado: tratamento diario, reuso de aprovacao identica, snapshots de
referencias, manifestos por ultimo, barreira completa e publicacao transacional
append-only. Novo conteudo/referencia para unidade/data aprovada exige revisao;
nao implementa substituicao ou exclusao automatica.

Verificacao: TD01-TD20 exercitados em `tests/test_tratar_diario.py`; grafo e
funcoes das tasks executando CLIs reais em `tests/test_airflow_dags.py`;
lake -> tratamento -> DW, idempotencia, zero, precisao, conflito e rollback
em `tests/test_dw_diario_local.py`, usando PostgreSQL descartavel.
No teste de banco, somente a verificacao de TLS/papel da conexao e o log local
sao substituidos: as operacoes SQL rodam efetivamente como `xfit_pipeline`.
Isso nao comprova TLS remoto por si so. Posteriormente, a conexao real restrita
com TLS e as execucoes pelo scheduler/worker foram verificadas na homologacao.

Operacao e parametros: `docs/fluxos_airflow.md`. Agendamento automatico,
correcoes/exclusoes automaticas, adaptadores externos e recuperacao automatica
apos commit indeterminado permanecem fora da v1. Nenhuma credencial foi alterada.
