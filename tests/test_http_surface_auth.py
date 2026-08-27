import asyncio

from forum.auth import HmacVerifier, issue_hs256
from forum.engine import Orchestrator
from forum.executor import EchoExecutor
from forum.http_surface import HttpSurface
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.roster import load_default

ALL = frozenset({"engineering", "graphics", "support", "research"})
SECRET = "test-signing-secret"


def _clock(t=1000.0):
    return lambda: t


def _orch():
    ticks = iter(float(t) for t in range(1, 100_000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    return Orchestrator(
        load_default(), ledger, EchoExecutor(),
        Policy(allowed_categories=ALL, max_parallel=4),
    )


def _authed_surface():
    orch = _orch()
    surface = HttpSurface(orch, verifier=HmacVerifier(SECRET, clock=_clock(1000)))
    return surface, orch


def _do(surface, method, path, body=b"", authorization=None):
    return asyncio.run(surface.dispatch(method, path, body, authorization))


def _bearer(roles):
    return "Bearer " + issue_hs256(subject="u", roles=roles, secret=SECRET, clock=_clock(1000))


def test_no_verifier_leaves_surface_open():
    surface = HttpSurface(_orch())  # no verifier configured
    assert _do(surface, "GET", "/status").status == 200


def test_public_health_needs_no_token():
    surface, _ = _authed_surface()
    assert _do(surface, "GET", "/health").status == 200


def test_protected_endpoint_requires_token():
    surface, _ = _authed_surface()
    assert _do(surface, "GET", "/status").status == 401


def test_invalid_token_rejected_401():
    surface, _ = _authed_surface()
    assert _do(surface, "GET", "/status", authorization="Bearer not.a.jwt").status == 401


def test_viewer_reads_but_cannot_submit_and_deny_is_witnessed():
    surface, orch = _authed_surface()
    assert _do(surface, "GET", "/status", authorization=_bearer(["viewer"])).status == 200
    denied = _do(surface, "POST", "/submit", b"{}", authorization=_bearer(["viewer"]))
    assert denied.status == 403
    kinds = [e.kind for e in orch.ledger.replay()]
    assert "authz_deny" in kinds  # the denial is a tamper-evident audit entry
    assert orch.ledger.verify(deep=True) is True


def test_operator_submit_authorized_and_grant_witnessed():
    surface, orch = _authed_surface()
    resp = _do(surface, "POST", "/submit", b'{"text": "x"}', authorization=_bearer(["operator"]))
    assert resp.status not in (401, 403)  # auth passed (route may 4xx/5xx on its own)
    kinds = [e.kind for e in orch.ledger.replay()]
    assert "authz_grant" in kinds  # mutating grant is witnessed
    assert orch.ledger.verify(deep=True) is True


def test_unauthenticated_requests_do_not_write_the_ledger():
    # a flood of tokenless requests must not grow the audit log (DoS guard)
    surface, orch = _authed_surface()
    before = orch.ledger.count()
    for _ in range(5):
        assert _do(surface, "POST", "/submit", b"{}").status == 401
    assert orch.ledger.count() == before
