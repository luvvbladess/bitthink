"""Healthcheck that skips sitecustomize (python -S). /health answers on loopback; only /v1/op refuses it."""

import json
import os
from urllib.request import urlopen


def main() -> None:
    host = (os.environ.get("SANDBOX_HOST") or "").strip()
    if host in {"", "0.0.0.0"}:
        host = "127.0.0.1"
    port = int(os.environ.get("SANDBOX_PORT") or 8090)
    with urlopen(f"http://{host}:{port}/health", timeout=2) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("status") != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
