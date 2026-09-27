"""Transport checks for the HTTP daemon: Origin, Host and content type.

They stop a web page in the user's browser from driving a local daemon
(cross-origin requests and DNS rebinding), while a CLI or curl client passes
untouched. They live at the transport, not in HttpSurface, so the stdio MCP
surface that shares HttpSurface never sees them.
"""
from __future__ import annotations

from forum.http_response import Response, error

__all__ = ["check_http_headers"]

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})
_PUBLIC_PATHS = frozenset({"/health"})


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _split_authority(value: str) -> tuple[str, str]:
    """(host, port text) of a Host or Origin authority. Host lowercased, IPv6 kept in brackets."""
    value = value.strip().lower()
    if value.startswith("["):  # [::1]:8080
        end = value.find("]")
        if end == -1:
            return value, ""
        return value[: end + 1], value[end + 2:] if value[end + 1: end + 2] == ":" else ""
    host, sep, port = value.rpartition(":")
    return (host, port) if sep else (value, "")


def _hostname(value: str) -> str:
    """The host part of a Host or Origin authority, without the port, lowercased."""
    return _split_authority(value)[0]


def _same_origin(origin: str, port: int | None) -> bool:
    """True for the daemon's own origin: http(s), a loopback host, and the daemon's port."""
    scheme, sep, authority = origin.strip().lower().partition("://")
    if not sep or scheme not in _DEFAULT_PORTS:
        return False  # includes the opaque "null" origin
    host, port_text = _split_authority(authority)
    if host not in _LOOPBACK_HOSTS:
        return False
    if port is None:
        return True
    if not port_text:
        return port == _DEFAULT_PORTS[scheme]
    return port_text.isdigit() and int(port_text) == port


def check_http_headers(
    method: str,
    path: str,
    headers: dict[str, str],
    *,
    port: int | None = None,
    check_host: bool = True,
) -> Response | None:
    """Transport-level defenses for the local daemon, or None to allow.

    A browser attaches an Origin on a cross-site request and a Host it cannot
    forge from a page, so these checks stop a web page in the user's browser from
    driving the loopback daemon (DNS-rebinding and cross-origin CSRF), which a CLI
    or curl client passes untouched. Applied to every path except /health.

    - Origin, when present, must be the daemon's own origin: a loopback host and,
      when ``port`` is given, the daemon's port. A page another local program
      serves (a dev server on localhost:5173) is a different origin, so 403.
    - Host, when present and ``check_host`` is on, must be a loopback name,
      compared without case, else 403. A daemon that requires a bearer token
      passes ``check_host=False``: a rebinding page never holds the token, and
      a client reaching a network-bound daemon uses the machine's own name.
    - A POST/PUT/PATCH with a body must be application/json, else 415.

    These are transport concerns and live here, not in HttpSurface, so the stdio
    MCP surface (which shares HttpSurface) is untouched.
    """
    if path in _PUBLIC_PATHS:
        return None
    origin = headers.get("origin")
    if origin and not _same_origin(origin, port):
        return error(403, "cross-origin request refused")
    host = headers.get("host")
    if check_host and host and _hostname(host) not in _LOOPBACK_HOSTS:
        return error(403, "unrecognized Host header refused")
    if method in ("POST", "PUT", "PATCH") and int(headers.get("content-length") or "0") > 0:
        ctype = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            return error(415, "Content-Type must be application/json")
    return None
