# Dashboard Streamlit: Vercel + AWS

Arquitetura escolhida pelo usuario em 18/10/2026. A Vercel publica somente `web/`;
Streamlit executa continuamente em uma EC2 com Docker. O navegador acessa cada
dominio diretamente, sem iframe ou proxy da Vercel. Supabase continua como DW.
Airflow nao precisa ser instalado na EC2 do dashboard.

**Publicacao autorizada pelo usuario em 28/10/2026, exclusivamente nos planos
gratuitos e sem qualquer cobranca.** Essa ordem substitui a suspensao de 18/10.
Nao fazer upgrade, contratar servicos ou consumir recursos fora das condicoes
gratuitas confirmadas. Vercel Hobby, AWS Free plan e hostname gratuito sslip.io
foram confirmados/escolhidos nesta retomada. O Free plan AWS encerra o acesso
quando o beneficio acaba; nao converter para plano pago para manter o site.
Permissao para publicar nao dispensa validar HTTPS e configuracao efetiva.

**Modo vigente: portfolio publico**, autorizado pelo usuario em 28/10/2026.
Compose define `XFIT_DASHBOARD_PUBLIC=1`: visitantes consultam indicadores do
DW sintetico sem login. Nao montar secrets OAuth nesse modo. Banco continua
privado, com login BI dedicado, TLS e privilegios somente nas views de leitura.
Sem a variavel publica, a aplicacao continua exigindo OIDC fora de demo/loopback.

## 1. Executar e conferir localmente

Na raiz do checkout, com Python 3.12:

```powershell
.venv\Scripts\python.exe -m pip install -r dashboard/requirements.lock
$env:XFIT_DASHBOARD_DEMO='1'
.venv\Scripts\python.exe -m streamlit run dashboard/app.py --server.address=127.0.0.1
```

Abra http://127.0.0.1:8501. Demo usa fixture visual criada no codigo, nao fontes,
credenciais do pipeline ou uma exportacao do DW. Os valores nao sao os indicadores
reais da base demonstrativa do projeto. Para sair do demo, remova a variavel ou
defina `XFIT_DASHBOARD_DEMO=0` e reinicie o processo.

Tela: receita/margem/pedidos/itens/ticket, evolucao diaria, receita mensal por
unidade, mix de categorias, comparativo e taxas. Filtros seguem o
[contrato analitico](contrato_dashboard.md). Meta/atingimento ficam indisponiveis
em categoria ou mes parcial. Mes/unidade ausente nao gera total parcial de meta.
Avisos distinguem ultima venda, execucao e publicacao; nao prometem completude.

```powershell
.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_dashboard_app.py -v
```

Os testes AppTest verificam renderizacao, filtros, valores da fixture e bloqueio
sem autenticacao configurada. Nao comprovam login OIDC externo ou conexao remota.

## 2. Provisionar leitura BI, sem reutilizar o pipeline

No ambiente deste checkout, login BI local preparado e verificado em 18/10/2026.
A credencial exclusiva fica em `.streamlit/bi.local.json`, ignorada pelo Git e
com ACL limitada ao usuario Windows e SYSTEM. Nunca copiar esse arquivo para
Vercel, imagem Docker, chat ou documentacao. Nao e o login OIDC do usuario final.

Para reabrir a previa deste computador com o DW real:

```powershell
.venv\Scripts\python.exe -B -m dashboard.executar_local
```

Esse launcher usa porta 8502, bind exclusivo 127.0.0.1, demo desligado e leitura
direta das views. A previa local dispensa OIDC apenas nessa interface de loopback;
nao encaminhar sua porta por tunel, proxy ou compartilhamento. O aplicativo
nega essa modalidade em 0.0.0.0/interface publica. O Compose nao habilita o modo
local; portfolio publicado usa o modo publico explicito, separado da previa local.

O helper `dashboard.configurar_local` prepara um segredo novo sem sobrescrever
arquivo existente e deriva verificador SCRAM; nao cria roles ou conecta ao banco.
Os dados nao sao copiados para JSON/CSV: consultas continuam online via TLS.

Referencia para outros ambientes: executar como administrador em sessao segura, fora de logs
e do Git. Nao criar senha dentro de migration ou comando de shell. Exemplo SQL
sem senha, para um login que ainda nao exista:

```sql
begin;
create role xfit_dashboard_app login nosuperuser nocreatedb nocreaterole
    noinherit noreplication nobypassrls;
grant xfit_dashboard to xfit_dashboard_app with inherit false;
grant xfit_dashboard to xfit_dashboard_app with set true;
alter role xfit_dashboard_app set default_transaction_read_only = on;
commit;
```

Defina uma senha forte por ferramenta administrativa segura, por exemplo
`\password xfit_dashboard_app` no psql interativo. Confirme os grants efetivos,
leitura das cinco views e negacao de bases/escrita/escalada usando esse login.
Se o login ja existe, inspecione-o antes; nao recrie ou amplie acesso cegamente.
Todos os usuarios autorizados da v1 leem o mesmo escopo comercial agregado;
nao ha segregacao por filial/tenant. Essa necessidade exigiria outro contrato.

O backend conecta ao pooler de sessao 5432 com `xfit_dashboard_app.PROJECT_REF`,
faz `SET LOCAL ROLE xfit_dashboard`, transacao read-only, timeout de conexao de
8s e de consulta de 15s. TLS exige `verify-full` e CA oficial do projeto. Nao
trocar por sslmode=require nem usar postgres, service_role ou xfit_pipeline.
Nenhum segredo e lido do `.env` do pipeline. Nao existe fallback de credencial.

Para execucao local com DW, configure no processo exclusivamente:
`XFIT_BI_PG_HOST`, `XFIT_BI_PG_DATABASE`, `XFIT_BI_PG_USER`,
`XFIT_BI_PG_PASSWORD` e `XFIT_BI_PG_SSLROOTCERT`. Nao enviar valores pelo chat.

## 3. Modo privado opcional (substituido no portfolio publico)

Copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml` somente
no servidor/ambiente privado. O arquivo real e ignorado pelo Git. Configure um
cliente OIDC (exemplo fornecido: Google), cookie_secret aleatorio longo e
`dashboard.allowed_emails` com as contas explicitamente autorizadas.

Cadastre no provedor a URL exata `https://dashboard.SEUDOMINIO.com/oauth2callback`.
Para teste local separado, use `http://localhost:8501/oauth2callback` e ajuste
redirect_uri. Use credenciais de cliente apropriadas ao ambiente.

Com `XFIT_DASHBOARD_PUBLIC=0`, sem OIDC/lista configurados, a aplicacao bloqueia antes de consultar o banco.
Exige sessao autenticada, e-mail verificado, allowlist e claim `exp` vigente.
Tokens expirados exigem sair/entrar; a validade e conferida em cada execucao da
tela, nao continuamente em uma aba ociosa. Sem permissao, nenhuma view e lida.
Revogacao da allowlist exige atualizacao dos secrets/reinicio e atua na proxima
execucao; dados ja enviados ao navegador nao podem ser recolhidos.

Demo nao e bypass para dados reais: seleciona outro carregador, sem conexao BI.
No Compose AWS, demo fica explicitamente desligado e portfolio publico ligado. Credencial de banco fica
apenas no processo do servidor. SQL usa parametros para filtros; nao ha cache
global de dados ou downloads de dados brutos implementados pela aplicacao.

## 4. AWS EC2

Antes de criar recursos, confirme regiao, elegibilidade atual da conta, custos de
EC2/EBS/IPv4/trafego/DNS, orcamento e alertas. Free Tier nao garante custo zero;
alertas nao interrompem automaticamente gastos. Nenhum recurso e criado por
estes arquivos. Escolha capacidade apos medir memoria/carga, nao por uma promessa
de que qualquer instancia gratuita comporta o app.

Use Linux com Docker Engine e Compose v2. Prefira acesso administrativo via SSM
ou restrinja SSH ao seu IP. Security Group: HTTP 80/HTTPS 443 publicos para o
proxy; nunca exponha 8501 ou PostgreSQL. Autorize saida necessaria ao Supabase,
OIDC, DNS, registros de imagem e emissor TLS. Configure A/AAAA do subdominio para
o host correto; nao mantenha AAAA apontando a um destino sem IPv6 funcional.

Na EC2, checkout em `/opt/xfit` e segredos fora dele, por exemplo
`/opt/xfit-secrets`. No modo publico, prepare senha BI (uma linha) e CA oficial;
OIDC nao e montado. Restrinja o diretorio ao operador e os arquivos ao UID 10001
do container; por exemplo proprietario `10001:10001`, modo `0400`. Compose local
usa bind mounts para secrets: confira permissoes reais, nao confie em uid/gid
de secrets do Swarm. Nao conceda leitura global como solucao para erro de acesso.

Copie `deploy/aws/.env.example` para `deploy/aws/.env` privado e ajuste dominio,
host, usuario e caminhos absolutos dos arquivos. Nao ha senha nesse env de exemplo.

```sh
cd /opt/xfit
docker compose --env-file deploy/aws/.env -f deploy/aws/compose.yaml config --quiet
docker compose --env-file deploy/aws/.env -f deploy/aws/compose.yaml up -d --build
docker compose --env-file deploy/aws/.env -f deploy/aws/compose.yaml ps
```

O proxy Caddy termina HTTPS e encaminha WebSockets; certificados persistem em
volumes. Streamlit nao publica porta no host; executa com UID 10001, filesystem
read-only, tmpfs, capabilities removidas e limites de CPU/memoria. Healthcheck
testa o processo, nao autenticacao, conectividade BI ou indicadores.

Imagem Python e tag Caddy devem receber atualizacoes de seguranca revisadas.
Dependencias Python diretas/transitivas estao fixadas em dashboard/requirements.lock.
Build local validado nao substitui avaliacao de vulnerabilidades e monitoramento.
Dimensionar backup de configuracao/segredos e certificados separadamente do DW.

Atualizacao manual: revisar diff, obter versao aprovada do Git, reconstruir e
repetir smoke tests. Para rollback, voltar ao SHA anterior aprovado e reconstruir;
nao alterar schema/dados para fazer rollback desta interface. Nenhum workflow
faz deploy automatico/SSH nesta etapa.

## 5. Vercel

No projeto ja conectado ao GitHub, configure:

- Root Directory: `web` (nao a raiz do repositorio).
- Framework Preset: Other; sem Install Command/Build Command; Output Directory: `.`.
- Nao configure variaveis de banco, Supabase ou OIDC na Vercel para esta pagina.

Antes do deploy, revise o diff e a allowlist de arquivos: nao publicar dados,
backups, `.env`, secrets.toml ou registros operacionais. web/vercel.json define
headers de seguranca; a pagina nao consulta banco nem carrega scripts terceiros.
O link fica desabilitado enquanto a URL nao foi definida.

Depois da AWS validada, preencha `window.XFIT_DASHBOARD_URL` em `web/config.js`
somente com a URL HTTPS publica do dashboard, sem tokens/senhas/query secrets.
Versione essa URL e publique a pagina. OIDC e cookies pertencem ao dominio AWS;
autenticacao na pagina Vercel nao protege automaticamente o Streamlit.

## 6. Smoke test obrigatorio antes de declarar deploy concluido

1. HTTPS valido, redirecionamento HTTP e WebSocket funcional pelo dominio AWS.
2. No portfolio publico, indicadores acessiveis sem login e sem sessao Google;
   arquivos privados e detalhes de excecoes nao podem ser enviados ao cliente.
3. Se for reativar modo privado, montar OIDC, desligar PUBLIC e repetir login,
   logout e negacao de contas fora da allowlist/tokens expirados antes de publicar.
4. Login BI real: somente views, escrita/bases/owner/pipeline negados, TLS verificado.
5. Julho/2026, todos os filtros: comparar SQL com receita concluida R$ 153.960,75,
   1.138 pedidos e atingimento 74,53%, caso a base ainda seja a mesma referencia.
6. Categoria desabilita meta; mes parcial tambem; filtro vazio e falha do banco
   exibem mensagem controlada, sem credenciais ou traceback no navegador.
7. Mobile e desktop; pagina Vercel direciona ao dominio correto. Verificar headers
   no ambiente real, nao apenas no servidor estatico local.
8. Conferir memoria, tempo de resposta, custos, logs sanitizados e ausencia de
   arquivos privados na imagem/artefatos. Processo saudavel nao prova esses itens.

## Implantacao verificada em 28/10/2026

Dashboard: https://xfit.3.133.147.43.sslip.io/ (AWS Free plan, beneficio temporario).
Apresentacao: https://x-fit-wear.vercel.app/ (Vercel Hobby).
Login Google, logout, TLS/privilegios BI, HTTPS/headers e arquivos privados
ausentes na Vercel verificados; detalhes e limites em CONTEXTO_ATUAL.md e no
adendo da auditoria. Publicacao Vercel direta de web/, sem commit/push.
Nao fazer upgrade dos planos. O hostname AWS depende do IP publico atual;
parar/iniciar a EC2 pode mudar esse IP e exige rever DNS/hostname e retorno OAuth.
Segredos OAuth antigos sem uso devem ser removidos pelo usuario no Google Cloud,
preservando o segredo substituto instalado. Nao reutilizar arquivos revogados.
