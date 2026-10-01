from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Verification:
    """An external verifier's verdict on a completed run's answer.

    ``ok`` is True when the answer is verified, False when it is refuted, and None
    when the verifier could not decide (but still wants the attempt on the record).
    ``detail`` is a human-readable reason; ``source`` names the verifier.
    """

    ok: bool | None
    detail: str = ""
    source: str = ""


class VerifierProvider(Protocol):
    """Checks a completed run's answer, after Forum has produced it.

    This is the seam to an external verifier: a peer like the index flagship, a
    proof-checker, or a test runner can implement it, and Forum will witness the
    verdict it returns. It is the peer of the ContextProvider seam (context in,
    verification out). Return None to abstain, so nothing is witnessed. Forum never
    imports the provider, only this shape.

    verify() runs synchronously inside the run, so keep it fast or offload heavy work
    yourself: a slow verifier blocks the calling run, and under the daemon the event
    loop. A verifier that raises is witnessed as could-not-decide, never fatal.
    """

    def verify(self, request: str, answer: str) -> Verification | None: ...


class NullVerifier:
    """The zero-dependency default: no external verification. Forum stands alone."""

    def verify(self, request: str, answer: str) -> Verification | None:
        return None
