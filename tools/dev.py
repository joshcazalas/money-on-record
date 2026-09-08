"""Serve only the frontend on loopback, with automatic reload and no build step."""

from __future__ import annotations

import argparse
import hashlib
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from os import PathLike
from pathlib import Path
from socket import socket
from socketserver import BaseServer
from urllib.parse import unquote, urlsplit

from build_local_data import build

from money_on_record_l0.record_browser import load_publications

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def revision() -> str:
    files = sorted(path for path in FRONTEND.rglob("*") if path.is_file())
    stamp = "|".join(f"{path.relative_to(FRONTEND)}:{path.stat().st_mtime_ns}" for path in files)
    return hashlib.sha256(stamp.encode()).hexdigest()[:16]


class Handler(SimpleHTTPRequestHandler):
    def __init__(
        self, request: socket, client_address: tuple[str, int], server: BaseServer
    ) -> None:
        super().__init__(request, client_address, server, directory=str(FRONTEND))

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/__dev/revision":
            payload = json.dumps({"revision": revision()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()

    def translate_path(self, path: str) -> str:
        # Do not follow links outside the frontend or expose dotfiles/repository data.
        resolved = Path(super().translate_path(path)).resolve()
        parts = Path(unquote(urlsplit(path).path)).parts
        if not resolved.is_relative_to(FRONTEND) or any(p.startswith(".") for p in parts):
            return str(FRONTEND / "__not_found__")
        return str(resolved)

    def list_directory(self, path: str | PathLike[str]) -> None:
        self.send_error(404)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--rebuild-data", action="store_true")
    args = parser.parse_args()
    if args.rebuild_data:
        build(force=True)
    else:
        for name, payload in load_publications(FRONTEND.parent / "site/content.json").items():
            destination = FRONTEND / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists() or destination.read_bytes() != payload:
                destination.write_bytes(payload)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"\nMoney on Record: http://localhost:{args.port}", flush=True)
    print("Edits reload automatically. Ctrl+C stops the server.\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
