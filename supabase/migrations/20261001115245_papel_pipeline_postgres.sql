-- Papel exclusivo do job Python. A senha e configurada fora desta migration.
create role xfit_pipeline nologin nosuperuser nocreatedb nocreaterole
    noinherit noreplication nobypassrls connection limit 3;
grant connect on database postgres to xfit_pipeline;
grant usage on schema stg, etl, dw to xfit_pipeline;
grant select, insert, update on stg.stg_produtos, stg.stg_metas, stg.stg_vendas,
    etl.cargas_dw, dw.dim_data, dw.dim_produto, dw.dim_unidade,
    dw.fato_vendas, dw.fato_metas to xfit_pipeline;
grant usage on sequence dw.dim_produto_produto_sk_seq, dw.dim_unidade_unidade_sk_seq
    to xfit_pipeline;
grant execute on function dw.carregar_dim_data(date, date), dw.carregar_dim_produto(),
    dw.carregar_dim_unidade(), dw.carregar_fato_vendas(), dw.carregar_fato_metas()
    to xfit_pipeline;

-- NOTE: o job precisa ler e promover toda a carga historica; nao e um papel de usuario final.
do $$
declare
    v_tabela text;
begin
    foreach v_tabela in array array[
        'stg.stg_produtos', 'stg.stg_metas', 'stg.stg_vendas', 'etl.cargas_dw',
        'dw.dim_data', 'dw.dim_produto', 'dw.dim_unidade', 'dw.fato_vendas', 'dw.fato_metas'
    ] loop
        execute format('create policy pipeline_leitura on %s for select to xfit_pipeline using (true)', v_tabela);
        execute format('create policy pipeline_insercao on %s for insert to xfit_pipeline with check (true)', v_tabela);
        execute format('create policy pipeline_atualizacao on %s for update to xfit_pipeline using (true) with check (true)', v_tabela);
    end loop;
end;
$$;
-- Sem DELETE, TRUNCATE, DDL, BYPASSRLS ou acesso a auth/storage para este job.
