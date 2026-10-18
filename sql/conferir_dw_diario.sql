do $$
begin
    if (select count(*) from stg.stg_produtos) <> (select count(*) from dw.dim_produto)
    or (select count(*) from stg.stg_metas) <> (select count(*) from dw.fato_metas)
    or exists (
        select 1 from stg.stg_produtos s left join dw.dim_produto p using (produto_id)
        where p.produto_id is null or
        row(s.produto, s.genero_produto, s.categoria, s.preco_lista, s.custo_padrao)
        is distinct from row(p.produto, p.genero_produto, p.categoria, p.preco_lista, p.custo_padrao)
    ) or exists (
        select 1 from stg.stg_metas s left join dw.fato_metas f using (unidade_id, ano_mes)
        where f.meta_id is null or
        row(s.meta_receita_liquida, s.meta_pedidos, s.meta_ticket_medio,
            s.meta_margem_bruta_pct, s.meta_taxa_devolucao_pct)
        is distinct from row(f.meta_receita_liquida, f.meta_pedidos, f.meta_ticket_medio,
                            f.meta_margem_bruta_pct, f.meta_taxa_devolucao_pct)
    ) or exists (
        (select fonte, id_venda, produto_id, quantidade, valor_bruto, valor_desconto,
                valor_liquido, custo_total, margem_bruta, status_pedido,
                to_char(data_venda, 'YYYYMMDD')::integer, unidade_id,
                forma_pagamento, campanha, pedido_online_id, canal_origem, cupom
         from stg.stg_vendas)
        except all
        (select fonte, id_venda, produto_id, quantidade, valor_bruto, valor_desconto,
                valor_liquido, custo_total, margem_bruta, status_pedido,
                data_id, unidade_id, forma_pagamento, campanha, pedido_online_id, canal_origem, cupom
         from dw.fato_vendas)
    ) or exists (
        select 1 from dw.fato_vendas f left join stg.stg_vendas s
        using (fonte, id_venda, produto_id) where s.fonte is null
    ) then
        raise exception 'Reconciliacao diaria staging/DW reprovada';
    end if;
end;
$$;
