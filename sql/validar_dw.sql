-- # Validacoes SQL do DW local/futuro Supabase
--
-- Rodar depois das cargas dimensionais. As consultas de problema devem retornar
-- zero linhas. O resumo pode ser consumido pelo Airflow como conferencia simples.
-- NOTE: a tolerancia financeira da staging nao autoriza desvio novo no DW.

select
    (select count(*) from dw.dim_data) as linhas_dim_data,
    (select count(*) from dw.dim_produto) as linhas_dim_produto,
    (select count(*) from dw.dim_unidade) as linhas_dim_unidade,
    (select count(*) from dw.fato_vendas) as linhas_fato_vendas,
    (select count(*) from dw.fato_metas) as linhas_fato_metas;

-- Buracos no calendario gravado.
with limites as (
    select min(data) as data_minima, max(data) as data_maxima
    from dw.dim_data
), calendario_esperado as (
    select data_calendario::date as data
    from limites,
         generate_series(data_minima, data_maxima, interval '1 day') as serie(data_calendario)
)
select calendario_esperado.data as data_faltante
from calendario_esperado
left join dw.dim_data using (data)
where dw.dim_data.data is null
order by calendario_esperado.data;

-- Produtos vendidos sem dimensao.
select count(*) as produtos_vendidos_sem_dimensao
from stg.stg_vendas as v
left join dw.dim_produto as p on p.produto_id = v.produto_id
where p.produto_id is null;

-- Unidades de vendas/metas sem dimensao.
with unidades_staging as (
    select unidade_id from stg.stg_vendas
    union
    select unidade_id from stg.stg_metas
)
select count(*) as unidades_sem_dimensao
from unidades_staging as u
left join dw.dim_unidade as d on d.unidade_id = u.unidade_id
where d.unidade_id is null;

-- Controle de grão da fato_vendas: uma linha por item vendido da staging.
select
    (select count(*) from stg.stg_vendas) as itens_staging,
    (select count(*) from dw.fato_vendas) as itens_dw,
    (select count(distinct id_venda) from dw.fato_vendas) as pedidos_dw;

-- Reconciliação financeira: transferência staging -> fato sem novo desvio.
select
    coalesce((select sum(valor_liquido) from stg.stg_vendas), 0) as valor_liquido_staging,
    coalesce((select sum(valor_liquido) from dw.fato_vendas), 0) as valor_liquido_dw,
    coalesce((select sum(valor_liquido) from stg.stg_vendas), 0)
      - coalesce((select sum(valor_liquido) from dw.fato_vendas), 0) as diferenca_valor_liquido;

-- Metas continuam mensais por unidade.
select unidade_id, ano_mes, count(*) as linhas
from dw.fato_metas
group by unidade_id, ano_mes
having count(*) > 1;
