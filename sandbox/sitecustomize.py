"""Block private/internal addresses from user Python and pip inside the sandbox."""

from __future__ import annotations

import ipaddress
import socket

_BLOCK_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)
_BLOCK_HOSTS = {
    "localhost",
    "db",
    "backend",
    "frontend",
    "metadata.google.internal",
    "host.docker.internal",
}


def _own_ips() -> set[str]:
    """Addresses of this container. User code must not call the sandbox API on them."""
    found: set[str] = set()
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 1))
            found.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None):
            sockaddr = item[4] if len(item) > 4 else None
            if isinstance(sockaddr, tuple) and sockaddr and isinstance(sockaddr[0], str):
                found.add(sockaddr[0])
    except OSError:
        pass
    return {ip for ip in found if ip and not ip.startswith("127.")}


_OWN_IPS = _own_ips()


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _blocked_ip(mapped)
    if str(ip) in _OWN_IPS:
        return True
    if ip.is_loopback or ip.is_unspecified or ip.is_link_local or ip.is_multicast:
        return True
    return any(ip in network for network in _BLOCK_NETWORKS)


def _blocked_host(host: str) -> bool:
    name = (host or "").strip().lower().rstrip(".")
    if not name or name in _BLOCK_HOSTS:
        return True
    if name.endswith(".internal") or name.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return False
    return _blocked_ip(ip)


def _guard(sock, address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) and address else address
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if isinstance(host, str) and _blocked_host(host):
        raise OSError("в песочнице нельзя ходить на внутренние адреса")
    return _orig_connect(sock, address, *args, **kwargs)


_orig_connect = socket.socket.connect
socket.socket.connect = _guard  # type: ignore[method-assign]
if hasattr(socket.socket, "connect_ex"):
    _orig_ex = socket.socket.connect_ex

    def _guard_ex(sock, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) and address else address
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if isinstance(host, str) and _blocked_host(host):
            return 111
        return _orig_ex(sock, address, *args, **kwargs)

    socket.socket.connect_ex = _guard_ex  # type: ignore[method-assign]

_orig_getaddrinfo = socket.getaddrinfo


def _guard_getaddrinfo(host, port, *args, **kwargs):
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if isinstance(host, str) and _blocked_host(host):
        raise OSError("в песочнице нельзя ходить на внутренние адреса")
    results = _orig_getaddrinfo(host, port, *args, **kwargs)
    public = []
    for item in results:
        sockaddr = item[4] if len(item) > 4 else None
        addr = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else ""
        if isinstance(addr, str) and _blocked_host(addr):
            continue
        public.append(item)
    if not public:
        raise OSError("в песочнице нельзя ходить на внутренние адреса")
    return public


socket.getaddrinfo = _guard_getaddrinfo  # type: ignore[assignment]
