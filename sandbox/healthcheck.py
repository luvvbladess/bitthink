"""Healthcheck that skips sitecustomize (python -S) and talks to the non-loopback bind."""

import json
import os
import socket
from urllib.request import urlopen


def bind_host() -> str:
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


def main() -> None:
    host = bind_host()
    port = int(os.environ.get("SANDBOX_PORT") or 8090)
    with urlopen(f"http://{host}:{port}/health", timeout=2) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("status") != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
