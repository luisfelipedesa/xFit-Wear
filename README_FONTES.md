# xFit Wear - Fontes de dados para BI

Este pacote contem fontes simuladas para um projeto de BI em Python de uma loja de roupas fitness.

## Fontes principais

- `data/raw/lojas_fisicas/vendas_barbacena.csv`
  - Vendas da loja fisica de Barbacena, MG, de 2018-11-01 a 2026-07-31.
- `data/raw/lojas_fisicas/vendas_conselheiro_lafaiete.csv`
  - Vendas da loja fisica de Conselheiro Lafaiete, MG, de 2018-11-01 a 2026-07-31.
- `data/api/vendas_online_api.json`
  - Base de vendas online usada pelo servidor mock de API, de 2020-04-01 a 2026-07-31.
- `data/api/mock_api_server.py`
  - API local simples para consumo via HTTP.

## Metas e cadastros

- `data/reference/metas_mensais.csv`
  - Metas mensais por canal/unidade, de 2018-11 a 2026-12.
- `data/reference/produtos.csv`
  - Cadastro de produtos, categoria, preco de lista e custo padrao.
- `data/reference/dicionario_dados.md`
  - Regras de leitura, campos e metricas sugeridas.

## Volume gerado

- Barbacena: 18.740 linhas.
- Conselheiro Lafaiete: 22.349 linhas.
- Ecommerce/API: 30.486 registros.
- Metas mensais: 277 linhas.

## Regras de simulacao

- Lojas fisicas operam de segunda a sabado; ecommerce opera todos os dias.
- A serie considera verao/volta aos treinos, Dia das Maes, Dia dos Namorados, Black Friday, dezembro e dias de pagamento.
- O historico inclui queda e recuperacao de 2020 nas lojas fisicas e crescimento acelerado do ecommerce a partir de abril de 2020.
- A distribuicao do ecommerce privilegia Sudeste e Minas Gerais, mas inclui outras regioes para permitir analises nacionais.
- Os dados sao ficticios e servem para portfolio; nao representam vendas reais.

## Como consumir a API online

Execute:

```bash
python data/api/mock_api_server.py
```

Endpoint:

```text
GET http://127.0.0.1:8000/v1/vendas-online?page=1&page_size=100
```

Exemplo de retorno:

```json
{
  "page": 1,
  "page_size": 100,
  "total_records": 30486,
  "total_pages": 305,
  "data": []
}
```

## Ideias de metricas

- Receita liquida
- Margem bruta e margem %
- Ticket medio
- Pedidos e itens vendidos
- Taxa de devolucao
- Taxa de cancelamento
- Atingimento de meta
- Mix por categoria, campanha, forma de pagamento e origem de trafego
