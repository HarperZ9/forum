"""JWT bearer authentication and role-based authorization for forum's surfaces.

The core is zero-dependency: HS256 (HMAC-SHA256, stdlib ``hmac``) token
verification, a role to scope policy, a per-endpoint required-scope map, and a
witness helper that records every authorization decision as a ledger entry, so
the audit trail is tamper-evident on the same Merkle chain as the runs it guards.

Asymmetric verification (RS256 / JWKS) is deliberately out of the core, which
would need a crypto dependency. It is an edge adapter: implement ``TokenVerifier``
and pass it wherever an ``HmacVerifier`` is accepted.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Iterable, Protocol


class InvalidToken(Exception):
    """A bearer token is missing, malformed, unsigned-for-us, or expired."""


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class Claims:
    subject: str
    roles: frozenset[str]
    raw: dict[str, Any]


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Claims: ...


class HmacVerifier:
    """HS256 JWT verification with a shared secret (stdlib only).

    Verifies the signature in constant time, then enforces ``exp`` and ``nbf``
    against an injectable clock (``leeway`` seconds of tolerance), and requires a
    non-empty string ``sub``. ``roles`` defaults to empty. Only ``alg=HS256`` is
    accepted; anything else (including ``none``) is rejected, closing the alg
    confusion and algorithm-stripping attacks.
    """

    def __init__(
        self,
        secret: str | bytes,
        *,
        leeway: float = 0.0,
        clock=time.time,
    ) -> None:
        self._secret = secret.encode("utf-8") if isinstance(secret, str) else secret
        if not self._secret:
            raise ValueError("HMAC secret must be non-empty")
        self._leeway = float(leeway)
        self._clock = clock

    def verify(self, token: str) -> Claims:
        parts = token.split(".")
        if len(parts) != 3:
            raise InvalidToken("malformed token (need header.payload.signature)")
        header_b64, payload_b64, sig_b64 = parts
        try:
            header = json.loads(_b64url_decode(header_b64))
        except Exception as exc:
            raise InvalidToken("undecodable header") from exc
        if not isinstance(header, dict) or header.get("alg") != "HS256":
            raise InvalidToken(
                f"unsupported alg {header.get('alg') if isinstance(header, dict) else None!r}"
                " (this verifier only accepts HS256)"
            )
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        try:
            provided = _b64url_decode(sig_b64)
        except Exception as exc:
            raise InvalidToken("undecodable signature") from exc
        if not hmac.compare_digest(expected, provided):
            raise InvalidToken("bad signature")

        try:
            payload = json.loads(_b64url_decode(payload_b64))
        except Exception as exc:
            raise InvalidToken("undecodable payload") from exc
        if not isinstance(payload, dict):
            raise InvalidToken("payload is not an object")

        now = float(self._clock())
        exp = payload.get("exp")
        if exp is not None and now > float(exp) + self._leeway:
            raise InvalidToken("token expired")
        nbf = payload.get("nbf")
        if nbf is not None and now + self._leeway < float(nbf):
            raise InvalidToken("token not yet valid")

        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise InvalidToken("missing or empty subject (sub)")
        roles_raw = payload.get("roles", [])
        if not isinstance(roles_raw, list):
            raise InvalidToken("roles claim must be a list")
        return Claims(
            subject=subject,
            roles=frozenset(str(r) for r in roles_raw),
            raw=payload,
        )


def issue_hs256(
    *,
    subject: str,
    roles: Iterable[str],
    secret: str | bytes,
    ttl_seconds: float | None = 3600.0,
    clock=time.time,
) -> str:
    """Mint an HS256 token (for issuing to callers and for tests)."""
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    now = float(clock())
    payload: dict[str, Any] = {"sub": subject, "roles": list(roles), "iat": now}
    if ttl_seconds is not None:
        payload["exp"] = now + ttl_seconds
    header_b64 = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload_b64 = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(key, signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"


def bearer_token(authorization_header: str | None) -> str | None:
    """Extract the token from an ``Authorization: Bearer <token>`` header."""
    if not authorization_header:
        return None
    scheme, _, value = authorization_header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


@dataclass(frozen=True, slots=True)
class RolePolicy:
    """Maps each role to the scopes it grants. A caller's scopes are the union
    over its roles; an unknown role grants nothing (fail-closed)."""

    grants: dict[str, frozenset[str]]

    def scopes_for(self, roles: Iterable[str]) -> frozenset[str]:
        out: set[str] = set()
        for role in roles:
            out |= self.grants.get(role, frozenset())
        return frozenset(out)


@dataclass(frozen=True, slots=True)
class AuthzDecision:
    granted: bool
    subject: str
    required: str
    scopes: frozenset[str]
    reason: str


def authorize(claims: Claims, required_scope: str, policy: RolePolicy) -> AuthzDecision:
    scopes = policy.scopes_for(claims.roles)
    granted = required_scope in scopes
    return AuthzDecision(
        granted=granted,
        subject=claims.subject,
        required=required_scope,
        scopes=scopes,
        reason="granted" if granted else f"missing scope {required_scope!r}",
    )


# API scopes for the HTTP/MCP surfaces. Read is separated from the mutating verbs,
# and approvals (gate decisions) are their own scope so an approver role can be
# granted narrowly.
SCOPE_READ = "forum:read"
SCOPE_ROUTE = "forum:route"
SCOPE_PLAN = "forum:plan"
SCOPE_SUBMIT = "forum:submit"
SCOPE_GATE = "forum:gate"

# A sensible default role vocabulary. Callers can supply their own RolePolicy.
DEFAULT_ROLE_POLICY = RolePolicy(
    grants={
        "viewer": frozenset({SCOPE_READ}),
        "operator": frozenset(
            {SCOPE_READ, SCOPE_ROUTE, SCOPE_PLAN, SCOPE_SUBMIT, SCOPE_GATE}
        ),
        "approver": frozenset({SCOPE_READ, SCOPE_GATE}),
        "service": frozenset({SCOPE_READ, SCOPE_ROUTE, SCOPE_PLAN, SCOPE_SUBMIT}),
    }
)

# method+path -> required scope. A path absent here is closed by default at the
# surface (deny), except explicitly public paths the surface allow-lists (/health).
_ENDPOINT_SCOPES: dict[tuple[str, str], str] = {
    ("GET", "/status"): SCOPE_READ,
    ("GET", "/verify"): SCOPE_READ,
    ("GET", "/checkpoint"): SCOPE_READ,
    ("GET", "/capsule"): SCOPE_READ,
    ("GET", "/room"): SCOPE_READ,
    ("GET", "/gates"): SCOPE_READ,
    ("GET", "/runtime"): SCOPE_READ,
    ("POST", "/route"): SCOPE_ROUTE,
    ("POST", "/plan"): SCOPE_PLAN,
    ("POST", "/submit"): SCOPE_SUBMIT,
    ("POST", "/context/preflight"): SCOPE_READ,
    ("POST", "/humanize"): SCOPE_READ,
    ("POST", "/prose/contract"): SCOPE_READ,
}

PUBLIC_ENDPOINTS: frozenset[tuple[str, str]] = frozenset({("GET", "/health")})


def required_scope(method: str, path: str) -> str | None:
    """The scope a method+path needs, or None if the endpoint is public.

    Unknown paths fail closed to the most restrictive mutating scope, so a new
    endpoint is never accidentally world-open before it is mapped here.
    """
    if (method, path) in PUBLIC_ENDPOINTS:
        return None
    if method == "GET" and (path.startswith("/ledger/") or path.startswith("/replay/")):
        return SCOPE_READ
    if method == "POST" and path.startswith("/gate/"):
        return SCOPE_GATE
    return _ENDPOINT_SCOPES.get((method, path), SCOPE_SUBMIT)


def witness_authz(ledger, decision: AuthzDecision, *, resource: str, actor: str = "auth"):
    """Record an authorization decision as a witnessed, tamper-evident ledger entry."""
    return ledger.append(
        actor=actor,
        kind="authz_grant" if decision.granted else "authz_deny",
        payload={
            "subject": decision.subject,
            "required": decision.required,
            "granted": decision.granted,
            "scopes": sorted(decision.scopes),
            "resource": resource,
            "reason": decision.reason,
        },
    )
