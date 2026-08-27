from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DATA_FILE = Path(__file__).with_name("vendas_online_api.json")


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
        page = max(1, int(params.get("page", ["1"])[0]))
        page_size = min(500, max(1, int(params.get("page_size", ["100"])[0])))
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
