"""Minimal HTTP API for the Computer sandbox. No secrets, no DB, no host mounts except /workspaces."""

from __future__ import annotations

import hmac
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import workspace_fs


def sandbox_token_ok(header: str | None, expected: str | None = None) -> bool:
    """Shared secret between the backend and this API. Empty token fails closed."""
    secret = expected if expected is not None else (os.environ.get("SANDBOX_TOKEN") or "")
    provided = header or ""
    if not secret or not provided:
        return False
    return hmac.compare_digest(provided, secret)


def bind_host() -> str:
    """Listen on the container address, not 0.0.0.0, so 127.0.0.1 does not reach /v1/op."""
    explicit = (os.environ.get("SANDBOX_HOST") or "").strip()
    if explicit:
        return explicit
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 1))
        ip = sock.getsockname()[0]
    except OSError:
        ip = ""
    finally:
        sock.close()
    if ip and not ip.startswith("127."):
        return ip
    return ip or "127.0.0.1"


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
        if not sandbox_token_ok(self.headers.get("X-Sandbox-Token")):
            self._send(401, {"error": "unauthorized"})
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
    host = bind_host()
    port = int(os.environ.get("SANDBOX_PORT") or 8090)
    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
