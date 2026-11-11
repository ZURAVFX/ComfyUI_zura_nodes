"""Loopback-only access checks for the local bridge adapter."""
import ipaddress
import secrets
from urllib.parse import urlsplit

from aiohttp import web


def _loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_local(request):
    peer = request.transport.get_extra_info("peername") if request.transport else None
    if not peer or not _loopback(peer[0]):
        raise web.HTTPForbidden(text="Local connections only")
    try:
        host = urlsplit("http://" + request.headers.get("Host", ""))
        hostname, port = host.hostname, host.port
        if not hostname or not _loopback(hostname) or host.username or host.password or host.path or host.query or host.fragment:
            raise ValueError("invalid host")
        origin = request.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if (parsed.scheme != request.scheme or parsed.hostname != hostname
                    or parsed.port != port or parsed.username or parsed.password
                    or parsed.path or parsed.query or parsed.fragment):
                raise ValueError("invalid origin")
    except ValueError:
        raise web.HTTPForbidden(text="Invalid local host or origin")


def require_token(request, token):
    require_local(request)
    if not token:
        raise web.HTTPForbidden(text="ComfyLink pairing is not configured")
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer ") or not secrets.compare_digest(value[7:].encode("utf-8"), token.encode("utf-8")):
        raise web.HTTPForbidden(text="ComfyLink authentication failed")
