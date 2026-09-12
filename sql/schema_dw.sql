-- # xFit Wear - schema SQL do pipeline analitico
--
-- Arquitetura decidida no projeto:
-- Python le CSV/API e prepara dados; Airflow orquestra; Supabase/Postgres guarda
-- staging e DW; SQL promove staging para modelo dimensional.
--
-- NOTE: este arquivo ainda nao e migration oficial porque a Supabase CLI nao esta
-- instalada neste ambiente. Quando a CLI entrar, criar a migration por comando e
-- copiar este contrato para o arquivo gerado.
-- TODO: separar grants por papel de servico quando houver projeto Supabase real.
-- TODO: mover logs detalhados de falha para tabela protegida quando o Airflow existir.

create schema if not exists stg;
create schema if not exists etl;
create schema if not exists dw;

comment on schema stg is 'Camada staging carregada por Python/Airflow a partir de CSV e API.';
comment on schema etl is 'Metadados operacionais do pipeline.';
comment on schema dw is 'Modelo dimensional da xFit Wear para consumo analitico controlado.';

-- Supabase: privado por padrao. O dashboard futuro deve consumir views/endpoints
-- revisados, nao tabelas base expostas diretamente.
revoke all on schema stg from public;
revoke all on schema stg from anon;
revoke all on schema stg from authenticated;
revoke all on schema etl from public;
revoke all on schema etl from anon;
revoke all on schema etl from authenticated;
revoke all on schema dw from public;
revoke all on schema dw from anon;
revoke all on schema dw from authenticated;

create table if not exists etl.cargas_dw (
    carga_dw_id text primary key,
    carga_origem_id text,
    etapa text not null,
    status text not null check (status in ('iniciada', 'sucesso', 'erro')),
    linhas_afetadas integer not null default 0 check (linhas_afetadas >= 0),
    mensagem_publica text,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);

comment on table etl.cargas_dw is 'Registro operacional resumido. Nao guardar payload sensivel ou valores brutos de erro.';

create table if not exists stg.stg_produtos (
    produto_id text primary key,
    produto text not null,
    genero_produto text,
    categoria text not null,
    preco_lista numeric(12, 2) not null check (preco_lista >= 0),
    custo_padrao numeric(12, 2) not null check (custo_padrao >= 0),
    data_processamento timestamptz not null default now()
);

create table if not exists stg.stg_vendas (
    fonte text not null,
    id_venda text not null,
    data_venda date not null,
    hora_venda time not null,
    cliente_id text not null,
    produto_id text not null,
    quantidade integer not null check (quantidade > 0),
    valor_bruto numeric(14, 2) not null check (valor_bruto >= 0),
    valor_desconto numeric(14, 2) not null check (valor_desconto >= 0),
    valor_liquido numeric(14, 2) not null check (valor_liquido >= 0),
    custo_total numeric(14, 2) not null check (custo_total >= 0),
    margem_bruta numeric(14, 2) not null,
    status_pedido text not null check (status_pedido in ('concluida', 'devolvida', 'cancelada')),
    canal text not null check (canal in ('loja_fisica', 'ecommerce')),
    unidade_id text not null,
    cidade text,
    uf char(2),
    campanha text,
    forma_pagamento text,
    pedido_online_id text,
    canal_origem text,
    cupom text,
    data_processamento timestamptz not null default now(),
    primary key (fonte, id_venda, produto_id)
);

comment on table stg.stg_vendas is 'Staging de vendas no nivel de item vendido enquanto a fonte nao fornece item_id nativo.';
comment on constraint stg_vendas_pkey on stg.stg_vendas is 'Regra provisoria: fonte/id_venda/produto_id identifica o item ate existir item_id da origem.';

create table if not exists stg.stg_metas (
    ano_mes char(7) not null,
    canal text not null check (canal in ('loja_fisica', 'ecommerce')),
    unidade_id text not null,
    cidade text,
    uf char(2),
    meta_receita_liquida numeric(14, 2) not null check (meta_receita_liquida >= 0),
    meta_pedidos integer not null check (meta_pedidos > 0),
    meta_ticket_medio numeric(14, 2) not null check (meta_ticket_medio >= 0),
    meta_margem_bruta_pct numeric(7, 4) not null check (meta_margem_bruta_pct >= 0),
    meta_taxa_devolucao_pct numeric(7, 4) not null check (meta_taxa_devolucao_pct >= 0),
    inicio_operacao date,
    observacao text,
    data_processamento timestamptz not null default now(),
    primary key (unidade_id, ano_mes)
);

create table if not exists dw.dim_data (
    data_id integer primary key,
    data date not null unique,
    ano smallint not null,
    mes smallint not null,
    dia smallint not null,
    ano_mes char(7) not null,
    trimestre smallint not null,
    semestre smallint not null,
    dia_semana smallint not null,
    nome_dia_semana text not null,
    fim_de_semana boolean not null,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now(),
    constraint dim_data_id_bate_com_data check (data_id = (to_char(data, 'YYYYMMDD'))::integer),
    constraint dim_data_ano_mes_bate_com_data check (ano_mes = to_char(data, 'YYYY-MM')),
    constraint dim_data_dia_semana_valido check (dia_semana between 1 and 7),
    constraint dim_data_nome_dia_semana_valido check (
        nome_dia_semana in ('segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo')
    )
);

comment on table dw.dim_data is 'Dimensao calendario. Metas futuras podem ampliar o calendario sem significar venda futura.';

create table if not exists dw.dim_produto (
    produto_sk bigint generated always as identity primary key,
    produto_id text not null unique,
    produto text not null,
    genero_produto text,
    categoria text not null,
    preco_lista numeric(12, 2) not null check (preco_lista >= 0),
    custo_padrao numeric(12, 2) not null check (custo_padrao >= 0),
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);

comment on table dw.dim_produto is 'Dimensao cadastral de produto. Nao guardar metricas transacionais nesta tabela.';

create table if not exists dw.dim_unidade (
    unidade_sk bigint generated always as identity primary key,
    unidade_id text not null unique,
    canal text not null check (canal in ('loja_fisica', 'ecommerce')),
    unidade text not null,
    cidade text,
    uf char(2),
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);

comment on table dw.dim_unidade is 'Concentra canal, unidade operacional, cidade e UF. Ecommerce deve permanecer como EC-BR.';

create table if not exists dw.fato_vendas (
    venda_item_id text primary key,
    id_venda text not null,
    fonte text not null,
    data_id integer not null references dw.dim_data(data_id),
    produto_id text not null references dw.dim_produto(produto_id),
    unidade_id text not null references dw.dim_unidade(unidade_id),
    quantidade integer not null check (quantidade > 0),
    valor_bruto numeric(14, 2) not null,
    valor_desconto numeric(14, 2) not null,
    valor_liquido numeric(14, 2) not null,
    custo_total numeric(14, 2) not null,
    margem_bruta numeric(14, 2) not null,
    status_pedido text not null check (status_pedido in ('concluida', 'devolvida', 'cancelada')),
    forma_pagamento text,
    campanha text,
    pedido_online_id text,
    canal_origem text,
    cupom text,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now(),
    constraint fato_vendas_item_origem_unico unique (fonte, id_venda, produto_id)
);

comment on table dw.fato_vendas is 'Fato no grao item vendido. Pedidos devem ser calculados por count(distinct id_venda).';
comment on column dw.fato_vendas.venda_item_id is 'Chave tecnica deterministica do item vendido enquanto a fonte nao fornece item_id.';
comment on column dw.fato_vendas.id_venda is 'Identificador do pedido usado em count(distinct id_venda).';
comment on column dw.fato_vendas.fonte is 'Fonte operacional mantida para rastreabilidade minima sem expor caminho local.';

create table if not exists dw.fato_metas (
    meta_id text primary key,
    ano_mes char(7) not null,
    data_id_mes integer not null references dw.dim_data(data_id),
    unidade_id text not null references dw.dim_unidade(unidade_id),
    meta_receita_liquida numeric(14, 2) not null check (meta_receita_liquida >= 0),
    meta_pedidos integer not null check (meta_pedidos > 0),
    meta_ticket_medio numeric(14, 2) not null check (meta_ticket_medio >= 0),
    meta_margem_bruta_pct numeric(7, 4) not null check (meta_margem_bruta_pct >= 0),
    meta_taxa_devolucao_pct numeric(7, 4) not null check (meta_taxa_devolucao_pct >= 0),
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now(),
    constraint fato_metas_unidade_mes_unico unique (unidade_id, ano_mes)
);

comment on table dw.fato_metas is 'Fato mensal por unidade. Nunca comparar metas com vendas sem agregar venda por unidade/mes antes.';

create index if not exists ix_fato_vendas_data on dw.fato_vendas(data_id);
create index if not exists ix_fato_vendas_produto on dw.fato_vendas(produto_id);
create index if not exists ix_fato_vendas_unidade on dw.fato_vendas(unidade_id);
create index if not exists ix_fato_vendas_pedido on dw.fato_vendas(id_venda);
create index if not exists ix_fato_metas_unidade_mes on dw.fato_metas(unidade_id, ano_mes);

alter table stg.stg_produtos enable row level security;
alter table stg.stg_vendas enable row level security;
alter table stg.stg_metas enable row level security;
alter table etl.cargas_dw enable row level security;
alter table dw.dim_data enable row level security;
alter table dw.dim_produto enable row level security;
alter table dw.dim_unidade enable row level security;
alter table dw.fato_vendas enable row level security;
alter table dw.fato_metas enable row level security;

-- Sem policies nesta fase: deny-by-default para anon/authenticated via RLS e grants.
-- TODO: quando houver dashboard, criar views seguras de consumo em vez de expor stg/dw direto.

create or replace function dw.carregar_dim_data(
    p_data_inicial date,
    p_data_final date
)
returns integer
language plpgsql
set search_path = dw, pg_temp
as $$
declare
    v_linhas_afetadas integer := 0;
begin
    if p_data_inicial is null or p_data_final is null or p_data_inicial > p_data_final then
        raise exception 'Janela invalida para carga da dim_data';
    end if;

    insert into dw.dim_data (
        data_id, data, ano, mes, dia, ano_mes, trimestre, semestre,
        dia_semana, nome_dia_semana, fim_de_semana, atualizado_em
    )
    select
        to_char(data_calendario, 'YYYYMMDD')::integer,
        data_calendario::date,
        extract(year from data_calendario)::smallint,
        extract(month from data_calendario)::smallint,
        extract(day from data_calendario)::smallint,
        to_char(data_calendario, 'YYYY-MM'),
        extract(quarter from data_calendario)::smallint,
        case when extract(month from data_calendario)::int <= 6 then 1 else 2 end::smallint,
        extract(isodow from data_calendario)::smallint,
        case extract(isodow from data_calendario)::int
            when 1 then 'segunda' when 2 then 'terca' when 3 then 'quarta'
            when 4 then 'quinta' when 5 then 'sexta' when 6 then 'sabado'
            when 7 then 'domingo'
        end,
        extract(isodow from data_calendario)::int in (6, 7),
        now()
    from generate_series(p_data_inicial, p_data_final, interval '1 day') as calendario(data_calendario)
    on conflict (data_id) do update set
        data = excluded.data,
        ano = excluded.ano,
        mes = excluded.mes,
        dia = excluded.dia,
        ano_mes = excluded.ano_mes,
        trimestre = excluded.trimestre,
        semestre = excluded.semestre,
        dia_semana = excluded.dia_semana,
        nome_dia_semana = excluded.nome_dia_semana,
        fim_de_semana = excluded.fim_de_semana,
        atualizado_em = now();

    get diagnostics v_linhas_afetadas = row_count;
    return v_linhas_afetadas;
end;
$$;

create or replace function dw.carregar_dim_produto()
returns integer
language plpgsql
set search_path = dw, stg, pg_temp
as $$
declare
    v_linhas_afetadas integer := 0;
begin
    insert into dw.dim_produto (
        produto_id, produto, genero_produto, categoria,
        preco_lista, custo_padrao, atualizado_em
    )
    select
        produto_id, produto, genero_produto, categoria,
        preco_lista, custo_padrao, now()
    from stg.stg_produtos
    on conflict (produto_id) do update set
        produto = excluded.produto,
        genero_produto = excluded.genero_produto,
        categoria = excluded.categoria,
        preco_lista = excluded.preco_lista,
        custo_padrao = excluded.custo_padrao,
        atualizado_em = now();

    get diagnostics v_linhas_afetadas = row_count;
    return v_linhas_afetadas;
end;
$$;

create or replace function dw.carregar_dim_unidade()
returns integer
language plpgsql
set search_path = dw, stg, pg_temp
as $$
declare
    v_linhas_afetadas integer := 0;
begin
    insert into dw.dim_unidade (unidade_id, canal, unidade, cidade, uf, atualizado_em)
    select distinct on (base.unidade_id)
        base.unidade_id,
        base.canal,
        case
            when base.unidade_id = 'EC-BR' then 'Ecommerce Brasil'
            else base.unidade_id
        end as unidade,
        base.cidade,
        base.uf,
        now()
    from (
        select unidade_id, canal, cidade, uf from stg.stg_vendas
        union all
        select unidade_id, canal, cidade, uf from stg.stg_metas
    ) as base
    order by base.unidade_id, case when base.cidade is not null then 0 else 1 end
    on conflict (unidade_id) do update set
        canal = excluded.canal,
        unidade = excluded.unidade,
        cidade = excluded.cidade,
        uf = excluded.uf,
        atualizado_em = now();

    get diagnostics v_linhas_afetadas = row_count;
    return v_linhas_afetadas;
end;
$$;

create or replace function dw.carregar_fato_vendas()
returns integer
language plpgsql
set search_path = dw, stg, pg_temp
as $$
declare
    v_linhas_afetadas integer := 0;
begin
    insert into dw.fato_vendas (
        venda_item_id, id_venda, fonte, data_id, produto_id, unidade_id,
        quantidade, valor_bruto, valor_desconto, valor_liquido, custo_total,
        margem_bruta, status_pedido, forma_pagamento, campanha, pedido_online_id,
        canal_origem, cupom, atualizado_em
    )
    select
        md5(v.fonte || '|' || v.id_venda || '|' || v.produto_id) as venda_item_id,
        v.id_venda,
        v.fonte,
        to_char(v.data_venda, 'YYYYMMDD')::integer as data_id,
        v.produto_id,
        v.unidade_id,
        v.quantidade,
        v.valor_bruto,
        v.valor_desconto,
        v.valor_liquido,
        v.custo_total,
        v.margem_bruta,
        v.status_pedido,
        v.forma_pagamento,
        v.campanha,
        v.pedido_online_id,
        v.canal_origem,
        v.cupom,
        now()
    from stg.stg_vendas as v
    join dw.dim_data as d on d.data = v.data_venda
    join dw.dim_produto as p on p.produto_id = v.produto_id
    join dw.dim_unidade as u on u.unidade_id = v.unidade_id
    on conflict (venda_item_id) do update set
        quantidade = excluded.quantidade,
        valor_bruto = excluded.valor_bruto,
        valor_desconto = excluded.valor_desconto,
        valor_liquido = excluded.valor_liquido,
        custo_total = excluded.custo_total,
        margem_bruta = excluded.margem_bruta,
        status_pedido = excluded.status_pedido,
        forma_pagamento = excluded.forma_pagamento,
        campanha = excluded.campanha,
        pedido_online_id = excluded.pedido_online_id,
        canal_origem = excluded.canal_origem,
        cupom = excluded.cupom,
        atualizado_em = now();

    get diagnostics v_linhas_afetadas = row_count;
    return v_linhas_afetadas;
end;
$$;

create or replace function dw.carregar_fato_metas()
returns integer
language plpgsql
set search_path = dw, stg, pg_temp
as $$
declare
    v_linhas_afetadas integer := 0;
begin
    insert into dw.fato_metas (
        meta_id, ano_mes, data_id_mes, unidade_id, meta_receita_liquida,
        meta_pedidos, meta_ticket_medio, meta_margem_bruta_pct,
        meta_taxa_devolucao_pct, atualizado_em
    )
    select
        md5(m.unidade_id || '|' || m.ano_mes) as meta_id,
        m.ano_mes,
        to_char((m.ano_mes || '-01')::date, 'YYYYMMDD')::integer as data_id_mes,
        m.unidade_id,
        m.meta_receita_liquida,
        m.meta_pedidos,
        m.meta_ticket_medio,
        m.meta_margem_bruta_pct,
        m.meta_taxa_devolucao_pct,
        now()
    from stg.stg_metas as m
    join dw.dim_data as d on d.data = (m.ano_mes || '-01')::date
    join dw.dim_unidade as u on u.unidade_id = m.unidade_id
    on conflict (meta_id) do update set
        meta_receita_liquida = excluded.meta_receita_liquida,
        meta_pedidos = excluded.meta_pedidos,
        meta_ticket_medio = excluded.meta_ticket_medio,
        meta_margem_bruta_pct = excluded.meta_margem_bruta_pct,
        meta_taxa_devolucao_pct = excluded.meta_taxa_devolucao_pct,
        atualizado_em = now();

    get diagnostics v_linhas_afetadas = row_count;
    return v_linhas_afetadas;
end;
$$;

comment on function dw.carregar_dim_data(date, date) is 'Carrega a dimensao calendario para a janela aprovada pela staging.';
comment on function dw.carregar_dim_produto() is 'Promove produtos da staging para dimensao cadastral de produto.';
comment on function dw.carregar_dim_unidade() is 'Promove unidades/canais da staging para dimensao de unidade.';
comment on function dw.carregar_fato_vendas() is 'Promove vendas no grao item vendido.';
comment on function dw.carregar_fato_metas() is 'Promove metas mensais por unidade.';

revoke all on function dw.carregar_dim_data(date, date) from public;
revoke all on function dw.carregar_dim_data(date, date) from anon;
revoke all on function dw.carregar_dim_data(date, date) from authenticated;
revoke all on function dw.carregar_dim_produto() from public;
revoke all on function dw.carregar_dim_produto() from anon;
revoke all on function dw.carregar_dim_produto() from authenticated;
revoke all on function dw.carregar_dim_unidade() from public;
revoke all on function dw.carregar_dim_unidade() from anon;
revoke all on function dw.carregar_dim_unidade() from authenticated;
revoke all on function dw.carregar_fato_vendas() from public;
revoke all on function dw.carregar_fato_vendas() from anon;
revoke all on function dw.carregar_fato_vendas() from authenticated;
revoke all on function dw.carregar_fato_metas() from public;
revoke all on function dw.carregar_fato_metas() from anon;
revoke all on function dw.carregar_fato_metas() from authenticated;
