#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import statistics
import urllib.parse

import crawler

HOST = "127.0.0.1"
PORT = int(os.environ.get("CRAWLER_PORT", "8000"))
PROJECT_ROOT = Path(__file__).resolve().parent


class CrawlerUIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/crawl":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada."})
            return

        try:
            payload = self.read_json()
            response = self.run_crawl(payload)
        except ValueError as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "Falha ao executar a varredura.", "detail": str(exc)},
            )
            return

        self.send_json(HTTPStatus.OK, response)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 100_000:
            raise ValueError("Corpo da requisição inválido.")

        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError("JSON inválido.") from exc

    def run_crawl(self, payload):
        city = str(payload.get("city", "")).strip()
        state = str(payload.get("state", "")).strip().upper()

        if len(city) < 2:
            raise ValueError("Informe uma cidade válida.")
        if len(state) != 2 or not state.isalpha():
            raise ValueError("Informe uma UF válida.")

        limit = max(1, min(int(payload.get("limit", 10)), 50))
        pages = max(1, min(int(payload.get("pages", 1)), 5))
        names = payload.get("sources") or []

        if not isinstance(names, list) or not names:
            raise ValueError("Selecione pelo menos uma fonte.")

        selected = crawler.select_sources(
            [str(name).strip().lower() for name in names]
        )

        report = asyncio.run(
            crawler.crawl_city(
                city=city,
                state=state,
                sources=selected,
                pages=pages,
                per_source_limit=limit,
                concurrency=4,
                respect_robots=True,
            )
        )

        listings = crawler.deduplicate(report.listings)
        crawler.save_outputs(listings, PROJECT_ROOT / "data")

        prices = [item.price for item in listings if item.price]
        ppm2 = [item.price_per_m2 for item in listings if item.price_per_m2]

        return {
            "query": {
                "city": city,
                "state": state,
                "limit": limit,
                "pages": pages,
                "sources": [source.name for source in selected],
            },
            "summary": {
                "listings": len(listings),
                "median_price": statistics.median(prices) if prices else None,
                "median_price_per_m2": statistics.median(ppm2) if ppm2 else None,
                "sources_with_results": sum(
                    1 for source in report.sources if source.successful > 0
                ),
            },
            "sources": [
                {
                    "source": source.source,
                    "discovered_urls": len(source.discovered_urls),
                    "successful": source.successful,
                    "failed": source.failed,
                    "skipped_by_robots": source.skipped_by_robots,
                    "errors": source.errors[:5],
                }
                for source in report.sources
            ],
            "listings": [item.to_dict() for item in listings],
        }

    def log_message(self, fmt, *args):
        print(f"[web] {self.address_string()} - {fmt % args}")

    def send_json(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    server = ThreadingHTTPServer((HOST, PORT), CrawlerUIHandler)
    print(f"Multi Source Crawler disponível em http://{HOST}:{PORT}")
    print("Pressione Ctrl+C para encerrar.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()
