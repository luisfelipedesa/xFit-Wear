create function public.verificar_disponibilidade_xfit()
returns integer
language sql
stable
security invoker
set search_path = ''
as $$ select 1; $$;

revoke all on function public.verificar_disponibilidade_xfit() from public;
grant execute on function public.verificar_disponibilidade_xfit() to anon;

notify pgrst, 'reload schema';
