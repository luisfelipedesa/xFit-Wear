from __future__ import annotations

import csv
import json
import math
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw" / "lojas_fisicas"
API = ROOT / "data" / "api"
REF = ROOT / "data" / "reference"

random.seed(7407)

PHYSICAL_START = date(2018, 11, 1)
ONLINE_START = date(2020, 4, 1)
DATA_END = date(2026, 7, 31)
GOALS_END = date(2026, 12, 1)


PRODUTOS = [
    ("XFIT-LEG-001", "Legging PowerFlex", "Feminino", "Leggings", 139.90, 57.80),
    ("XFIT-TOP-002", "Top Alta Sustentacao", "Feminino", "Tops", 99.90, 39.20),
    ("XFIT-SHO-003", "Shorts DryRun", "Feminino", "Shorts", 89.90, 35.50),
    ("XFIT-CAM-004", "Camiseta Training", "Unissex", "Camisetas", 79.90, 31.70),
    ("XFIT-REG-005", "Regata Essential", "Unissex", "Regatas", 69.90, 27.60),
    ("XFIT-JAQ-006", "Jaqueta WindFit", "Unissex", "Jaquetas", 219.90, 98.40),
    ("XFIT-CAL-007", "Calca Jogger Move", "Masculino", "Calcas", 159.90, 70.20),
    ("XFIT-BER-008", "Bermuda Sprint", "Masculino", "Bermudas", 109.90, 45.10),
    ("XFIT-MAC-009", "Macacao Studio", "Feminino", "Macacoes", 189.90, 82.30),
    ("XFIT-MEI-010", "Meia Performance", "Unissex", "Acessorios", 29.90, 9.80),
    ("XFIT-GAR-011", "Garrafa Termica 750ml", "Unissex", "Acessorios", 64.90, 24.90),
    ("XFIT-BOL-012", "Bolsa Gym Pro", "Unissex", "Acessorios", 149.90, 63.40),
]

CORES = ["Preto", "Grafite", "Azul Marinho", "Verde Oliva", "Rosa", "Vinho", "Branco"]
TAMANHOS = ["PP", "P", "M", "G", "GG"]
PAGAMENTOS = ["credito", "debito", "pix", "dinheiro"]
ONLINE_PAGAMENTOS = ["credito", "pix", "boleto"]
ORIGENS = ["instagram_ads", "google_ads", "organico", "email", "marketplace", "influencer"]
CAMPANHAS = ["sem_campanha", "verao_fit", "dia_das_maes", "namorados", "black_friday", "volta_treino"]
UFS = [
    ("SP", "Sao Paulo", 16),
    ("RJ", "Rio de Janeiro", 10),
    ("MG", "Belo Horizonte", 18),
    ("MG", "Juiz de Fora", 6),
    ("MG", "Barbacena", 5),
    ("MG", "Conselheiro Lafaiete", 4),
    ("ES", "Vitoria", 4),
    ("RS", "Porto Alegre", 5),
    ("PR", "Curitiba", 5),
    ("SC", "Florianopolis", 4),
    ("BA", "Salvador", 4),
    ("PE", "Recife", 3),
    ("GO", "Goiania", 3),
    ("DF", "Brasilia", 5),
    ("CE", "Fortaleza", 3),
    ("PA", "Belem", 2),
    ("AM", "Manaus", 1),
    ("MT", "Cuiaba", 2),
]


def month_iter(start: date, end: date):
    current = date(start.year, start.month, 1)
    while current <= end:
        yield current
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def year_growth_factor(day: date, channel: str) -> float:
    """Synthetic macro curve: local stores felt 2020 harder; ecommerce accelerated."""
    year_map = {
        "loja_fisica": {
            2018: 0.70,
            2019: 0.82,
            2020: 0.58,
            2021: 0.73,
            2022: 0.92,
            2023: 1.00,
            2024: 1.08,
            2025: 1.17,
            2026: 1.25,
        },
        "ecommerce": {
            2020: 0.78,
            2021: 0.95,
            2022: 1.05,
            2023: 1.16,
            2024: 1.30,
            2025: 1.45,
            2026: 1.57,
        },
    }
    base = year_map[channel].get(day.year, 1.0)
    if day.year == 2020 and channel == "loja_fisica" and day.month in (3, 4, 5, 6):
        base *= 0.62
    if day.year == 2020 and channel == "ecommerce" and day.month in (4, 5, 6, 7):
        base *= 1.20
    return base


def seasonal_factor(day: date) -> float:
    factor = 1.0
    if day.month in (1, 2):
        factor += 0.18
    if day.month == 3:
        factor += 0.07
    if day.month == 5:
        factor += 0.08
    if day.month == 6:
        factor += 0.05
    if day.month in (8, 9):
        factor += 0.12
    if day.month == 11:
        factor += 0.32
    if day.month == 12:
        factor += 0.16
    if day.weekday() in (4, 5):
        factor += 0.18
    return factor


def payday_factor(day: date) -> float:
    if 3 <= day.day <= 10:
        return 1.10
    if 20 <= day.day <= 25:
        return 1.05
    return 1.0


def campaign_for_day(day: date) -> str:
    if day.month == 11:
        return random.choices(["black_friday", "sem_campanha"], weights=[55, 45], k=1)[0]
    if day.month in (1, 2):
        return random.choices(["verao_fit", "volta_treino", "sem_campanha"], weights=[38, 26, 36], k=1)[0]
    if day.month == 5:
        return random.choices(["dia_das_maes", "sem_campanha"], weights=[34, 66], k=1)[0]
    if day.month == 6:
        return random.choices(["namorados", "sem_campanha"], weights=[28, 72], k=1)[0]
    if day.month in (8, 9):
        return random.choices(["volta_treino", "sem_campanha"], weights=[30, 70], k=1)[0]
    return random.choices(CAMPANHAS, weights=[76, 6, 4, 4, 4, 6], k=1)[0]


def product_for_day(day: date):
    weights_by_category = {
        "Leggings": 18,
        "Tops": 15,
        "Shorts": 12,
        "Camisetas": 13,
        "Regatas": 9,
        "Jaquetas": 4,
        "Calcas": 8,
        "Bermudas": 8,
        "Macacoes": 4,
        "Acessorios": 9,
    }
    if day.month in (5, 6, 7):
        weights_by_category["Jaquetas"] += 8
        weights_by_category["Calcas"] += 5
    if day.month in (12, 1, 2, 3):
        weights_by_category["Shorts"] += 6
        weights_by_category["Regatas"] += 5
        weights_by_category["Bermudas"] += 4
    if day.month == 11:
        weights_by_category["Acessorios"] += 8

    weights = [weights_by_category[p[3]] for p in PRODUTOS]
    return random.choices(PRODUTOS, weights=weights, k=1)[0]


def random_time(online: bool) -> str:
    hour = random.choices(
        range(8, 23) if not online else range(0, 24),
        weights=[2, 3, 4, 6, 7, 8, 8, 7, 5, 6, 7, 6, 4, 3, 2] if not online else None,
        k=1,
    )[0]
    return f"{hour:02d}:{random.randrange(60):02d}:{random.randrange(60):02d}"


def money(value: float) -> str:
    return f"{value:.2f}"


def make_sale(prefix: str, seq: int, sale_day: date, physical_store: dict | None) -> dict:
    product_id, produto, genero, categoria, preco, custo = product_for_day(sale_day)
    qtd = random.choices([1, 2, 3], weights=[80, 17, 3], k=1)[0]
    campanha = campaign_for_day(sale_day)
    desconto_base = [0, 0, 0, 0.05, 0.10, 0.15]
    if campanha == "black_friday":
        desconto_base.extend([0.20, 0.25, 0.30])
    elif campanha != "sem_campanha":
        desconto_base.extend([0.10, 0.15, 0.20])
    desconto_pct = random.choice(desconto_base)
    bruto = preco * qtd
    desconto = bruto * desconto_pct
    liquido = bruto - desconto
    custo_total = custo * qtd
    margem = liquido - custo_total
    status = random.choices(
        ["concluida", "devolvida", "cancelada"],
        weights=[94, 4, 2] if physical_store else [91, 6, 3],
        k=1,
    )[0]
    if status == "cancelada":
        liquido = 0
        margem = 0

    row = {
        "id_venda": f"{prefix}-{seq:06d}",
        "data_venda": sale_day.isoformat(),
        "hora_venda": random_time(online=physical_store is None),
        "cliente_id": f"CLI-{random.randrange(1, 2800):05d}",
        "genero_cliente": random.choices(["F", "M", "Nao informado"], weights=[67, 28, 5], k=1)[0],
        "faixa_etaria": random.choices(["18-24", "25-34", "35-44", "45-54", "55+"], weights=[18, 36, 25, 14, 7], k=1)[0],
        "produto_id": product_id,
        "produto": produto,
        "genero_produto": genero,
        "categoria": categoria,
        "tamanho": random.choice(TAMANHOS),
        "cor": random.choice(CORES),
        "quantidade": qtd,
        "preco_unitario": money(preco),
        "desconto_pct": f"{desconto_pct:.2f}",
        "valor_desconto": money(desconto),
        "valor_bruto": money(bruto),
        "valor_liquido": money(liquido),
        "custo_unitario": money(custo),
        "custo_total": money(custo_total),
        "margem_bruta": money(margem),
        "status_pedido": status,
        "campanha": campanha,
    }

    if physical_store:
        row.update(
            {
                "canal": "loja_fisica",
                "loja_id": physical_store["loja_id"],
                "loja_nome": physical_store["loja_nome"],
                "cidade": physical_store["cidade"],
                "uf": "MG",
                "vendedor_id": f"VND-{physical_store['loja_id']}-{random.randrange(1, 7):02d}",
                "forma_pagamento": random.choice(PAGAMENTOS),
            }
        )
    else:
        uf, cidade, _weight = random.choices(UFS, weights=[item[2] for item in UFS], k=1)[0]
        row.update(
            {
                "canal": "ecommerce",
                "pedido_online_id": f"WEB-{seq:07d}",
                "cidade_entrega": cidade,
                "uf_entrega": uf,
                "regiao_entrega": regiao_por_uf(uf),
                "forma_pagamento": random.choice(ONLINE_PAGAMENTOS),
                "canal_origem": random.choice(ORIGENS),
                "frete_cobrado": money(random.choice([0, 9.9, 14.9, 19.9, 24.9])),
                "prazo_entrega_dias": random.randint(2, 12),
                "cupom": random.choice(["", "", "", "PRIMEIRA10", "FIT15", "FRETEGRATIS"]),
            }
        )
    return row


def regiao_por_uf(uf: str) -> str:
    if uf in {"SP", "RJ", "MG", "ES"}:
        return "Sudeste"
    if uf in {"RS", "PR", "SC"}:
        return "Sul"
    if uf in {"BA", "PE", "CE"}:
        return "Nordeste"
    if uf in {"GO", "DF", "MT"}:
        return "Centro-Oeste"
    return "Norte"


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def build_physical_sales(store: dict, prefix: str, base_daily: float) -> list[dict]:
    rows = []
    seq = 1
    for day in daterange(PHYSICAL_START, DATA_END):
        if day.weekday() == 6:
            continue
        ramp = min(1.0, 0.35 + ((day - PHYSICAL_START).days / 365) * 0.25)
        lam = base_daily * ramp * seasonal_factor(day) * payday_factor(day) * year_growth_factor(day, "loja_fisica")
        count = max(0, int(random.gauss(lam, max(1.4, lam * 0.20))))
        for _ in range(count):
            rows.append(make_sale(prefix, seq, day, store))
            seq += 1
    return rows


def build_online_sales() -> list[dict]:
    rows = []
    seq = 1
    for day in daterange(ONLINE_START, DATA_END):
        months_live = (day.year - ONLINE_START.year) * 12 + (day.month - ONLINE_START.month)
        ramp = min(1.0, 0.38 + months_live * 0.018)
        lam = 10.5 * ramp * seasonal_factor(day) * payday_factor(day) * year_growth_factor(day, "ecommerce")
        if day.month == 11:
            lam += 7
        count = max(1, int(random.gauss(lam, max(2.0, lam * 0.24))))
        for _ in range(count):
            rows.append(make_sale("ONL", seq, day, None))
            seq += 1
    return rows


def build_goals() -> list[dict]:
    rows = []
    channels = [
        ("loja_fisica", "LJ-BQ", "Barbacena", "MG", 42000, 310, PHYSICAL_START),
        ("loja_fisica", "LJ-CL", "Conselheiro Lafaiete", "MG", 48000, 350, PHYSICAL_START),
        ("ecommerce", "EC-BR", "Brasil", "BR", 56000, 430, ONLINE_START),
    ]
    for month in month_iter(PHYSICAL_START, GOALS_END):
        for canal, unidade_id, cidade, uf, base_revenue, base_orders, start_date in channels:
            if month < date(start_date.year, start_date.month, 1):
                continue
            months_active = (month.year - start_date.year) * 12 + (month.month - start_date.month)
            ramp = min(1.0, 0.55 + months_active * 0.012)
            growth = ramp * year_growth_factor(month, canal)
            factor = seasonal_factor(month)
            if canal == "ecommerce":
                factor += 0.07
            receita = base_revenue * growth * factor
            pedidos = math.ceil(base_orders * growth * factor)
            rows.append(
                {
                    "ano_mes": month.strftime("%Y-%m"),
                    "canal": canal,
                    "unidade_id": unidade_id,
                    "cidade": cidade,
                    "uf": uf,
                    "meta_receita_liquida": money(receita),
                    "meta_pedidos": pedidos,
                    "meta_ticket_medio": money(receita / pedidos),
                    "meta_margem_bruta_pct": "0.48" if canal == "ecommerce" else "0.52",
                    "meta_taxa_devolucao_pct": "0.06" if canal == "ecommerce" else "0.04",
                    "inicio_operacao": start_date.isoformat(),
                    "observacao": "meta_planejada" if month > DATA_END else "meta_historica",
                }
            )
    return rows


def write_api_files(rows: list[dict]) -> None:
    API.mkdir(parents=True, exist_ok=True)
    payload = {
        "api_name": "xfit-wear-vendas-online",
        "version": "v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_system": "mock_ecommerce_api",
        "total_records": len(rows),
        "records": rows,
    }
    (API / "vendas_online_api.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_reference_files(goals: list[dict]) -> None:
    REF.mkdir(parents=True, exist_ok=True)
    product_rows = [
        {
            "produto_id": p[0],
            "produto": p[1],
            "genero_produto": p[2],
            "categoria": p[3],
            "preco_lista": money(p[4]),
            "custo_padrao": money(p[5]),
        }
        for p in PRODUTOS
    ]
    write_csv(REF / "produtos.csv", product_rows)
    write_csv(REF / "metas_mensais.csv", goals)
    (REF / "dicionario_dados.md").write_text(
        """# Dicionario de dados - xFit Wear

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
""",
        encoding="utf-8",
    )


def write_mock_api_server() -> None:
    (API / "mock_api_server.py").write_text(
        '''from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DATA_FILE = Path(__file__).with_name("vendas_online_api.json")


def parse_positive_int(params: dict, nome: str, padrao: int, limite: int | None = None) -> int:
    try:
        valor = int(params.get(nome, [str(padrao)])[0])
    except ValueError as erro:
        raise ValueError(f"{nome} deve ser inteiro") from erro

    valor = max(1, valor)
    if limite is not None:
        valor = min(limite, valor)
    return valor


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/", "/v1/vendas-online", "/v1/health"}:
            self._send_json({"error": "endpoint_not_found"}, 404)
            return

        if parsed.path in {"/", "/v1/health"}:
            self._send_json({"status": "ok", "endpoint": "/v1/vendas-online"})
            return

        payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        params = parse_qs(parsed.query)
        try:
            page = parse_positive_int(params, "page", 1)
            page_size = parse_positive_int(params, "page_size", 100, limite=500)
        except ValueError as erro:
            self._send_json({"error": "invalid_query_param", "message": str(erro)}, 400)
            return

        records = payload["records"]
        start = (page - 1) * page_size
        end = start + page_size
        self._send_json(
            {
                "page": page,
                "page_size": page_size,
                "total_records": len(records),
                "total_pages": (len(records) + page_size - 1) // page_size,
                "data": records[start:end],
            }
        )


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8000), Handler)
    print("API mock xFit Wear em http://127.0.0.1:8000/v1/vendas-online?page=1&page_size=100")
    server.serve_forever()
''',
        encoding="utf-8",
    )


def arquivos_gerados() -> list[Path]:
    return [
        RAW / "vendas_barbacena.csv",
        RAW / "vendas_conselheiro_lafaiete.csv",
        API / "vendas_online_api.json",
        REF / "produtos.csv",
        REF / "metas_mensais.csv",
        REF / "dicionario_dados.md",
        API / "mock_api_server.py",
    ]


def validar_sobrescrita_autorizada() -> None:
    existentes = [path for path in arquivos_gerados() if path.exists()]
    if existentes and "--force" not in sys.argv:
        print("Geracao bloqueada: arquivos de fonte ja existem.")
        print("Rode `python src/data_lake_audit.py --backup` antes de sobrescrever.")
        print("Depois use `python gerar_fontes_xfit.py --force` se a sobrescrita for intencional.")
        raise SystemExit(2)


def main() -> None:
    validar_sobrescrita_autorizada()

    barbacena = {"loja_id": "LJ-BQ", "loja_nome": "xFit Wear Barbacena", "cidade": "Barbacena"}
    conselheiro = {"loja_id": "LJ-CL", "loja_nome": "xFit Wear Conselheiro Lafaiete", "cidade": "Conselheiro Lafaiete"}

    rows_bq = build_physical_sales(barbacena, "BQ", 8.2)
    rows_cl = build_physical_sales(conselheiro, "CL", 9.6)
    rows_online = build_online_sales()
    goals = build_goals()

    write_csv(RAW / "vendas_barbacena.csv", rows_bq)
    write_csv(RAW / "vendas_conselheiro_lafaiete.csv", rows_cl)
    write_api_files(rows_online)
    write_reference_files(goals)
    write_mock_api_server()

    print(json.dumps({
        "vendas_barbacena": len(rows_bq),
        "vendas_conselheiro_lafaiete": len(rows_cl),
        "vendas_online_api": len(rows_online),
        "metas_mensais": len(goals),
    }, indent=2))


if __name__ == "__main__":
    main()
