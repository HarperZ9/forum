import base64
import json

import pytest

from forum.auth import (
    DEFAULT_ROLE_POLICY,
    HmacVerifier,
    InvalidToken,
    RolePolicy,
    authorize,
    bearer_token,
    issue_hs256,
    required_scope,
    witness_authz,
)
from forum.ledger import InMemoryStorage, Ledger

SECRET = "s3cr3t-signing-key"


def _clock(t=1000.0):
    return lambda: t


def _verifier(t=1000.0, leeway=0.0):
    return HmacVerifier(SECRET, leeway=leeway, clock=_clock(t))


def test_issue_and_verify_round_trip():
    tok = issue_hs256(subject="alice", roles=["operator"], secret=SECRET, clock=_clock(1000))
    claims = _verifier(1001).verify(tok)
    assert claims.subject == "alice"
    assert claims.roles == frozenset({"operator"})


def test_bad_signature_rejected():
    tok = issue_hs256(subject="a", roles=[], secret=SECRET, clock=_clock(1000))
    forged = HmacVerifier("different-key", clock=_clock(1001))
    with pytest.raises(InvalidToken, match="bad signature"):
        forged.verify(tok)


def test_expired_token_rejected():
    tok = issue_hs256(subject="a", roles=[], secret=SECRET, ttl_seconds=100, clock=_clock(1000))
    with pytest.raises(InvalidToken, match="expired"):
        _verifier(1101).verify(tok)  # 1000+100 < 1101
    # within leeway it is still accepted
    _verifier(1105, leeway=10).verify(tok)


def test_not_yet_valid_rejected():
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "a", "nbf": 2000}).encode()).rstrip(b"=").decode()
    import hashlib
    import hmac
    sig = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    tok = f"{header}.{payload}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"
    with pytest.raises(InvalidToken, match="not yet valid"):
        _verifier(1500).verify(tok)


def test_alg_confusion_and_none_rejected():
    # a token that claims alg=none with an empty signature must not verify
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "attacker", "roles": ["operator"]}).encode()).rstrip(b"=").decode()
    tok = f"{header}.{payload}."
    with pytest.raises(InvalidToken):
        _verifier().verify(tok)


def test_malformed_and_missing_subject():
    with pytest.raises(InvalidToken, match="malformed"):
        _verifier().verify("not-a-jwt")
    tok = issue_hs256(subject="", roles=[], secret=SECRET, clock=_clock(1000)) if False else None
    # build a signed token with no sub
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"roles": []}).encode()).rstrip(b"=").decode()
    import hashlib
    import hmac
    sig = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    tok = f"{header}.{payload}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"
    with pytest.raises(InvalidToken, match="subject"):
        _verifier().verify(tok)


def test_empty_secret_rejected():
    with pytest.raises(ValueError):
        HmacVerifier("")


def test_bearer_token_extraction():
    assert bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"
    assert bearer_token("bearer abc") == "abc"  # scheme case-insensitive
    assert bearer_token("Basic abc") is None
    assert bearer_token("Bearer ") is None
    assert bearer_token(None) is None


def test_role_policy_union_and_fail_closed():
    p = RolePolicy(grants={"r": frozenset({"a"}), "s": frozenset({"a", "b"})})
    assert p.scopes_for(["r", "s"]) == frozenset({"a", "b"})
    assert p.scopes_for(["unknown"]) == frozenset()  # fail-closed


def test_authorize_grant_and_deny():
    claims = _verifier(1001).verify(
        issue_hs256(subject="op", roles=["operator"], secret=SECRET, clock=_clock(1000))
    )
    grant = authorize(claims, "forum:submit", DEFAULT_ROLE_POLICY)
    assert grant.granted is True
    viewer = _verifier(1001).verify(
        issue_hs256(subject="v", roles=["viewer"], secret=SECRET, clock=_clock(1000))
    )
    deny = authorize(viewer, "forum:submit", DEFAULT_ROLE_POLICY)
    assert deny.granted is False
    assert "missing scope" in deny.reason


def test_required_scope_map():
    assert required_scope("GET", "/health") is None  # public
    assert required_scope("GET", "/status") == "forum:read"
    assert required_scope("POST", "/submit") == "forum:submit"
    assert required_scope("POST", "/unknown") == "forum:submit"  # closed by default


def test_witness_authz_is_tamper_evident():
    led = Ledger(InMemoryStorage(), clock=iter(float(t) for t in range(1, 20)).__next__)
    claims = _verifier(1001).verify(
        issue_hs256(subject="op", roles=["operator"], secret=SECRET, clock=_clock(1000))
    )
    grant = authorize(claims, "forum:submit", DEFAULT_ROLE_POLICY)
    viewer = _verifier(1001).verify(
        issue_hs256(subject="v", roles=["viewer"], secret=SECRET, clock=_clock(1000))
    )
    deny = authorize(viewer, "forum:submit", DEFAULT_ROLE_POLICY)
    e0 = witness_authz(led, grant, resource="POST /submit")
    e1 = witness_authz(led, deny, resource="POST /submit")
    assert e0.kind == "authz_grant"
    assert e1.kind == "authz_deny"
    assert led.verify(deep=True) is True
    got = led.get_payload(e1.payload_hash)
    assert got["subject"] == "v" and got["granted"] is False
