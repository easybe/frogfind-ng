import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

_BLOCKED_V4 = [
    ipaddress.ip_network(n) for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
    )
]

_BLOCKED_V6 = [
    ipaddress.ip_network(n) for n in (
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "::ffff:0:0/96",
        "64:ff9b::/96",
        "100::/64",
    )
]

_BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


def validate_url(url: str) -> Optional[str]:
    """Returns an error string if the URL is unsafe, None if it is safe."""
    if not url or len(url) > 2048:
        return "Invalid URL"

    try:
        parsed = urlparse(url)
    except Exception:
        return "Malformed URL"

    if parsed.scheme not in ("http", "https"):
        return f"Scheme '{parsed.scheme}' not allowed"

    hostname = parsed.hostname
    if not hostname:
        return "Missing hostname"

    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return "Hostname not allowed"

    # Reject bare IPs that look private without DNS lookup
    try:
        direct_ip = ipaddress.ip_address(hostname)
        return _check_ip(direct_ip)
    except ValueError:
        pass  # hostname is a domain name — proceed to DNS

    try:
        resolved = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return "DNS resolution failed"

    for family, _, _, _, sockaddr in resolved:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        err = _check_ip(ip)
        if err:
            return err

    return None


def _check_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> Optional[str]:
    if isinstance(ip, ipaddress.IPv4Address):
        for net in _BLOCKED_V4:
            if ip in net:
                return "Private/reserved IP blocked"
    else:
        for net in _BLOCKED_V6:
            if ip in net:
                return "Private/reserved IPv6 blocked"
    return None


def is_safe_url(url: str) -> bool:
    return validate_url(url) is None
