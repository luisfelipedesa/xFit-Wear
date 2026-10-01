-- Executar em transacao depois de carregar e reconciliar toda a staging.
-- O executor define SET LOCAL xfit.carga_dw_id com o identificador aprovado.
do $$
declare
    v_carga_id text := current_setting('xfit.carga_dw_id');
    v_inicio date;
    v_fim date;
    v_linhas integer := 0;
begin
    perform 1 from etl.cargas_dw
    where carga_dw_id = v_carga_id and status = 'iniciada' for update;
    if not found then
        raise exception 'Carga ausente ou ja finalizada';
    end if;
    if not exists (select 1 from stg.stg_vendas)
       or not exists (select 1 from stg.stg_produtos)
       or not exists (select 1 from stg.stg_metas) then
        raise exception 'Staging incompleta';
    end if;

    select min(data_venda), greatest(max(data_venda),
        (select (max(ano_mes) || '-01')::date + interval '1 month - 1 day' from stg.stg_metas)::date)
    into v_inicio, v_fim from stg.stg_vendas;
    v_linhas := dw.carregar_dim_data(v_inicio, v_fim);
    v_linhas := v_linhas + dw.carregar_dim_produto();
    v_linhas := v_linhas + dw.carregar_dim_unidade();
    v_linhas := v_linhas + dw.carregar_fato_vendas();
    v_linhas := v_linhas + dw.carregar_fato_metas();

    if (select count(*) from stg.stg_vendas) <> (select count(*) from dw.fato_vendas)
       or (select count(*) from stg.stg_metas) <> (select count(*) from dw.fato_metas)
       or (select count(*) from stg.stg_produtos) <> (select count(*) from dw.dim_produto)
       or exists (
           select 1 from stg.stg_vendas s
           left join dw.fato_vendas f using (fonte, id_venda, produto_id)
           where f.venda_item_id is null or
               row(to_char(s.data_venda, 'YYYYMMDD')::integer, s.unidade_id, s.quantidade,
                   s.valor_bruto, s.valor_desconto, s.valor_liquido, s.custo_total,
                   s.margem_bruta, s.status_pedido, s.forma_pagamento, s.campanha,
                   s.pedido_online_id, s.canal_origem, s.cupom)
               is distinct from
               row(f.data_id, f.unidade_id, f.quantidade, f.valor_bruto, f.valor_desconto,
                   f.valor_liquido, f.custo_total, f.margem_bruta, f.status_pedido,
                   f.forma_pagamento, f.campanha, f.pedido_online_id, f.canal_origem, f.cupom)
       ) or exists (
           select 1 from stg.stg_metas s
           left join dw.fato_metas f using (unidade_id, ano_mes)
           where f.meta_id is null or
               row(s.meta_receita_liquida, s.meta_pedidos, s.meta_ticket_medio,
                   s.meta_margem_bruta_pct, s.meta_taxa_devolucao_pct)
               is distinct from
               row(f.meta_receita_liquida, f.meta_pedidos, f.meta_ticket_medio,
                   f.meta_margem_bruta_pct, f.meta_taxa_devolucao_pct)
       ) then
        raise exception 'Reconciliacao staging/DW reprovada';
    end if;
    update etl.cargas_dw set status = 'sucesso', etapa = 'dw',
        linhas_afetadas = v_linhas, atualizado_em = now(),
        mensagem_publica = 'Carga dimensional reconciliada com a staging'
    where carga_dw_id = v_carga_id;
end;
$$;
