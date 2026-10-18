begin;
grant xfit_dashboard to current_user with set true;

do $$
begin
    if coalesce((select sum(linhas_registradas) from bi.vw_vendas_diarias),0)
       is distinct from (select count(*) from dw.fato_vendas)
       or coalesce((select sum(pedidos_total) from bi.vw_vendas_diarias),0)
       is distinct from (select count(distinct (fonte,id_venda)) from dw.fato_vendas)
       or (select sum(receita_liquida_registrada) from bi.vw_vendas_diarias)
       is distinct from (select sum(valor_liquido) from dw.fato_vendas)
       or coalesce((select sum(receita_liquida_concluida) from bi.vw_vendas_diarias),0)
       is distinct from coalesce((select sum(valor_liquido) from dw.fato_vendas where status_pedido='concluida'),0)
       or coalesce((select sum(margem_bruta_concluida) from bi.vw_vendas_diarias),0)
       is distinct from coalesce((select sum(margem_bruta) from dw.fato_vendas where status_pedido='concluida'),0)
       or coalesce((select sum(itens_vendidos) from bi.vw_vendas_diarias),0)
       is distinct from coalesce((select sum(quantidade) from dw.fato_vendas where status_pedido='concluida'),0) then
        raise exception 'Indicadores diarios divergem da fato';
    end if;
    if (select sum(receita_liquida_registrada) from bi.vw_vendas_diarias_categoria)
       is distinct from (select sum(valor_liquido) from dw.fato_vendas)
       or (select count(*) from bi.vw_metas_mensais)
       <> (select count(*) from dw.fato_metas)
       or (select sum(meta_receita_liquida) from bi.vw_desempenho_mensal)
       is distinct from (select sum(meta_receita_liquida) from dw.fato_metas)
       or exists (select 1 from bi.vw_desempenho_mensal
                  where not tem_registros_vendas and atingimento_receita_pct is not null) then
        raise exception 'Categoria ou metas nao reconciliadas';
    end if;
    if exists (select 1 from pg_roles where rolname in ('xfit_dashboard','xfit_bi_owner')
               and (rolsuper or rolbypassrls or rolcreaterole or rolcreatedb or rolcanlogin))
       or pg_has_role('xfit_dashboard','xfit_bi_owner','MEMBER')
       or pg_has_role('xfit_dashboard','xfit_pipeline','MEMBER') then
        raise exception 'Papel BI privilegiado ou com membresia indevida';
    end if;
end;
$$;

do $$
declare
    v_papel text;
    v_view text;
    v_tabela text;
    v_bloqueado boolean;
begin
    foreach v_view in array array[
        'vw_vendas_diarias','vw_vendas_diarias_categoria','vw_metas_mensais',
        'vw_desempenho_mensal','vw_atualizacao'
    ] loop
        execute 'set local role xfit_dashboard';
        execute format('select count(*) from bi.%I',v_view);
        reset role;
        if has_table_privilege('xfit_dashboard','bi.'||v_view,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') then
            raise exception 'Dashboard recebeu privilegio alem de leitura';
        end if;
        foreach v_papel in array array['anon','authenticated'] loop
            execute format('set local role %I',v_papel);
            v_bloqueado := false;
            begin
                execute format('select count(*) from bi.%I',v_view);
            exception when insufficient_privilege then
                v_bloqueado := true;
            end;
            reset role;
            if not v_bloqueado then raise exception 'View BI acessivel ao consumidor publico'; end if;
        end loop;
    end loop;
    foreach v_tabela in array array[
        'dw.dim_data','dw.dim_produto','dw.dim_unidade','dw.fato_vendas','dw.fato_metas',
        'stg.stg_vendas','stg.stg_produtos','stg.stg_metas','etl.cargas_dw','bi.vw_vendas_agrupadas'
    ] loop
        execute 'set local role xfit_dashboard';
        v_bloqueado := false;
        begin
            execute 'select count(*) from '||v_tabela;
        exception when insufficient_privilege then
            v_bloqueado := true;
        end;
        reset role;
        if not v_bloqueado then raise exception 'Dashboard acessa base privada diretamente'; end if;
    end loop;
end;
$$;

rollback;
select 'indicadores, metas e permissoes BI aprovados; nenhuma alteracao de dados' as resultado;
