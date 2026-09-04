from __future__ import annotations

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
