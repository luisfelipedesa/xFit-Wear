# Consulta periodica do Supabase

O workflow `.github/workflows/supabase-disponibilidade.yml` verifica o banco a cada
cinco dias, sem depender do computador local ou do Airflow. Pode ser executado
manualmente na pagina Actions do repositorio xFit-Wear.

O scheduler do GitHub acorda diariamente as 10:17 UTC (07:17 em Sao Paulo).
O codigo so acessa o Supabase quando a diferenca em dias desde 2026-10-18 e
multipla de cinco. Isso preserva o intervalo nas viradas de mes; `*/5` no dia do
mes nao representa um intervalo constante. Proximos acessos: 23/10, 28/10 e 02/11.
Disparo manual ignora esse filtro. Horarios dependem da disponibilidade do GitHub.

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

## Limites importantes

- A consulta e uma tentativa de gerar atividade, nao garantia contra pausa.
- O Supabase considera atividade suficiente na janela de sete dias; a documentacao
  cita algumas consultas diarias como normalmente suficientes. Um acesso a cada
  cinco dias pode nao atingir o criterio. Somente o plano pago elimina a pausa
  automatica; nenhum upgrade foi contratado nesta etapa.
- Em repositorio publico, o GitHub desativa workflows agendados apos 60 dias sem
  atividade no repositorio. As execucoes do proprio cron nao substituem manutencao
  do repositorio. Reabilitar o workflow quando necessario e observar alertas.
- O job nao restaura um projeto pausado. Nesse caso, restaurar pelo painel e
  executar o teste manual novamente.

Fontes oficiais consultadas em 2026-10-18:

- https://supabase.com/docs/guides/platform/free-project-pausing
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## Verificacao

`python -B -m unittest discover -s tests -p test_keepalive_supabase.py -v` verifica
intervalos por 400 dias, disparo manual, bloqueio de destino/chave inadequados,
resposta esperada e ausencia de permissoes/secrets de escrita no workflow.
O teste HTTPS real foi aprovado com chave publicavel depois de aplicar a migration.
Isso comprova a consulta, nao prevencao futura de pausas.

Primeiro teste no GitHub Actions aprovado em 2026-10-18, job consultar em 4s:
https://github.com/luisfelipedesa/xFit-Wear/actions/runs/39151977359
O log confirmou a resposta SQL esperada, nao apenas criacao/agendamento do workflow.
