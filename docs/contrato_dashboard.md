# Dashboard comercial - contrato v1

Data: 2026-10-18. Escopo: definicoes, camada SQL privada e verificacao; nao inclui
interface, credencial de login, autenticacao de usuario final ou deploy.

## Primeira pagina e filtros

Pagina: **Visao Geral Comercial**. Ordem de leitura:

1. Aviso de cobertura dos dados e ultima execucao da carga.
2. Filtros: intervalo de datas inclusivo, unidades e canais; categoria unica ou Todas.
3. Cards: receita de vendas concluidas, margem em R$/%, pedidos concluidos,
   unidades vendidas e ticket medio. Meta/atingimento em bloco proprio.
4. Evolucao diaria da receita, comparacao mensal por unidade e mix de categorias.
5. Tabela por unidade com os mesmos numeradores/denominadores dos cards.

Periodo inicial: ultimo mes com vendas registradas, nao mes atual do computador.
Na base demonstrativa atual, julho/2026. Unidade/canal/categoria iniciam em Todas.
Datas, unidade e canal afetam todos os indicadores compativeis. Categoria e
**selecao unica** na v1; nao implementar multisselecao usando soma de pedidos.

Com categoria selecionada, o card usa exclusivamente a view por categoria;
sem categoria, usa a view diaria geral. Nao somar categorias para reconstruir
pedidos totais: um mesmo pedido pode conter produtos de categorias diferentes.
O grafico de mix usa receita/unidades, nao soma de pedidos por categoria.
Categorias sao as do cadastro dimensional atual; o modelo nao guarda versoes
historicas do cadastro para reconstituir categorias vigentes na data da venda.

## Regras dos indicadores

As regras abaixo sao a definicao operacional inicial da v1, nao uma nova regra
contabil de reconhecimento de receita. Alteracoes exigem revisao do contrato.
Valores financeiros permanecem numeric/Decimal; arredondar somente na exibicao.

| Indicador | Formula e escopo |
|---|---|
| Receita liquida registrada | Soma de valor_liquido de todas as linhas; reconcilia com o DW |
| Receita de vendas concluidas | Soma de valor_liquido somente com status concluida; card principal |
| Receita devolvida registrada | Soma positiva de valor_liquido em devolvida; informacao separada, nao estorno |
| Margem bruta R$ | Soma de margem_bruta somente das concluidas |
| Margem bruta % | 100 * margem das concluidas / receita das concluidas |
| Pedidos totais | COUNT DISTINCT do par (fonte, id_venda), incluindo os tres status |
| Pedidos concluidos | Mesma identidade, somente concluida; card de pedidos |
| Itens vendidos | SUM(quantidade) das concluidas; nao e quantidade de linhas |
| Ticket medio | Receita das concluidas / pedidos concluidos |
| Taxa de devolucao | 100 * pedidos devolvidos / (pedidos concluidos + devolvidos) |
| Taxa de cancelamento | 100 * pedidos cancelados / pedidos totais |
| Atingimento da receita | 100 * receita concluida registrada no mes / meta mensal da unidade |

Canceladas nao entram em receita/margem/pedidos concluidos/itens vendidos, mas
participam dos pedidos totais e da taxa de cancelamento. A fonte ja zera receita
e margem canceladas; o custo original da cancelada nao deve reduzir a margem
do card. Devolvidas mantem valores positivos na fonte: nao inventar receita
negativa, devolucao financeira, data de estorno ou saldo de estoque inexistentes.
O dashboard deve rotular explicitamente a receita principal como de concluidas.

Divisao por zero retorna NULL: exibir travessao/"nao aplicavel", nao 0% nem infinito.
Na agregacao de varios dias/unidades, somar os numeradores e denominadores e so
entao dividir. Nunca fazer AVG(ticket_medio), AVG(margem_pct) ou AVG(atingimento).

Somas de pedidos entre dias/unidades dependem da invariante validada pelo ETL:
o par fonte/id_venda pertence a uma unica data/unidade/status. Pedido com varios
produtos e valido; cabecalho divergente e bloqueado antes do DW. Se a origem
passar a representar devolucao parcial ou mudanca de status por item, revisar o
grao e estas regras antes de usar os mesmos totais.

## Metas sem multiplicacao

Meta tem grao unidade/mes, sem categoria. Vendas sao agregadas antes do join.
A view mensal faz full join: mantem meta sem vendas e vendas sem meta.

- Card de meta so fica ativo sem filtro de categoria e com selecao de meses
  inteiros. Periodo parcial continua mostrando vendas, mas desabilita comparacao
  de meta no dashboard; nao existe rateio diario aprovado.
- Categoria selecionada: meta e atingimento ficam "nao disponivel neste filtro".
- Meta zero/ausente: atingimento NULL; ausencia de meta e sinalizada por tem_meta.
- Mes com meta e sem registros: receita registrada zero, tem_registros_vendas=false,
  atingimento NULL. Isso nao comprova ausencia de movimento nem desempenho ruim.
- Para varias unidades/meses, somar uma vez cada meta selecionada e dividir a
  receita total pela meta total. Meta de margem/devolucao e armazenada como fracao
  na fonte (0.48 = 48%); as views convertem para percentual exibivel.

## Views e contrato de consumo

| View privada | Grao / uso |
|---|---|
| bi.vw_vendas_diarias | Data/unidade/canal, sem categoria; cards gerais e evolucao |
| bi.vw_vendas_diarias_categoria | Data/unidade/canal/categoria; filtro unico e mix |
| bi.vw_metas_mensais | Unidade/mes; metas originais sem join com itens |
| bi.vw_desempenho_mensal | Unidade/mes; venda agregada e meta preservada |
| bi.vw_atualizacao | Uma linha; cobertura das vendas e situacao operacional conhecida |

`bi.vw_vendas_agrupadas` e interna, sem SELECT para o consumidor. GROUPING SETS
centraliza as regras e conta pedidos distintamente no nivel geral e por categoria.
Nenhuma view de consumo retorna cliente_id, id_venda, pedido_online_id ou credenciais.
Aplicar filtros com parametros SQL, nunca concatenando texto de entrada do usuario.

## Atualizacao e completude

Exibir separadamente:

- ultima_data_venda: maximo de data com vendas, nao data da execucao;
- ultima_execucao_sucesso: ultima carga concluida, que pode ser reprocessamento;
- ultima_data_diaria_publicada: data do contrato diario aprovado, inclusive zero;
- cargas_sem_conclusao e cargas_com_erro: sinais operacionais, nao novos movimentos.

A completude por unidade/data esta nos manifestos do lake, nao numa tabela SQL
consumivel por esta camada. Portanto completude_datalake_disponivel e
completude_periodo_comprovada permanecem false; nao afirmar "dados completos".
O aviso textual foi substituido pelo farol autorizado em 28/10, descrito abaixo.
Nao adotar SLA de
atraso arbitrario antes de definir horario esperado das entregas. Dados historicos
de portfolio terminando em julho nao representam vendas atuais em outubro.

## Acesso somente de leitura

Dois papeis distintos, ambos NOLOGIN, NOSUPERUSER, NOBYPASSRLS:

- xfit_bi_owner: dono das views privadas; SELECT limitado a dimensoes/fatos e
  tres colunas de etl.cargas_dw, com policies exclusivamente de leitura. Nao e
  dono das tabelas nem recebe escrita, e nao usa xfit_pipeline.
- xfit_dashboard: apenas USAGE de bi e SELECT nas cinco views de consumo.
  Sem acesso direto a stg/etl/dw, a view interna ou ao papel owner.

As views usam explicitamente security_invoker=false e security_barrier=true.
E uma fronteira intencional de agregacao em schema privado: executam com o owner
limitado, sujeito a RLS, nao com postgres. security_invoker=true exigiria conceder
as tabelas subjacentes ao consumidor, contrariando o isolamento desejado aqui.
Nao expor bi na Data API nem conceder acesso a anon/authenticated. O teste local
altera a policy do owner para false e confirma que a view deixa de retornar dados.

Login do backend, senha em secret manager e TLS terao configuracao propria na
etapa da interface. Nao foi criada senha nem alterada .env. NOLOGIN nao e uma
conexao pronta para a aplicacao. Jamais usar a senha do pipeline ou service_role
no navegador, no dashboard ou como substituto dessa etapa. Autenticacao do usuario
final e autorizacao de acesso ao backend continuam separadas destas roles SQL.

Na migration, o administrador recebe SET ROLE do owner apenas durante a criacao
dos objetos, sem heranca de privilegios. Ao final, SET e desligado. O validador
habilita SET ROLE de xfit_dashboard somente dentro da transacao de teste e o
ROLLBACK desfaz essa habilitacao. Nao ha membresia do consumidor no owner/pipeline.

## Aceite e verificacao

`tests/test_dashboard_sql.py` usa fixtures em PostgreSQL descartavel. Um pedido
com produtos em duas categorias, outro pedido com mesmo ID em outra fonte,
devolucao e cancelamento resultam em receita registrada 170, concluida 140,
margem 90, quatro pedidos totais, dois concluidos, quatro unidades e ticket 70.
Meta mensal 100 aparece uma vez, com realizado 90 e atingimento 90%.

Cobertura: filtros, denominadores, zero/NULL, meta ausente/zero, categoria nao
aditiva, nao multiplicacao de metas, RLS do owner e sessao nao administrativa
negando bases, escrita e escalada. `sql/validar_dashboard.sql` reconcilia a base
efetiva e testa leitura permitida/negada com rollback. Resultados executados
devem ser registrados em docs/operacao_producao.md, sem afirmar uso em producao.

Verificacao em 2026-10-18: migration 20261018183526 aplicada no Supabase;
137 testes locais executados (133 aprovados e quatro remotos opt-in ignorados).
Validador SQL aprovado localmente e no remoto, com rollback, e Security Advisor
sem alertas. Oito tabelas de negocio preservadas por comparacao de hash canonico.
Essas evidencias validam a camada de consumo, nao uma interface em producao.

Referencia remota de julho/2026, apos aplicar as views: receita concluida
R$ 153.960,75, meta R$ 206.574,40, 1.138 pedidos concluidos, 1.420 unidades,
ticket R$ 135,29 e atingimento 74,53%. Sao resultados demonstrativos da base
existente, nao indicadores de uma operacao comercial comprovada.

## Proxima fatia

Construir a primeira tela somente apos escolher biblioteca Python e confirmar
compatibilidade de hospedagem com o deploy pretendido. Streamlit/Dash e uma
aplicacao Python persistente nao devem ser tratados automaticamente como deploy
nativo na Vercel. Nao houve escolha de framework na etapa de definicoes.
Em pedido posterior de 18/10/2026, o usuario escolheu Streamlit na AWS e pagina
estatica na Vercel. Implementacao local em `dashboard/`; operacao descrita em
`docs/deploy_dashboard.md`. Deploy explicitamente suspenso por ordem do usuario
ate nova autorizacao, enquanto a interface passa por ajustes.

## Ajuste autorizado: comparativo anual e apresentacao pt-BR

Em 18/10/2026, usuario solicitou comparativo anual inclusive de metas,
devolucoes em dashboard, informacoes em portugues brasileiro e retirada da
frase final do rodape. Implementacao na interface, sem alteracao de SQL/DW.

- Filtro Anual seleciona janeiro a dezembro do ano informado; soma cada meta
  mensal/unidade uma vez. Realizado e a soma das vendas concluidas registradas.
- Quando ha registros em parte do ano e metas completas nos 12 meses, mostrar
  realizado registrado / meta anual integral. Meses futuros/sem registros nao
  bloqueiam o comparativo, nem viram prova de movimento zero ou de completude.
  Sinalizar explicitamente a cobertura parcial; nao projetar nem ratear metas.
- Periodo inteiro sem registros mantem atingimento nao aplicavel. Metas
  ausentes/zero mantem as protecoes existentes; categoria ou mes parcial nao
  habilitam meta sem grao/criterio de rateio aprovado.
- Graficos apresentam realizado x meta por unidade, no grao anual ou mensal.
  Devolucoes/cancelamentos possuem indicadores e graficos proprios, usando os
  mesmos filtros e denominadores. A data continua sendo a da venda, nao uma
  data de devolucao financeira inexistente na origem.
- Rotulos, nomes visuais, datas, valores, eixos e dicas dos graficos em pt-BR.
  Menus tecnicos de graficos ocultados; tabela simples sem barra em ingles.
  Filtros de datas textuais DD/MM/AAAA e selecao de unidades/canais em portugues.
  Rodape solicitado removido, sem retirar avisos de cobertura dos dados.

## Interacao por clique — 28/10/2026

- Clicar numa categoria aplica essa categoria ao painel. Unidades e periodo
  vigentes permanecem; metas ficam indisponiveis conforme a regra existente.
- Clicar numa barra de receita/meta por unidade seleciona a unidade, seu canal
  e o periodo da barra, limitado ao intervalo ja escolhido. Em devolucoes por
  unidade, muda somente unidade/canal. As selecoes combinam-se com a categoria.
- Clicar num ponto das evolucoes de receita/devolucao restringe ao dia da venda,
  inclusive saindo do modo anual. Nao representa data do evento de devolucao.
- Filtros laterais acompanham os cliques. Limpar filtros restaura o mes da
  ultima venda, todas as unidades/canais e todas as categorias. Selecao e local
  a sessao do usuario; consultas continuam parametrizadas e somente leitura.
- Pedidos por situacao permanece comparativo, sem filtro por status, para nao
  alterar os denominadores das taxas. Cards e tabela tambem nao disparam filtro.
- Verificacao local em 28/10: 28 testes focados aprovados em Python 3.12/Windows,
  Streamlit 1.66.0 e Altair 6.3.0. Cliques reais no navegador: Leggings,
  Barbacena + Leggings e 13/09/2026 conferidos com o DW. Deploy segue suspenso.

## Apresentacao para deploy — 28/10/2026

Pedido posterior remove o subtitulo INTELIGENCIA COMERCIAL / VISAO GERAL e o
banner de previa local da interface. Unidade EC-BR passa a ser exibida como
Ecommerce nos filtros, legendas, resumos e tabela, sem alterar o identificador.
Cada grafico ocupa sua propria linha com a largura disponivel; cards mantem
seus agrupamentos. Controles de acesso, regras analiticas e filtros por clique
permanecem. Essa revisao visual nao publica a aplicacao.

## Farol de alinhamento das cargas — 28/10/2026

Regra explicita do usuario para esta etapa: considerar validado quando todas
as fontes terminarem na mesma data. Substitui o aviso textual de completude;
nao adota D-1 nem compara com a data final dos filtros.

- Verde / Atualizada: todas as tres fontes esperadas presentes com a mesma
  data final disponivel no DW, mesmo se for uma base historica.
- Vermelho / Data final divergente: data anterior a mais recente do conjunto.
- Amarelo / Aguardando demais cargas: data mais recente, mas outras fontes
  divergentes ou sem data. Nenhuma fonte fica verde enquanto faltar alinhamento.
- Cinza / Sem data disponivel: unidade esperada ausente ou sem registros.

Data final e max(data_venda) da view privada bi.vw_vendas_diarias por unidade,
sem filtro comercial. Inclui vendas de todas as situacoes, nao so concluidas.
Esta e uma verificacao de alinhamento das datas dos dados disponiveis, nao de
completude dos recibos nem de dias declarados sem movimento. Nao confundir a
data de negocio com a hora da ultima execucao. Sem novos grants ou migrations.

## Acesso publico ao portfolio — 28/10/2026

Pedido posterior do usuario autoriza visitantes sem login a ler os indicadores
do DW sintetico. O servidor exige `XFIT_DASHBOARD_PUBLIC=1` para esse modo;
parametros de URL nao ativam acesso publico. Interface identifica os dados como
demonstrativos. Credencial BI e TLS permanecem no servidor, views de leitura
privadas e sem permissao de escrita/bases internas. Regras analiticas e filtros
permanecem; apenas a exigencia de login dos visitantes foi substituida.
