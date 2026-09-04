# Operacao e seguranca do projeto xFit Wear

## Premissa obrigatoria

Apesar de as fontes atuais serem sinteticas, este projeto deve ser tratado como
um projeto real com dados reais de cliente.

O objetivo da construcao local e preparar uma base tecnica que possa evoluir
para deploy e operacao para cliente. Portanto, toda nova fase deve considerar:

- preservacao de dados antes de sobrescrita;
- logs de processo por etapa;
- identificador unico de carga;
- validacao antes de promocao para camadas analiticas;
- mensagens de erro sem vazamento de caminhos locais, segredos ou dados sensiveis;
- separacao entre dado bruto, staging, DW e artefatos operacionais;
- possibilidade futura de rollback, auditoria e rastreabilidade.

## Fase 10 - Auditoria e protecao do data lake local

Esta fase cria uma trilha local para os arquivos injetados no pipeline.

Artefato principal:

```text
src/data_lake_audit.py
```

Contrato versionavel das fontes:

```text
config/data_sources.json
```

Responsabilidades:

- gerar `carga_id`;
- ler o contrato de fontes em `config/data_sources.json`;
- calcular `sha256`, tamanho e quantidade de registros por fonte;
- criar manifesto em `data/processed/manifests/`;
- registrar execucao em `data/processed/logs/etl_runs.jsonl`;
- criar backup opcional em `data/processed/backups/<carga_id>/`;
- bloquear backup de caminhos fora do projeto.

Comandos:

```bash
python src/data_lake_audit.py
python src/data_lake_audit.py --backup
python src/data_lake_audit.py --self-test
```

## Gate antes do DW

Antes de criar ou atualizar `dw`, rode:

```bash
python src/data_lake_audit.py --backup
python src/validate_staging.py
```

O projeto so deve promover dados para DW quando:

- o manifesto do data lake for gerado sem erro;
- o backup local tiver sido criado para a carga;
- `validate_staging.py` retornar `pode_promover_dw: True`;
- erros e alertas forem analisados e registrados.

## Risco residual atual

Ainda nao existe banco, transacao real, RLS, usuario, autorizacao, deploy ou
armazenamento remoto. A protecao atual e local e baseada em arquivos.

Quando o projeto migrar para Supabase/PostgreSQL, estes controles devem virar
tabelas e transacoes reais, por exemplo:

- `etl.cargas`;
- `etl.manifestos_arquivo`;
- `etl.rejeicoes`;
- `etl.log_falhas`;
- rollback transacional da carga;
- RLS e grants minimos quando houver dados privados expostos.
