# Dicionario de dados - xFit Wear

Fontes principais:
- `data/raw/lojas_fisicas/vendas_barbacena.csv`: vendas da loja fisica de Barbacena, MG.
- `data/raw/lojas_fisicas/vendas_conselheiro_lafaiete.csv`: vendas da loja fisica de Conselheiro Lafaiete, MG.
- `data/api/vendas_online_api.json`: base que simula o payload de uma API de ecommerce.
- `data/api/mock_api_server.py`: servidor HTTP local, sem dependencias externas, para consumir a fonte online por API.
- `data/reference/metas_mensais.csv`: metas por mes e canal/unidade.
- `data/reference/produtos.csv`: cadastro simples de produtos.

Observacoes para ETL:
- CSVs usam `;` como delimitador e `utf-8-sig` para abrir bem no Excel.
- Valores monetarios estao em BRL e usam ponto decimal.
- `status_pedido = cancelada` zera receita liquida e margem.
- `status_pedido = devolvida` mantem a venda registrada para permitir analise de devolucao.
- A fonte online tem campos extras de entrega, origem, frete e cupom.
- Lojas fisicas operam de segunda a sabado; ecommerce opera em dias corridos.
- A serie inclui sazonalidade de verao, Dia das Maes, Namorados, volta aos treinos, Black Friday, dezembro, dias de pagamento e choque/recuperacao de 2020.

Metricas sugeridas:
- Receita liquida, margem bruta, margem %, ticket medio, pedidos, itens vendidos.
- Taxa de devolucao e cancelamento.
- Atingimento de meta por mes, canal e unidade.
- Mix de categoria, forma de pagamento, campanha e origem de trafego.
