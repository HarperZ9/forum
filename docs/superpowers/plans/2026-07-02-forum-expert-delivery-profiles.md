# Forum Expert Delivery Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic expert delivery profiles so Forum can check, witness, summarize, and expose domain-aware prose standards for final answers and humanized text.

**Architecture:** Add a pure `forum.delivery_profile` module that scores text against named profile contracts without rewriting facts. Wire that pure check into `humanize_text`, HTTP/MCP/CLI humanize surfaces, `Orchestrator.submit`, receipts, summaries, and docs. Profile checks are witnessed signals, not fatal run gates.

**Tech Stack:** Python 3.11+, standard library only, existing Forum ledger/storage/orchestrator stack, pytest, argparse, stdlib JSON HTTP/MCP surfaces.

## Global Constraints

- Forum core must remain zero-dependency.
- Profile checks must be deterministic and replayable.
- Existing behavior must remain compatible when no delivery profile is provided.
- Profile checks must not silently rewrite facts.
- A delivery profile must be a measurable standard, not a request to imitate a named writer.
- A profile failure must be witnessed and summarized, not treated as a fatal run failure.
- CLI, HTTP, MCP, Python API, README, USAGE, ARCHITECTURE, and CHANGELOG must stay aligned.
- Tests must cover profile rules, run integration, reports, receipts where relevant, and public surface parsing.

---

## File Structure

- Create `src/forum/delivery_profile.py`: pure profile dataclasses, profile registry, deterministic assessment, and JSON payload conversion.
- Create `tests/test_delivery_profile.py`: pure profile tests.
- Modify `src/forum/humanize.py`: accept optional `profile`, attach `profile_check`.
- Modify `src/forum/cli.py`: parse `--profile` for `humanize` and `--delivery-profile` for `submit`.
- Modify `src/forum/http_surface.py`: parse `profile` for `/humanize` and `delivery_profile` for `/submit`.
- Modify `src/forum/mcp_surface.py`: pass profile fields through HTTP and advertise schemas.
- Modify `src/forum/engine.py`: add `delivery_profile` to `submit`, validate early, witness profile checks after final delivery.
- Modify `src/forum/report.py`: summarize `delivery_profile_check` entries.
- Modify `src/forum/receipts.py`: add compact submit receipt `delivery_profile` observed block.
- Modify `tests/test_humanize.py`, `tests/test_delivery.py`, `tests/test_report.py`, `tests/test_cli.py`, `tests/test_http_surface.py`, and `tests/test_mcp_surface.py`.
- Modify `README.md`, `USAGE.md`, `ARCHITECTURE.md`, `CHANGELOG.md`.
- Create `examples/run_delivery_profile.py`.

---

### Task 1: Pure Delivery Profile Core

**Files:**
- Create: `src/forum/delivery_profile.py`
- Create: `tests/test_delivery_profile.py`

**Interfaces:**
- Consumes: no Forum runtime modules.
- Produces:
  - `DeliveryProfile`
  - `ProfileFinding`
  - `ProfileAssessment`
  - `get_profile(name: str | None) -> DeliveryProfile`
  - `list_profiles() -> tuple[str, ...]`
  - `assess_profile(text: str, profile: str | DeliveryProfile | None = None) -> ProfileAssessment`
  - `profile_payload(assessment: ProfileAssessment) -> dict`

- [ ] **Step 1: Write failing pure profile tests**

Create `tests/test_delivery_profile.py`:

```python
import pytest

from forum.delivery_profile import (
    DELIVERY_PROFILE_SCHEMA,
    assess_profile,
    get_profile,
    list_profiles,
    profile_payload,
)


def _codes(assessment):
    return {finding.code for finding in assessment.findings}


def test_list_profiles_and_default_profile():
    assert list_profiles() == ("operator", "engineer", "researcher", "executive")
    assert get_profile(None).name == "operator"
    assert get_profile("engineer").name == "engineer"


def test_unknown_profile_names_valid_options():
    with pytest.raises(ValueError) as exc:
        get_profile("poet")
    msg = str(exc.value)
    assert "unknown delivery profile" in msg
    assert "operator" in msg and "engineer" in msg and "researcher" in msg and "executive" in msg


def test_empty_text_is_flagged():
    assessment = assess_profile("", "operator")
    assert assessment.flagged is True
    assert "empty_text" in _codes(assessment)


def test_model_preamble_and_ai_disclaimer_are_flagged():
    assessment = assess_profile("As an AI language model, I cannot inspect the repo.", "operator")
    codes = _codes(assessment)
    assert "model_preamble" in codes
    assert "model_disclaimer" in codes


def test_operator_profile_accepts_direct_concise_action():
    assessment = assess_profile("Ship the API. Run the focused tests. Report the checkpoint.", "operator")
    assert assessment.flagged is False
    assert assessment.findings == ()


def test_operator_profile_flags_indirect_opening_and_missing_action():
    assessment = assess_profile("It seems the system may be ready. The status is acceptable.", "operator")
    codes = _codes(assessment)
    assert "banned_start" in codes
    assert "missing_action_verb" in codes


def test_engineer_profile_flags_vague_unsupported_optimization():
    assessment = assess_profile("Optimize the system and make it better.", "engineer")
    codes = _codes(assessment)
    assert "missing_required_term" in codes
    assert "vague_optimization" in codes


def test_engineer_profile_accepts_concrete_verified_language():
    text = "The module passes the focused test from the ledger. Keep the API unchanged."
    assessment = assess_profile(text, "engineer")
    assert assessment.flagged is False


def test_researcher_profile_requires_evidence_language():
    assessment = assess_profile("This proves the model is better than the baseline.", "researcher")
    codes = _codes(assessment)
    assert "missing_evidence_language" in codes
    assert "overconfident_without_evidence" in codes


def test_researcher_profile_accepts_sourced_language():
    text = "The source reports lower context pressure. Unknown cases remain outside this sample."
    assessment = assess_profile(text, "researcher")
    assert assessment.flagged is False


def test_executive_profile_flags_long_or_indirect_answers():
    text = "Maybe the project is ready. " + " ".join(["detail"] * 130)
    assessment = assess_profile(text, "executive")
    codes = _codes(assessment)
    assert "banned_start" in codes
    assert "too_many_words" in codes


def test_profile_payload_is_json_ready():
    assessment = assess_profile("Ship the API. Run the tests.", "operator")
    payload = profile_payload(assessment)
    assert payload["schema"] == DELIVERY_PROFILE_SCHEMA
    assert payload["profile"] == "operator"
    assert payload["flagged"] is False
    assert payload["findings"] == []
```

- [ ] **Step 2: Run pure profile tests to verify they fail**

Run:

```bash
python -m pytest tests/test_delivery_profile.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'forum.delivery_profile'`.

- [ ] **Step 3: Add the pure profile module**

Create `src/forum/delivery_profile.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass

DELIVERY_PROFILE_SCHEMA = "forum.delivery-profile/v1"

_WORD = re.compile(r"[^\W_]+")
_SENTENCE = re.compile(r"[.!?]+")

_FILLER = frozenset({
    "just", "really", "very", "quite", "basically", "actually", "literally",
    "simply", "essentially", "definitely", "certainly", "probably", "perhaps",
    "maybe", "somewhat", "rather", "fairly", "arguably", "clearly", "obviously",
    "honestly", "truly", "indeed", "generally",
})

_ACTION_VERBS = frozenset({
    "ship", "run", "fix", "build", "verify", "commit", "report", "review",
    "deploy", "write", "read", "test", "measure", "compare", "record",
})

_EVIDENCE_TERMS = frozenset({
    "source", "citation", "observed", "measured", "reported", "unknown",
    "verified", "not verified", "from the test output", "from the ledger",
})

_TECHNICAL_TERMS = frozenset({
    "file", "test", "api", "module", "function", "command", "error", "schema",
    "ledger", "route", "class", "method", "commit", "http", "mcp", "cli",
})

_BANNED_STARTS = (
    "it seems",
    "maybe",
    "perhaps",
    "i think",
    "as an ai",
    "as a language model",
)

_MODEL_PREAMBLES = (
    "as an ai language model",
    "as a language model",
    "as an ai",
)

_MODEL_DISCLAIMERS = (
    "i cannot",
    "i can't",
    "i do not have access",
    "i don't have access",
)

_OVERCONFIDENT = frozenset({"proves", "certainly", "obviously", "definitely"})


@dataclass(frozen=True, slots=True)
class DeliveryProfile:
    name: str
    max_mean_sentence_words: float
    max_filler_ratio: float
    max_words: int | None = None
    banned_starts: tuple[str, ...] = _BANNED_STARTS
    banned_phrases: tuple[str, ...] = ()
    required_terms: tuple[str, ...] = ()
    requires_action_verb: bool = False
    requires_evidence_language: bool = False
    direct_opening: bool = False


@dataclass(frozen=True, slots=True)
class ProfileFinding:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class ProfileAssessment:
    profile: str
    words: int
    sentences: int
    mean_sentence_words: float
    filler_ratio: float
    flagged: bool
    findings: tuple[ProfileFinding, ...]
    schema: str = DELIVERY_PROFILE_SCHEMA


_PROFILES = {
    "operator": DeliveryProfile(
        name="operator",
        max_mean_sentence_words=24.0,
        max_filler_ratio=0.04,
        requires_action_verb=True,
        direct_opening=True,
    ),
    "engineer": DeliveryProfile(
        name="engineer",
        max_mean_sentence_words=24.0,
        max_filler_ratio=0.04,
        required_terms=tuple(sorted(_TECHNICAL_TERMS)),
        requires_action_verb=True,
        requires_evidence_language=True,
        direct_opening=True,
    ),
    "researcher": DeliveryProfile(
        name="researcher",
        max_mean_sentence_words=24.0,
        max_filler_ratio=0.04,
        requires_evidence_language=True,
        direct_opening=True,
    ),
    "executive": DeliveryProfile(
        name="executive",
        max_mean_sentence_words=24.0,
        max_filler_ratio=0.04,
        max_words=120,
        requires_action_verb=True,
        direct_opening=True,
    ),
}


def list_profiles() -> tuple[str, ...]:
    return tuple(_PROFILES)


def get_profile(name: str | None) -> DeliveryProfile:
    key = "operator" if name is None else str(name).strip().lower()
    try:
        return _PROFILES[key]
    except KeyError as exc:
        valid = ", ".join(list_profiles())
        raise ValueError(f"unknown delivery profile {name!r}; valid profiles: {valid}") from exc


def assess_profile(text: str, profile: str | DeliveryProfile | None = None) -> ProfileAssessment:
    p = profile if isinstance(profile, DeliveryProfile) else get_profile(profile)
    raw = text or ""
    lowered = raw.strip().lower()
    words = _WORD.findall(lowered)
    word_count = len(words)
    sentence_count = len([s for s in _SENTENCE.split(raw) if s.strip()])
    mean = round(word_count / sentence_count, 2) if sentence_count else float(word_count)
    filler_ratio = round(sum(1 for word in words if word in _FILLER) / word_count, 4) if word_count else 0.0
    findings: list[ProfileFinding] = []

    if not lowered:
        findings.append(ProfileFinding("empty_text", "delivered text is empty"))
    if any(lowered.startswith(prefix) for prefix in _MODEL_PREAMBLES):
        findings.append(ProfileFinding("model_preamble", "text starts with a model preamble"))
    if any(phrase in lowered for phrase in _MODEL_DISCLAIMERS):
        findings.append(ProfileFinding("model_disclaimer", "text contains a first-person model disclaimer"))
    banned_start = next((start for start in p.banned_starts if lowered.startswith(start)), None)
    if banned_start:
        findings.append(ProfileFinding("banned_start", f"text starts with {banned_start!r}"))
    banned_phrase = next((phrase for phrase in p.banned_phrases if phrase in lowered), None)
    if banned_phrase:
        findings.append(ProfileFinding("banned_phrase", f"text contains banned phrase {banned_phrase!r}"))
    if word_count and mean > p.max_mean_sentence_words:
        findings.append(ProfileFinding("long_sentence", f"mean sentence words {mean} exceeds {p.max_mean_sentence_words}"))
    if word_count and filler_ratio > p.max_filler_ratio:
        findings.append(ProfileFinding("filler_ratio", f"filler ratio {filler_ratio} exceeds {p.max_filler_ratio}"))
    if p.max_words is not None and word_count > p.max_words:
        findings.append(ProfileFinding("too_many_words", f"word count {word_count} exceeds {p.max_words}"))
    if p.requires_action_verb and sentence_count > 1 and not any(word in _ACTION_VERBS for word in words):
        findings.append(ProfileFinding("missing_action_verb", "profile requires a concrete action verb"))
    if p.required_terms and not any(term in words for term in p.required_terms):
        findings.append(ProfileFinding("missing_required_term", f"{p.name} profile requires a concrete technical term"))
    has_evidence = _has_phrase(lowered, _EVIDENCE_TERMS)
    if p.requires_evidence_language and not has_evidence:
        findings.append(ProfileFinding("missing_evidence_language", f"{p.name} profile requires evidence language"))
    if "optimize" in words and not any(char.isdigit() for char in lowered):
        findings.append(ProfileFinding("vague_optimization", "optimization claim needs a measurable target"))
    if any(word in _OVERCONFIDENT for word in words) and not has_evidence:
        findings.append(ProfileFinding("overconfident_without_evidence", "overconfident wording needs evidence language"))

    return ProfileAssessment(
        profile=p.name,
        words=word_count,
        sentences=sentence_count,
        mean_sentence_words=mean,
        filler_ratio=filler_ratio,
        flagged=bool(findings),
        findings=tuple(findings),
    )


def profile_payload(assessment: ProfileAssessment) -> dict:
    return {
        "schema": assessment.schema,
        "profile": assessment.profile,
        "words": assessment.words,
        "sentences": assessment.sentences,
        "mean_sentence_words": assessment.mean_sentence_words,
        "filler_ratio": assessment.filler_ratio,
        "flagged": assessment.flagged,
        "findings": [
            {"code": finding.code, "detail": finding.detail}
            for finding in assessment.findings
        ],
    }


def _has_phrase(text: str, phrases: frozenset[str]) -> bool:
    tokens = set(_WORD.findall(text))
    return any((" " in phrase and phrase in text) or phrase in tokens for phrase in phrases)
```

- [ ] **Step 4: Run pure profile tests to verify they pass**

Run:

```bash
python -m pytest tests/test_delivery_profile.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the pure core**

```bash
git add src/forum/delivery_profile.py tests/test_delivery_profile.py
git commit -m "feat: add expert delivery profile core"
```

---

### Task 2: Humanize Profile Checks and Humanize Public Surfaces

**Files:**
- Modify: `src/forum/humanize.py`
- Modify: `src/forum/cli.py`
- Modify: `src/forum/http_surface.py`
- Modify: `src/forum/mcp_surface.py`
- Modify: `tests/test_humanize.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_http_surface.py`
- Modify: `tests/test_mcp_surface.py`

**Interfaces:**
- Consumes: `assess_profile(text, profile)` and `profile_payload(assessment)` from Task 1.
- Produces:
  - `humanize_text(text: str, audience: str = "operator", profile: str | None = None) -> dict`
  - CLI `forum humanize TEXT --profile engineer`
  - HTTP `/humanize` field `profile`
  - MCP `forum.prose.humanize` field `profile`

- [ ] **Step 1: Add failing humanize tests**

Append to `tests/test_humanize.py`:

```python
def test_humanize_text_includes_delivery_profile_check():
    payload = humanize_text(
        "Prior to launch, utilize the module test output.",
        profile="engineer",
    )
    assert payload["profile"] == "engineer"
    assert payload["profile_check"]["schema"] == "forum.delivery-profile/v1"
    assert payload["profile_check"]["profile"] == "engineer"
    assert payload["profile_check"]["flagged"] is False


def test_humanize_cli_accepts_profile(capsys):
    rc = main([
        "humanize",
        "Prior to launch, utilize the module test output.",
        "--profile",
        "engineer",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"] == "engineer"
    assert payload["profile_check"]["profile"] == "engineer"


def test_humanize_cli_reports_unknown_profile(capsys):
    rc = main(["humanize", "Use the report.", "--profile", "poet"])
    assert rc == 2
    assert "unknown delivery profile" in capsys.readouterr().err
```

- [ ] **Step 2: Add failing HTTP and MCP humanize tests**

Append to `tests/test_http_surface.py`:

```python
def test_humanize_accepts_delivery_profile():
    surface, _ = _surface()
    resp = _do(
        surface,
        "POST",
        "/humanize",
        b'{"text":"Prior to launch, utilize the module test output.","profile":"engineer"}',
    )
    assert resp.status == 200
    body = json.loads(resp.body)
    assert body["profile"] == "engineer"
    assert body["profile_check"]["profile"] == "engineer"


def test_humanize_rejects_unknown_delivery_profile():
    surface, _ = _surface()
    resp = _do(surface, "POST", "/humanize", b'{"text":"Use the report.","profile":"poet"}')
    assert resp.status == 400
    assert "unknown delivery profile" in json.loads(resp.body)["error"]
```

Append to `tests/test_mcp_surface.py`:

```python
def test_call_prefixed_humanize_accepts_delivery_profile():
    resp = _call(_mcp(), "forum.prose.humanize", {
        "text": "Prior to launch, utilize the module test output.",
        "profile": "engineer",
    })
    result = resp["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["profile"] == "engineer"
    assert payload["profile_check"]["profile"] == "engineer"
```

- [ ] **Step 3: Run humanize surface tests to verify they fail**

Run:

```bash
python -m pytest tests/test_humanize.py::test_humanize_text_includes_delivery_profile_check tests/test_humanize.py::test_humanize_cli_accepts_profile tests/test_humanize.py::test_humanize_cli_reports_unknown_profile tests/test_http_surface.py::test_humanize_accepts_delivery_profile tests/test_http_surface.py::test_humanize_rejects_unknown_delivery_profile tests/test_mcp_surface.py::test_call_prefixed_humanize_accepts_delivery_profile -q
```

Expected: FAIL because `profile` is not accepted or not returned yet.

- [ ] **Step 4: Update `humanize_text`**

In `src/forum/humanize.py`, add:

```python
from forum.delivery_profile import assess_profile, profile_payload
```

Change the signature:

```python
def humanize_text(text: str, audience: str = "operator", profile: str | None = None) -> dict:
```

Before the return, add:

```python
    assessment = assess_profile(output, profile)
```

Change the returned dict to include:

```python
        "profile": assessment.profile,
        "profile_check": profile_payload(assessment),
```

- [ ] **Step 5: Update CLI humanize parsing**

In `src/forum/cli.py`, change `_cmd_humanize`:

```python
def _cmd_humanize(args) -> int:
    from forum.humanize import humanize_text

    try:
        print(json.dumps(humanize_text(args.text, audience=args.audience, profile=args.profile)))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0
```

In `build_parser()`, add to the `humanize` parser:

```python
    humanize.add_argument("--profile", default=None, help="delivery profile to assess: operator, engineer, researcher, executive")
```

- [ ] **Step 6: Update HTTP humanize parsing**

In `src/forum/http_surface.py`, inside `_humanize`, replace the return call:

```python
        profile = data.get("profile")
        if profile is not None and (not isinstance(profile, str) or not profile):
            return error(400, "field 'profile' must be a non-empty string when provided")
        try:
            return json_response(humanize_text(text, audience=audience, profile=profile))
        except ValueError as exc:
            return error(400, str(exc))
```

- [ ] **Step 7: Update MCP humanize routing and schema**

In `src/forum/mcp_surface.py`, add:

```python
def _humanize_body(arguments: dict) -> bytes:
    body = {"text": arguments.get("text", ""), "audience": arguments.get("audience", "operator")}
    if "profile" in arguments:
        body["profile"] = arguments["profile"]
    return _body(body)
```

Change `_TOOL_ROUTES`:

```python
    "humanize": lambda a: ("POST", "/humanize", _humanize_body(a)),
```

In the `forum.prose.humanize` schema properties, add:

```python
                "profile": {"type": "string", "description": "delivery profile: operator, engineer, researcher, executive"},
```

- [ ] **Step 8: Run humanize and public surface tests**

Run:

```bash
python -m pytest tests/test_humanize.py tests/test_http_surface.py tests/test_mcp_surface.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/forum/humanize.py src/forum/cli.py src/forum/http_surface.py src/forum/mcp_surface.py tests/test_humanize.py tests/test_http_surface.py tests/test_mcp_surface.py tests/test_cli.py
git commit -m "feat: assess delivery profiles for humanized prose"
```

---

### Task 3: Witness Delivery Profiles During Submit

**Files:**
- Modify: `src/forum/engine.py`
- Modify: `tests/test_delivery.py`

**Interfaces:**
- Consumes: `get_profile`, `assess_profile`, `profile_payload`.
- Produces:
  - `Orchestrator.submit(request, *, budget=None, context_budget=None, delivery_profile=None) -> str`
  - Ledger entries with `actor="delivery-profile"` and `kind="delivery_profile_check"`.

- [ ] **Step 1: Add failing run integration tests**

Append to `tests/test_delivery.py`:

```python
def test_submit_witnesses_delivery_profile_check():
    led = _led()
    answer = asyncio.run(
        _orch(led, "The module passes the focused test from the ledger. Ship the API.").submit(
            REQUEST,
            delivery_profile="engineer",
        )
    )
    assert "Ship the API" in answer
    entries = led.query(kind="delivery_profile_check")
    assert len(entries) == 1
    payload = led.get_payload(entries[0].payload_hash)
    assert payload["schema"] == "forum.delivery-profile/v1"
    assert payload["profile"] == "engineer"
    assert payload["flagged"] is False
    parent = led.get(entries[0].causal_parent)
    assert led.get_payload(parent.payload_hash).get("answer") == answer
    assert led.verify(deep=True) is True


def test_delivery_profile_check_chains_to_accepted_revision():
    led = _led()
    answer = asyncio.run(
        _orch(led, VERBOSE, reviser=_Reviser(REVISED)).submit(
            REQUEST,
            delivery_profile="operator",
        )
    )
    assert answer == REVISED
    check = led.query(kind="delivery_profile_check")[0]
    parent = led.get(check.causal_parent)
    assert led.get_payload(parent.payload_hash).get("answer") == REVISED


def test_unknown_delivery_profile_fails_before_ledger_write():
    led = _led()
    try:
        asyncio.run(_orch(led, "answer").submit(REQUEST, delivery_profile="poet"))
    except ValueError as exc:
        assert "unknown delivery profile" in str(exc)
    else:
        raise AssertionError("expected ValueError")
    assert led.replay() == []
```

- [ ] **Step 2: Run run integration tests to verify they fail**

Run:

```bash
python -m pytest tests/test_delivery.py::test_submit_witnesses_delivery_profile_check tests/test_delivery.py::test_delivery_profile_check_chains_to_accepted_revision tests/test_delivery.py::test_unknown_delivery_profile_fails_before_ledger_write -q
```

Expected: FAIL with `TypeError: Orchestrator.submit() got an unexpected keyword argument 'delivery_profile'`.

- [ ] **Step 3: Update `Orchestrator.submit` signature and validation**

In `src/forum/engine.py`, add imports:

```python
from forum.delivery_profile import assess_profile, get_profile, profile_payload
```

Change submit signature:

```python
    async def submit(
        self,
        request: str,
        *,
        budget: RunBudget | None = None,
        context_budget: ContextBudget | None = None,
        delivery_profile: str | None = None,
    ) -> str:
```

After `start = time.monotonic()`, add:

```python
        selected_delivery_profile = get_profile(delivery_profile).name if delivery_profile is not None else None
```

This validates before the request ledger entry.

- [ ] **Step 4: Add `_witness_delivery_profile` helper**

Add to `Orchestrator` before `_witness_intent`:

```python
    def _witness_delivery_profile(
        self,
        answer: str,
        parent_seq: int,
        profile: str | None,
    ) -> None:
        if profile is None:
            return
        assessment = assess_profile(answer, profile)
        self.ledger.append(
            actor="delivery-profile",
            kind="delivery_profile_check",
            payload=profile_payload(assessment),
            causal_parent=parent_seq,
        )
```

- [ ] **Step 5: Call delivery profile check after delivery**

In `submit`, after:

```python
        answer, answer_seq = self._resolve_delivery(request, answer, answer_entry.seq)
```

add:

```python
        self._witness_delivery_profile(answer, answer_seq, selected_delivery_profile)
```

- [ ] **Step 6: Run delivery tests**

Run:

```bash
python -m pytest tests/test_delivery.py tests/test_delivery_profile.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/forum/engine.py tests/test_delivery.py
git commit -m "feat: witness delivery profile checks"
```

---

### Task 4: Report and Receipt Profile Metrics

**Files:**
- Modify: `src/forum/report.py`
- Modify: `src/forum/receipts.py`
- Modify: `tests/test_report.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `delivery_profile_check` payloads.
- Produces:
  - summary fields `delivery_profile_checks`, `delivery_profile_flagged`, `delivery_profile_operator`, `delivery_profile_engineer`, `delivery_profile_researcher`, `delivery_profile_executive`
  - submit receipt block `delivery_profile`

- [ ] **Step 1: Add failing report test**

Append to `tests/test_report.py`:

```python
def test_summary_reports_delivery_profile_metrics():
    led = _led()
    led.append(
        actor="delivery-profile",
        kind="delivery_profile_check",
        payload={
            "schema": "forum.delivery-profile/v1",
            "profile": "engineer",
            "words": 9,
            "sentences": 1,
            "mean_sentence_words": 9.0,
            "filler_ratio": 0.0,
            "flagged": False,
            "findings": [],
        },
    )
    led.append(
        actor="delivery-profile",
        kind="delivery_profile_check",
        payload={
            "schema": "forum.delivery-profile/v1",
            "profile": "executive",
            "words": 140,
            "sentences": 2,
            "mean_sentence_words": 70.0,
            "filler_ratio": 0.0,
            "flagged": True,
            "findings": [{"code": "too_many_words", "detail": "word count 140 exceeds 120"}],
        },
    )
    s = summarize(led)
    assert s["delivery_profile_checks"] == 2
    assert s["delivery_profile_flagged"] == 1
    assert s["delivery_profile_engineer"] == 1
    assert s["delivery_profile_executive"] == 1
    assert s["delivery_profile_operator"] == 0
    assert s["delivery_profile_researcher"] == 0
    assert "delivery_profile_flagged" in compare(s, s)
```

- [ ] **Step 2: Add failing CLI receipt test for submit profile block**

In `tests/test_cli.py`, update `test_submit_json_returns_answer_and_receipt` to include `--delivery-profile engineer` in the argument list:

```python
    rc = main([
        "submit", "design an api", "--ledger", str(tmp_path / "ledger"),
        "--cmd", f'{sys.executable} {model}', "--json",
        "--delivery-profile", "engineer",
    ])
```

Then add assertions:

```python
    assert body["receipt"]["delivery_profile"]["requested"] == "engineer"
    assert body["receipt"]["delivery_profile"]["checks"] == 1
```

- [ ] **Step 3: Run report and CLI tests to verify failures**

Run:

```bash
python -m pytest tests/test_report.py::test_summary_reports_delivery_profile_metrics tests/test_cli.py::test_submit_json_returns_answer_and_receipt -q
```

Expected: FAIL with missing summary keys and missing CLI submit flag.

- [ ] **Step 4: Add report summary metrics**

In `src/forum/report.py`, after revision metrics, add:

```python
    delivery_profile_entries = ledger.query(kind="delivery_profile_check")
    delivery_profile_payloads = [ledger.get_payload(e.payload_hash) for e in delivery_profile_entries]
    delivery_profile_flagged = sum(1 for p in delivery_profile_payloads if p.get("flagged"))
    delivery_profile_counts = Counter(str(p.get("profile", "")) for p in delivery_profile_payloads)
```

Add to the returned dict:

```python
        "delivery_profile_checks": len(delivery_profile_entries),
        "delivery_profile_flagged": delivery_profile_flagged,
        "delivery_profile_operator": delivery_profile_counts.get("operator", 0),
        "delivery_profile_engineer": delivery_profile_counts.get("engineer", 0),
        "delivery_profile_researcher": delivery_profile_counts.get("researcher", 0),
        "delivery_profile_executive": delivery_profile_counts.get("executive", 0),
```

Add to `_NUMERIC`:

```python
    "delivery_profile_checks", "delivery_profile_flagged",
    "delivery_profile_operator", "delivery_profile_engineer",
    "delivery_profile_researcher", "delivery_profile_executive",
```

- [ ] **Step 5: Add receipt helper**

In `src/forum/receipts.py`, add:

```python
def _delivery_profile_observed(entries: list[LedgerEntry], ledger: Ledger) -> dict[str, int]:
    payloads = []
    for entry in entries:
        if entry.kind != "delivery_profile_check":
            continue
        try:
            payloads.append(ledger.get_payload(entry.payload_hash))
        except KeyError:
            continue
    return {
        "checks": len(payloads),
        "flagged": sum(1 for payload in payloads if payload.get("flagged")),
    }
```

Change `submit_receipt` signature:

```python
    delivery_profile: str | None = None,
```

Add to the returned dict:

```python
        "delivery_profile": {
            "requested": delivery_profile,
            **_delivery_profile_observed(entries, ledger),
        },
```

- [ ] **Step 6: Run report tests**

Run:

```bash
python -m pytest tests/test_report.py -q
```

Expected: PASS for report tests. CLI test still fails until Task 5 adds the public submit flag.

- [ ] **Step 7: Commit report and receipt internals**

Commit together with Task 5 because CLI submit must pass the `delivery_profile` value to receipts.

---

### Task 5: Submit Profile Public Surfaces

**Files:**
- Modify: `src/forum/cli.py`
- Modify: `src/forum/http_surface.py`
- Modify: `src/forum/mcp_surface.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_http_surface.py`
- Modify: `tests/test_mcp_surface.py`

**Interfaces:**
- Consumes: `Orchestrator.submit(..., delivery_profile=...)` from Task 3 and receipt `delivery_profile` from Task 4.
- Produces:
  - CLI `forum submit TEXT --delivery-profile engineer`
  - HTTP `/submit` field `delivery_profile`
  - MCP `submit` and `forum.submit` field `delivery_profile`

- [ ] **Step 1: Add failing public submit tests**

Append to `tests/test_cli.py`:

```python
def test_delivery_profile_submit_flag_parses():
    args = build_parser().parse_args(["submit", "do x", "--cmd", "echo", "--delivery-profile", "engineer"])
    assert args.delivery_profile == "engineer"
```

Append to `tests/test_http_surface.py`:

```python
def test_submit_accepts_delivery_profile_field():
    surface, _ = _surface()
    resp = _do(
        surface,
        "POST",
        "/submit",
        b'{"request": "design an api", "delivery_profile": "engineer"}',
    )
    assert resp.status == 200
    body = json.loads(resp.body)
    assert body["receipt"]["delivery_profile"]["requested"] == "engineer"
    assert body["receipt"]["delivery_profile"]["checks"] == 1


def test_submit_rejects_unknown_delivery_profile():
    surface, _ = _surface()
    resp = _do(
        surface,
        "POST",
        "/submit",
        b'{"request": "design an api", "delivery_profile": "poet"}',
    )
    assert resp.status == 400
    assert "unknown delivery profile" in json.loads(resp.body)["error"]
```

Append to `tests/test_mcp_surface.py`:

```python
def test_prefixed_submit_accepts_delivery_profile_field():
    surface = _mcp()
    resp = _call(surface, "forum.submit", {
        "request": "design an api",
        "delivery_profile": "engineer",
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["receipt"]["delivery_profile"]["requested"] == "engineer"
    assert payload["receipt"]["delivery_profile"]["checks"] == 1
```

- [ ] **Step 2: Run public submit tests to verify failures**

Run:

```bash
python -m pytest tests/test_cli.py::test_delivery_profile_submit_flag_parses tests/test_cli.py::test_submit_json_returns_answer_and_receipt tests/test_http_surface.py::test_submit_accepts_delivery_profile_field tests/test_http_surface.py::test_submit_rejects_unknown_delivery_profile tests/test_mcp_surface.py::test_prefixed_submit_accepts_delivery_profile_field -q
```

Expected: FAIL because submit profile fields are not exposed yet.

- [ ] **Step 3: Update CLI submit**

In `src/forum/cli.py`, change submit call:

```python
        answer = asyncio.run(
            orch.submit(
                args.request,
                budget=budget,
                context_budget=context_budget,
                delivery_profile=args.delivery_profile,
            )
        )
```

Change `ValueError` handling:

```python
    except ValueError as exc:
        print(f"submit failed: {exc}", file=sys.stderr)
        return 1
```

Change `submit_receipt` call:

```python
        delivery_profile=args.delivery_profile,
```

Add parser argument:

```python
    submit.add_argument("--delivery-profile", default=None, help="delivery profile to witness: operator, engineer, researcher, executive")
```

- [ ] **Step 4: Update HTTP submit parsing**

In `src/forum/http_surface.py`, inside `_submit`, add:

```python
        delivery_profile = data.get("delivery_profile")
        if delivery_profile is not None and (not isinstance(delivery_profile, str) or not delivery_profile):
            return error(400, "field 'delivery_profile' must be a non-empty string when provided")
```

Change submit call:

```python
            answer = await self._orch.submit(request, context_budget=context_budget, delivery_profile=delivery_profile)
```

Change `except ValueError` in `_submit`:

```python
        except ValueError as exc:
            message = str(exc)
            if "unknown delivery profile" in message:
                return error(400, message)
            return error(
                502,
                "the configured executor did not return valid JSON; point the "
                f"daemon at a real model executor ({exc})",
            )
```

Change receipt call:

```python
            delivery_profile=delivery_profile,
```

- [ ] **Step 5: Update MCP submit routing and schema**

In `src/forum/mcp_surface.py`, update `_submit_body`:

```python
    if "delivery_profile" in arguments:
        body["delivery_profile"] = arguments["delivery_profile"]
```

In `_SUBMIT_PROPERTIES`, add:

```python
    "delivery_profile": {"type": "string", "description": "delivery profile: operator, engineer, researcher, executive"},
```

- [ ] **Step 6: Run surface tests**

Run:

```bash
python -m pytest tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py tests/test_report.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit report, receipt, and submit surfaces**

```bash
git add src/forum/report.py src/forum/receipts.py src/forum/cli.py src/forum/http_surface.py src/forum/mcp_surface.py tests/test_report.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py
git commit -m "feat: expose delivery profile checks"
```

---

### Task 6: Documentation and Example

**Files:**
- Create: `examples/run_delivery_profile.py`
- Modify: `README.md`
- Modify: `USAGE.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: public delivery profile behavior from Tasks 1-5.
- Produces: docs and example for profile selection.

- [ ] **Step 1: Add runnable example**

Create `examples/run_delivery_profile.py`:

```python
"""Forum: expert delivery profiles, witnessed prose contracts (v1.14).

Forum can now witness whether a delivered answer meets a selected expert delivery
profile. The profile is deterministic: it flags generic model tells, filler, indirect
openings, and missing domain evidence without rewriting facts.

Run:  python examples/run_delivery_profile.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.report import summarize
from forum.roster import loads


ROSTER = loads(
    """
[[agent]]
name = "backend"
category = "engineering"
domain = "apis"
keywords = ["api"]
model_tier = "capable"
executor = "scripted"
"""
)


class Executor:
    async def run(self, assignment):
        agent = assignment.agent
        if agent == "coordinator":
            return Result(
                assignment.task_id,
                agent,
                '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build the api", "depends_on": []}]}',
            )
        if agent == "validator":
            return Result(assignment.task_id, agent, '{"ok": true, "score": 1.0, "reason": "ok"}')
        if agent == "synthesizer":
            return Result(assignment.task_id, agent, "The module passes the focused test from the ledger. Ship the API.")
        return Result(assignment.task_id, agent, "done")


def main() -> None:
    ticks = iter(float(t) for t in range(1, 1000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER,
        ledger,
        Executor(),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=1),
    )
    answer = asyncio.run(orch.submit("build the api", delivery_profile="engineer"))
    summary = summarize(ledger)
    print(answer)
    print("delivery profile checks:", summary["delivery_profile_checks"])
    print("delivery profile flagged:", summary["delivery_profile_flagged"])
    print("ledger verified:", summary["verified"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update README**

In `README.md`, add to the pains list:

```markdown
- **"The answer still sounds like generic model output."** Expert Delivery Profiles check the final answer against a selected local prose contract (`operator`, `engineer`, `researcher`, or `executive`) and witness the result as `delivery_profile_check`. (v1.14)
```

In the examples list, add:

```markdown
python examples/run_delivery_profile.py # witnessed expert delivery profiles
```

In the module list, extend the `forum.delivery` bullet to mention `forum.delivery_profile`.

In the roadmap, add:

```markdown
- **1.14, expert delivery profiles.** Deterministic local profile checks for operator, engineer, researcher, and executive delivery, witnessed in the ledger and exposed across CLI, HTTP, MCP, receipts, summary, and bench.
```

- [ ] **Step 3: Update USAGE**

Add:

````markdown
## Expert Delivery Profiles

```bash
forum humanize "Prior to launch, utilize the module test output." --profile engineer
forum submit "ship the api" --cmd "ollama run llama3" --delivery-profile engineer --json
```

Profiles are deterministic checks, not named-writer mimicry. `operator` is the default
contract; `engineer`, `researcher`, and `executive` add domain-specific expectations.
Submit runs witness `delivery_profile_check` entries, and `forum ledger summary --json`
reports profile checks and flags.
````

- [ ] **Step 4: Update ARCHITECTURE**

In `ARCHITECTURE.md`, extend the delivery section with:

```markdown
Expert Delivery Profiles add a second deterministic floor beside concision. A selected
profile (`operator`, `engineer`, `researcher`, or `executive`) checks the delivered
answer for model tells, indirect openings, filler, domain evidence language, and
profile-specific shape. The check is witnessed as `delivery_profile_check`; it does not
rewrite facts and it does not fail the run. It gives the operator a local, replayable
contract for how the answer was delivered.
```

- [ ] **Step 5: Update CHANGELOG**

Under `## Unreleased`, add:

```markdown
- Expert Delivery Profiles: adds deterministic profile checks for `operator`, `engineer`, `researcher`, and `executive` prose, with `delivery_profile_check` ledger entries, summary/bench metrics, receipt fields, and CLI/HTTP/MCP profile selection for `humanize` and `submit`.
```

- [ ] **Step 6: Run docs/example verification**

Run:

```bash
python examples/run_delivery_profile.py
python -m pytest tests/test_delivery_profile.py tests/test_humanize.py tests/test_delivery.py tests/test_report.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py -q
```

Expected: example prints `ledger verified: True`; tests PASS.

- [ ] **Step 7: Commit**

```bash
git add README.md USAGE.md ARCHITECTURE.md CHANGELOG.md examples/run_delivery_profile.py
git commit -m "docs: document expert delivery profiles"
```

---

### Task 7: Final Verification

**Files:**
- Read-only verification across the working tree.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: evidence that v1.14 Expert Delivery Profiles satisfy the spec.

- [ ] **Step 1: Run targeted test slice**

Run:

```bash
python -m pytest tests/test_delivery_profile.py tests/test_humanize.py tests/test_delivery.py tests/test_report.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py -q
```

Expected: PASS.

- [ ] **Step 2: Run package-facing checks**

Run:

```bash
forum status --json
forum doctor --json
python examples/run_delivery_profile.py
```

Expected: `forum status --json` and `forum doctor --json` emit JSON action envelopes with `status: MATCH`; the example prints `ledger verified: True`.

- [ ] **Step 3: Run full suite**

Run:

```bash
python -m pytest -q
```

Expected: PASS with the real-model tests skipped unless `FORUM_RUN_REAL=1`.

- [ ] **Step 4: Inspect git diff and branch state**

Run:

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors; clean branch after commits. No `.env`, credentials, or private payloads are staged.

- [ ] **Step 5: Finish without an empty commit**

If verification required no fixes, do not create another commit. If verification did
require fixes, make the smallest targeted edits, rerun the failed verification command,
then repeat Step 4 before committing the exact changed files shown by
`git status --short`.
