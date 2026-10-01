-- Testes de integracao: todas as alteracoes de dados terminam em ROLLBACK.
begin;
do $$
declare
    v_papel text;
    v_tabela text;
    v_funcao text;
    v_coluna text;
    v_bloqueado boolean;
begin
    foreach v_papel in array array['anon', 'authenticated'] loop
        foreach v_tabela in array array[
            'stg.stg_vendas', 'stg.stg_produtos', 'stg.stg_metas', 'etl.cargas_dw',
            'dw.dim_data', 'dw.dim_produto', 'dw.dim_unidade', 'dw.fato_vendas', 'dw.fato_metas'
        ] loop
            select attname into v_coluna from pg_attribute
            where attrelid = v_tabela::regclass and attnum > 0 and not attisdropped
            order by attnum limit 1;
            execute format('set local role %I', v_papel);
            v_bloqueado := false;
            begin
                execute 'select count(*) from ' || v_tabela;
            exception when insufficient_privilege then
                v_bloqueado := true;
            end;
            reset role;
            if not v_bloqueado then
                raise exception 'Leitura privada permitida para %', v_papel;
            end if;
            execute format('set local role %I', v_papel);
            v_bloqueado := false;
            begin
                execute format('update %s set %I = %I where false', v_tabela, v_coluna, v_coluna);
            exception when insufficient_privilege then
                v_bloqueado := true;
            end;
            reset role;
            if not v_bloqueado then
                raise exception 'Escrita privada permitida para %', v_papel;
            end if;
        end loop;
        foreach v_funcao in array array[
            'dw.carregar_dim_data(current_date,current_date)', 'dw.carregar_dim_produto()',
            'dw.carregar_dim_unidade()', 'dw.carregar_fato_vendas()', 'dw.carregar_fato_metas()'
        ] loop
            execute format('set local role %I', v_papel);
            v_bloqueado := false;
            begin
                execute 'select ' || v_funcao;
            exception when insufficient_privilege then
                v_bloqueado := true;
            end;
            reset role;
            if not v_bloqueado then
                raise exception 'Funcao de carga permitida para %', v_papel;
            end if;
        end loop;
    end loop;
end;
$$;

do $$
declare
    v_itens bigint;
    v_metas bigint;
    v_total numeric;
    v_fonte text;
    v_pedido text;
    v_produto text;
    v_data date;
    v_unidade text;
begin
    select count(*), sum(valor_liquido) into v_itens, v_total from dw.fato_vendas;
    select count(*) into v_metas from dw.fato_metas;
    perform dw.carregar_dim_produto();
    perform dw.carregar_dim_unidade();
    perform dw.carregar_fato_vendas();
    perform dw.carregar_fato_metas();
    if v_itens <> (select count(*) from dw.fato_vendas)
       or v_metas <> (select count(*) from dw.fato_metas)
       or v_total <> (select sum(valor_liquido) from dw.fato_vendas) then
        raise exception 'Reprocessamento duplicou ou alterou a carga';
    end if;

    select fonte, id_venda, produto_id, data_venda + 1
    into v_fonte, v_pedido, v_produto, v_data
    from stg.stg_vendas order by data_venda limit 1;
    select unidade_id into v_unidade from dw.dim_unidade
    where unidade_id <> (select unidade_id from stg.stg_vendas
        where fonte = v_fonte and id_venda = v_pedido and produto_id = v_produto) limit 1;
    update stg.stg_vendas set data_venda = v_data, unidade_id = v_unidade
    where fonte = v_fonte and id_venda = v_pedido and produto_id = v_produto;
    perform dw.carregar_fato_vendas();
    if not exists (
        select 1 from dw.fato_vendas where fonte = v_fonte and id_venda = v_pedido
        and produto_id = v_produto and data_id = to_char(v_data, 'YYYYMMDD')::integer
        and unidade_id = v_unidade
    ) or v_itens <> (select count(*) from dw.fato_vendas) then
        raise exception 'Correcao de data/unidade nao refletida na fato';
    end if;
end;
$$;
rollback;
select 'acessos privados e reprocessamento aprovados; dados preservados por rollback' as resultado;
