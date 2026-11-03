# Consulta periodica do Supabase

O workflow `.github/workflows/supabase-disponibilidade.yml` verifica o banco
diariamente, sem depender do computador local ou do Airflow. Pode ser executado
manualmente na pagina Actions do repositorio xFit-Wear.

O scheduler do GitHub acorda diariamente as 10:17 UTC (07:17 em Sao Paulo).
Toda execucao, agendada ou manual, consulta o Supabase. O filtro de cinco dias
foi removido em 02/11/2026 apos pausa por baixa atividade. Horarios dependem da
disponibilidade do GitHub; o horario do cron nao e garantia de inicio pontual.

## Consulta e permissoes

A migration `supabase/migrations/20261018175323_disponibilidade_xfit.sql` cria
`public.verificar_disponibilidade_xfit()`, uma funcao SECURITY INVOKER que retorna
somente o inteiro 1. Nao le nem altera tabelas, nao concede acesso ao DW e nao
executa a carga ETL. Execucao concedida somente ao papel anon; o acesso privado
dos schemas stg, etl e dw permanece bloqueado.

O Actions recebe apenas a chave **publicavel** do projeto, na variavel de
repositorio `SUPABASE_PUBLISHABLE_KEY`. Nao usa senha PostgreSQL, service_role,
access token administrativo ou GITHUB_TOKEN com escrita. O cliente exige o URL
HTTPS exato do projeto, impede redirects e confere resposta 200 com corpo 1.
Rotacao da chave publicavel exige atualizar a variavel no GitHub.

## Logs e falhas

O job registra o instante UTC, o tipo de disparo e o resultado HTTP 200/RPC 1
quando a consulta passa. Em falhas, termina com exit code 1 e anotacao `::error::`:

- HTTP 401: revisar a chave publicavel configurada no GitHub.
- HTTP 403: revisar permissoes da RPC e configuracao de acesso.
- HTTP 404: verificar disponibilidade do projeto e existencia/exposicao da RPC.
- HTTP 429: verificar limite de requisicoes.
- HTTP 5xx: verificar indisponibilidade, pausa ou restauracao do projeto.
- HTTP 3xx: redirecionamento bloqueado, revisar endpoint.
- Rede: distingue DNS, TLS e limite de tempo; demais erros recebem orientacao de
  conectividade. O timeout de cada chamada continua em 20 segundos.
- Configuracao invalida ou resposta diferente de 1: revisar variavel/URL ou RPC.

Essas orientacoes nao comprovam a causa de um status HTTP. Nao sao impressos
chave, headers, corpo da resposta ou texto bruto de excecoes. Consultar o painel
do Supabase para detalhes internos e restaurar o projeto se estiver pausado.

## Limites importantes

- A consulta e uma tentativa de gerar atividade, nao garantia contra pausa.
- O Supabase considera atividade suficiente na janela de sete dias; a documentacao
  cita algumas consultas diarias como normalmente suficientes. Uma consulta
  diaria ainda pode nao atingir o criterio. Somente o plano pago elimina a pausa
  automatica; nenhum upgrade foi contratado nesta etapa.
- Em repositorio publico, o GitHub desativa workflows agendados apos 60 dias sem
  atividade no repositorio. As execucoes do proprio cron nao substituem manutencao
  do repositorio. Reabilitar o workflow quando necessario e observar alertas.
- O job nao restaura um projeto pausado. Nesse caso, restaurar pelo painel e
  executar o teste manual novamente.

Fontes oficiais (regra de pausa reconsultada em 02/11/2026):

- https://supabase.com/docs/guides/platform/free-project-pausing
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## Verificacao

`python -B -m unittest discover -s tests -p test_keepalive_supabase.py -v` verifica
consulta em cada execucao, inclusive dias antes ignorados e viradas de mes,
disparo manual, bloqueio de destino/chave inadequados, resposta esperada,
classificacao segura das falhas e ausencia de permissoes/secrets de escrita.
O teste HTTPS real foi aprovado com chave publicavel depois de aplicar a migration.
Isso comprova a consulta, nao prevencao futura de pausas.

Primeiro teste no GitHub Actions aprovado em 2026-10-18, job consultar em 4s:
https://github.com/luisfelipedesa/xFit-Wear/actions/runs/39151977359
O log confirmou a resposta SQL esperada, nao apenas criacao/agendamento do workflow.

Alteracao de 02/11/2026 validada localmente com seis testes. Para alterar o cron
efetivo, publicar o workflow revisado no branch padrao do GitHub; a edicao local
nao modifica o agendamento remoto. Nao e necessario redeploy na AWS ou Vercel.
