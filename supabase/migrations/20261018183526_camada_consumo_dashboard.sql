create role xfit_bi_owner nologin nosuperuser nocreatedb nocreaterole
    noinherit noreplication nobypassrls;
create role xfit_dashboard nologin nosuperuser nocreatedb nocreaterole
    noinherit noreplication nobypassrls;

grant xfit_bi_owner to current_user with inherit false;
grant xfit_bi_owner to current_user with set true;

create schema bi authorization xfit_bi_owner;
set local role xfit_bi_owner;
revoke all on schema bi from public, anon, authenticated;
grant usage on schema bi to xfit_dashboard;
reset role;
grant usage on schema dw, etl to xfit_bi_owner;
grant select on dw.dim_data, dw.dim_produto, dw.dim_unidade,
    dw.fato_vendas, dw.fato_metas to xfit_bi_owner;
grant select (carga_dw_id, status, atualizado_em) on etl.cargas_dw to xfit_bi_owner;

create policy bi_leitura on dw.dim_data for select to xfit_bi_owner using (true);
create policy bi_leitura on dw.dim_produto for select to xfit_bi_owner using (true);
create policy bi_leitura on dw.dim_unidade for select to xfit_bi_owner using (true);
create policy bi_leitura on dw.fato_vendas for select to xfit_bi_owner using (true);
create policy bi_leitura on dw.fato_metas for select to xfit_bi_owner using (true);
create policy bi_leitura on etl.cargas_dw for select to xfit_bi_owner using (true);

set local role xfit_bi_owner;

create view bi.vw_vendas_agrupadas
with (security_barrier = true, security_invoker = false) as
select
    calendario.data as data_venda,
    calendario.ano_mes,
    unidade.unidade_id,
    unidade.unidade,
    unidade.canal,
    produto.categoria,
    grouping(produto.categoria) as agrupamento_categoria,
    count(*) as linhas_registradas,
    count(distinct (venda.fonte, venda.id_venda)) as pedidos_total,
    count(distinct (venda.fonte, venda.id_venda))
        filter (where venda.status_pedido = 'concluida') as pedidos_concluidos,
    count(distinct (venda.fonte, venda.id_venda))
        filter (where venda.status_pedido = 'devolvida') as pedidos_devolvidos,
    count(distinct (venda.fonte, venda.id_venda))
        filter (where venda.status_pedido = 'cancelada') as pedidos_cancelados,
    coalesce(sum(venda.quantidade)
        filter (where venda.status_pedido = 'concluida'), 0) as itens_vendidos,
    sum(venda.valor_liquido) as receita_liquida_registrada,
    coalesce(sum(venda.valor_liquido)
        filter (where venda.status_pedido = 'concluida'), 0) as receita_liquida_concluida,
    coalesce(sum(venda.valor_liquido)
        filter (where venda.status_pedido = 'devolvida'), 0) as receita_devolvida_registrada,
    coalesce(sum(venda.margem_bruta)
        filter (where venda.status_pedido = 'concluida'), 0) as margem_bruta_concluida
from dw.fato_vendas as venda
join dw.dim_data as calendario using (data_id)
join dw.dim_unidade as unidade using (unidade_id)
join dw.dim_produto as produto using (produto_id)
group by grouping sets (
    (calendario.data, calendario.ano_mes, unidade.unidade_id, unidade.unidade, unidade.canal),
    (calendario.data, calendario.ano_mes, unidade.unidade_id, unidade.unidade, unidade.canal, produto.categoria)
);

create view bi.vw_vendas_diarias
with (security_barrier = true, security_invoker = false) as
select data_venda, ano_mes, unidade_id, unidade, canal, linhas_registradas,
    pedidos_total, pedidos_concluidos, pedidos_devolvidos, pedidos_cancelados,
    itens_vendidos, receita_liquida_registrada, receita_liquida_concluida,
    receita_devolvida_registrada, margem_bruta_concluida,
    receita_liquida_concluida / nullif(pedidos_concluidos, 0) as ticket_medio,
    100.0 * margem_bruta_concluida / nullif(receita_liquida_concluida, 0) as margem_bruta_pct,
    100.0 * pedidos_devolvidos / nullif(pedidos_concluidos + pedidos_devolvidos, 0) as taxa_devolucao_pct,
    100.0 * pedidos_cancelados / nullif(pedidos_total, 0) as taxa_cancelamento_pct
from bi.vw_vendas_agrupadas where agrupamento_categoria = 1;

create view bi.vw_vendas_diarias_categoria
with (security_barrier = true, security_invoker = false) as
select data_venda, ano_mes, unidade_id, unidade, canal, categoria, linhas_registradas,
    pedidos_total, pedidos_concluidos, pedidos_devolvidos, pedidos_cancelados,
    itens_vendidos, receita_liquida_registrada, receita_liquida_concluida,
    receita_devolvida_registrada, margem_bruta_concluida,
    receita_liquida_concluida / nullif(pedidos_concluidos, 0) as ticket_medio,
    100.0 * margem_bruta_concluida / nullif(receita_liquida_concluida, 0) as margem_bruta_pct,
    100.0 * pedidos_devolvidos / nullif(pedidos_concluidos + pedidos_devolvidos, 0) as taxa_devolucao_pct,
    100.0 * pedidos_cancelados / nullif(pedidos_total, 0) as taxa_cancelamento_pct
from bi.vw_vendas_agrupadas where agrupamento_categoria = 0;

create view bi.vw_metas_mensais
with (security_barrier = true, security_invoker = false) as
select meta.ano_mes, calendario.data as inicio_mes,
    (calendario.data + interval '1 month - 1 day')::date as fim_mes,
    unidade.unidade_id, unidade.unidade, unidade.canal,
    meta.meta_receita_liquida, meta.meta_pedidos, meta.meta_ticket_medio,
    100.0 * meta.meta_margem_bruta_pct as meta_margem_bruta_pct,
    100.0 * meta.meta_taxa_devolucao_pct as meta_taxa_devolucao_pct
from dw.fato_metas as meta
join dw.dim_data as calendario on calendario.data_id = meta.data_id_mes
join dw.dim_unidade as unidade using (unidade_id);

create view bi.vw_desempenho_mensal
with (security_barrier = true, security_invoker = false) as
with vendas_mes as (
    select ano_mes, unidade_id, unidade, canal,
        sum(linhas_registradas) as linhas_registradas,
        sum(pedidos_total) as pedidos_total,
        sum(pedidos_concluidos) as pedidos_concluidos,
        sum(pedidos_devolvidos) as pedidos_devolvidos,
        sum(pedidos_cancelados) as pedidos_cancelados,
        sum(itens_vendidos) as itens_vendidos,
        sum(receita_liquida_registrada) as receita_liquida_registrada,
        sum(receita_liquida_concluida) as receita_liquida_concluida,
        sum(receita_devolvida_registrada) as receita_devolvida_registrada,
        sum(margem_bruta_concluida) as margem_bruta_concluida
    from bi.vw_vendas_diarias group by ano_mes, unidade_id, unidade, canal
)
select coalesce(vendas_mes.ano_mes, meta.ano_mes) as ano_mes,
    coalesce(vendas_mes.unidade_id, meta.unidade_id) as unidade_id,
    coalesce(vendas_mes.unidade, meta.unidade) as unidade,
    coalesce(vendas_mes.canal, meta.canal) as canal,
    coalesce(vendas_mes.linhas_registradas, 0) as linhas_registradas,
    coalesce(vendas_mes.pedidos_total, 0) as pedidos_total,
    coalesce(vendas_mes.pedidos_concluidos, 0) as pedidos_concluidos,
    coalesce(vendas_mes.pedidos_devolvidos, 0) as pedidos_devolvidos,
    coalesce(vendas_mes.pedidos_cancelados, 0) as pedidos_cancelados,
    coalesce(vendas_mes.itens_vendidos, 0) as itens_vendidos,
    coalesce(vendas_mes.receita_liquida_registrada, 0) as receita_liquida_registrada,
    coalesce(vendas_mes.receita_liquida_concluida, 0) as receita_liquida_concluida,
    coalesce(vendas_mes.receita_devolvida_registrada, 0) as receita_devolvida_registrada,
    coalesce(vendas_mes.margem_bruta_concluida, 0) as margem_bruta_concluida,
    vendas_mes.receita_liquida_concluida / nullif(vendas_mes.pedidos_concluidos, 0) as ticket_medio,
    100.0 * vendas_mes.margem_bruta_concluida / nullif(vendas_mes.receita_liquida_concluida, 0) as margem_bruta_pct,
    100.0 * vendas_mes.pedidos_devolvidos / nullif(vendas_mes.pedidos_concluidos + vendas_mes.pedidos_devolvidos, 0) as taxa_devolucao_pct,
    100.0 * vendas_mes.pedidos_cancelados / nullif(vendas_mes.pedidos_total, 0) as taxa_cancelamento_pct,
    meta.meta_receita_liquida, meta.meta_pedidos,
    100.0 * vendas_mes.receita_liquida_concluida / nullif(meta.meta_receita_liquida, 0) as atingimento_receita_pct,
    vendas_mes.linhas_registradas is not null as tem_registros_vendas,
    meta.unidade_id is not null as tem_meta,
    false as completude_periodo_comprovada
from vendas_mes full join bi.vw_metas_mensais as meta
    on meta.unidade_id = vendas_mes.unidade_id and meta.ano_mes = vendas_mes.ano_mes;

create view bi.vw_atualizacao
with (security_barrier = true, security_invoker = false) as
select
    (select max(calendario.data) from dw.fato_vendas as venda
        join dw.dim_data as calendario using (data_id)) as ultima_data_venda,
    max(atualizado_em) filter (where status = 'sucesso') as ultima_execucao_sucesso,
    max(to_date(substring(carga_dw_id from '^dw-diario-([0-9]{8})$'), 'YYYYMMDD'))
        filter (where status = 'sucesso' and carga_dw_id ~ '^dw-diario-[0-9]{8}$') as ultima_data_diaria_publicada,
    count(*) filter (where status = 'iniciada') as cargas_sem_conclusao,
    count(*) filter (where status = 'erro') as cargas_com_erro,
    false as completude_datalake_disponivel,
    'Ultima execucao nao comprova completude por unidade/data; consultar manifestos do lake.'::text as aviso
from etl.cargas_dw;

revoke all on all tables in schema bi from public, anon, authenticated, xfit_dashboard;
grant select on bi.vw_vendas_diarias, bi.vw_vendas_diarias_categoria,
    bi.vw_metas_mensais, bi.vw_desempenho_mensal, bi.vw_atualizacao to xfit_dashboard;

reset role;
grant xfit_bi_owner to current_user with set false;
