"""Fetches a public web page for the research engine.

The URL comes from search results, i.e. from the internet, so the request must
not be usable to reach internal services (server-side request forgery):

* only ``http``/``https`` on the default ports, no credentials in the URL;
* the host must resolve only to public addresses (private, loopback,
  link-local, cloud metadata and other reserved ranges are refused);
* the connection is made to the address that was checked, so a second DNS
  answer cannot redirect it (DNS rebinding);
* redirects are followed manually, at most ``MAX_REDIRECTS`` times, and every
  hop is validated again;
* the response is read in chunks up to ``MAX_BYTES`` and must be text.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

MAX_REDIRECTS = 3
MAX_BYTES = 2 * 1024 * 1024
_ALLOWED_PORTS = {None, 80, 443}
_TEXT_TYPES = ("text/", "application/xhtml", "application/xml")


class UnsafeUrlError(ValueError):
    pass


def _public_addresses(host: str, port: int) -> list[str]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = {entry[4][0] for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise UnsafeUrlError("The source host could not be resolved.") from exc
    else:
        addresses = {str(literal)}
    if not addresses:
        raise UnsafeUrlError("The source host did not resolve to an address.")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        mapped = getattr(ip, "ipv4_mapped", None)
        if not ip.is_global or (mapped is not None and not mapped.is_global):
            raise UnsafeUrlError("The source host resolves to a non-public network address.")
    return sorted(addresses)


def validate_url(url: str) -> bool:
    """Syntactic check only (no DNS): scheme, host, port and no credentials."""
    if not url:
        return False
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host or port not in _ALLOWED_PORTS:
        return False
    if parsed.username or parsed.password or host.startswith(".") or host.endswith(".local"):
        return False
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    try:
        if not ipaddress.ip_address(host).is_global:
            return False
    except ValueError:
        pass
    return True


def _resolve(url: str) -> tuple[str, str, int]:
    """Validate ``url`` and return (host, pinned address, port)."""
    if not validate_url(url):
        raise UnsafeUrlError("Unsafe or invalid source URL.")
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    host = parsed.hostname or ""
    return host, _public_addresses(host, port)[0], port


def fetch_page(url: str, *, timeout_seconds: float = 30.0, transport: httpx.BaseTransport | None = None) -> str:
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        host, address, port = _resolve(current)
        parsed = urlsplit(current)
        # Connect to the checked address; keep the host name for TLS (SNI and
        # certificate verification) and for the Host header.
        target_host = f"[{address}]" if ":" in address else address
        pinned = parsed._replace(netloc=f"{target_host}:{port}").geturl()
        with httpx.Client(follow_redirects=False, timeout=timeout_seconds, trust_env=False, transport=transport) as client:
            request = client.build_request(
                "GET",
                pinned,
                headers={"Host": host if port in {80, 443} else f"{host}:{port}", "Accept": "text/html,application/xhtml+xml"},
                extensions={"sni_hostname": host},
            )
            response = client.send(request, stream=True)
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise RuntimeError("Source redirect has no target.")
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    raise RuntimeError(f"Source fetch failed with status {response.status_code}.")
                content_type = response.headers.get("content-type", "")
                if not any(kind in content_type for kind in _TEXT_TYPES):
                    raise RuntimeError("Source content type is not readable text.")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise RuntimeError("Source page is too large.")
                    chunks.append(chunk)
                return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
            finally:
                response.close()
    raise RuntimeError("Source redirected too many times.")
