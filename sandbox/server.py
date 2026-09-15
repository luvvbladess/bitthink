"""Minimal HTTP API for the Computer sandbox. No secrets, no DB, no host mounts except /workspaces."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import workspace_fs


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._send(200, {"status": "ok"})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/op":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 9_000_000:
            self._send(400, {"error": "bad body"})
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send(400, {"error": "invalid json"})
            return
        if not isinstance(data, dict):
            self._send(400, {"error": "object required"})
            return
        try:
            user_id = int(data.get("user_id"))
            op = str(data.get("op") or "")
            text = workspace_fs.dispatch(user_id, op, data)
        except Exception as exc:
            self._send(400, {"error": str(exc)[:400]})
            return
        self._send(200, {"text": text})


def main() -> None:
    os.environ.setdefault("WORKSPACES_DIR", "/workspaces")
    os.environ["SANDBOX_MODE"] = "1"
    os.environ["WORKSPACE_ALLOW_LOCAL_RUN"] = "1"
    host = os.environ.get("SANDBOX_HOST", "0.0.0.0")
    port = int(os.environ.get("SANDBOX_PORT") or 8090)
    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
