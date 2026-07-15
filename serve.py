#!/usr/bin/env python3
"""Tiny static server for Lumi's Math Garden.

Python's stock http.server sometimes labels .js as text/plain, which modern
browsers reject for ES modules. This server forces the correct MIME types and
disables caching so edits show up immediately during development.

    python3 serve.py [port]   # default 4173
"""
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

MIME = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".webmanifest": "application/manifest+json",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".html": "text/html; charset=utf-8",
}


class Handler(SimpleHTTPRequestHandler):
    def guess_type(self, path):
        for ext, mime in MIME.items():
            if path.endswith(ext):
                return mime
        return super().guess_type(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass  # keep the console quiet


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4173
    print(f"🌱 Lumi's Math Garden serving at http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
