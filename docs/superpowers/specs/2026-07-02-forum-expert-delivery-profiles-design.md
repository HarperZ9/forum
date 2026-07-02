# Forum v1.14 Expert Delivery Profiles Design

> Make Forum's final answers and humanized prose feel like a refined specialist wrote
> them, while keeping the contract local, deterministic, measurable, and witnessed.

| | |
|---|---|
| Project | Forum |
| Release target | v1.14 |
| Status | Design written, pending operator review |
| Location | `C:/dev/public/forum` |
| Primary goal | Domain-aware prose and delivery contracts for local orchestration |
| Related modules | `forum.delivery`, `forum.humanize`, `forum.report`, `forum.engine`, `forum.http_surface`, `forum.mcp_surface` |

## 1. Why this is the next milestone

The larger objective is for Forum to become the Project Telos user platform and
execution layer, not just another agent harness. Context Pressure made runs cheaper
and more explicit. The next missing control point is delivery quality: Forum can detect
verbose prose and can simplify a single pasted text, but it cannot yet say what kind of
expert should be speaking, what delivery standard the answer must satisfy, or how that
standard was checked.

The user experience target is clear: the operator should feel they are working with a
competent specialist, not with a generic language model. That does not mean imitating
named writers or copying a public figure's style. Forum should instead encode the
mechanics that make expert prose work: direct openings, concrete claims, low filler,
domain-appropriate evidence language, clear uncertainty markers, and no model
preambles.

This milestone adds a deterministic profile layer first. A later model-backed reviser
can write toward a profile, but the first contract must be local and testable so Forum
can prove a delivery surface improved without trusting the model that produced it.

## 2. Scope

In scope:

- a new pure `forum.delivery_profile` module;
- named delivery profiles for `operator`, `engineer`, `researcher`, and `executive`;
- deterministic profile checks for both final answers and `forum humanize`;
- witnessed `delivery_profile_check` ledger entries during `Orchestrator.submit`;
- summary and bench metrics for profile checks;
- CLI, HTTP, and MCP profile options for humanize and submit;
- docs and an example showing profile selection.

Out of scope for v1.14:

- model-generated style transfer;
- named writer or public-figure mimicry;
- per-agent personality memory;
- prompt-template marketplaces;
- UI rooms, dashboards, or multi-session workspaces;
- changing the `Reviser` protocol;
- semantic truth verification beyond the existing intent and verifier seams.

## 3. Requirements

1. Forum core must remain zero-dependency.
2. Profile checks must be deterministic and replayable.
3. Existing behavior must remain compatible when no delivery profile is provided.
4. Profile checks must not silently rewrite facts.
5. A delivery profile must be a measurable standard, not a request to imitate a named
   writer.
6. A profile failure must be witnessed and summarized, not treated as a fatal run
   failure.
7. CLI, HTTP, MCP, Python API, README, USAGE, ARCHITECTURE, and CHANGELOG must stay
   aligned.
8. Tests must cover profile rules, run integration, reports, receipts where relevant,
   and public surface parsing.

## 4. Design Principle

The profile layer is a floor, not a stylist. It answers: "Did this answer meet the
minimum delivery contract for this audience?" It does not answer: "Is this beautiful?"
or "Would a named writer have said this?"

That separation keeps Forum local and auditable. The deterministic floor catches
generic model tells and domain mismatches. A future profile-aware reviser can improve
flagged answers, but any accepted rewrite still has to pass the same deterministic
contract.

## 5. Profiles

Profiles are frozen data, loaded from code in v1.14. They can become manifest-backed
later, but the first version should be explicit and tested.

### `operator`

Default operational prose. It should be terse, concrete, and action-oriented.

Rules:

- no model preambles;
- no first-person model disclaimers;
- max mean sentence words: 24;
- filler ratio at or below 0.04;
- the first sentence should not begin with a hedge such as "It seems" or "Maybe";
- at least one concrete action verb when the answer is longer than one sentence.

### `engineer`

For implementation, architecture, debugging, and code review.

Rules:

- all `operator` rules;
- concrete technical nouns are expected: file, test, API, module, function, command,
  error, schema, or equivalent;
- vague claims such as "optimize the system" are flagged unless paired with a measurable
  target;
- uncertainty should be labeled with evidence language such as "unknown", "not
  verified", "from the test output", or "from the ledger".

### `researcher`

For analysis, papers, evidence review, and synthesis.

Rules:

- all `operator` rules except action-verb requirement;
- evidence language is expected: "source", "citation", "observed", "measured",
  "reported", "unknown", or "not verified";
- overconfident words such as "proves", "certainly", and "obviously" are flagged unless
  the answer also carries evidence language.

### `executive`

For briefings and decision support.

Rules:

- all `operator` rules;
- opening sentence must state the decision, status, or recommendation directly;
- answer longer than 120 words should be flagged as too long for the profile;
- implementation detail should be present only when attached to impact, risk, or next
  action.

## 6. Core API

Create:

```text
forum.delivery_profile
```

Primary types:

```text
DeliveryProfile
  name: str
  max_mean_sentence_words: float
  max_filler_ratio: float
  max_words: int | None
  banned_starts: tuple[str, ...]
  banned_phrases: tuple[str, ...]
  required_terms: tuple[str, ...]
  requires_action_verb: bool
  requires_evidence_language: bool
  direct_opening: bool

ProfileFinding
  code: str
  detail: str

ProfileAssessment
  schema: "forum.delivery-profile/v1"
  profile: str
  words: int
  sentences: int
  mean_sentence_words: float
  filler_ratio: float
  flagged: bool
  findings: tuple[ProfileFinding, ...]
```

Core functions:

```text
get_profile(name: str | None) -> DeliveryProfile
list_profiles() -> tuple[str, ...]
assess_profile(text: str, profile: str | DeliveryProfile | None = None) -> ProfileAssessment
profile_payload(assessment: ProfileAssessment) -> dict
```

Default profile is `operator`.

Unknown profile names raise `ValueError` with a clear list of valid profile names.

## 7. Integration Points

### `forum humanize`

`humanize_text(text, audience="operator", profile=None)` will apply the existing
simplification rules and then assess the result with the selected profile. It will not
invent facts or rewrite toward a profile beyond the current deterministic replacements.
The returned payload adds:

```json
{
  "profile": "engineer",
  "profile_check": {
    "schema": "forum.delivery-profile/v1",
    "profile": "engineer",
    "flagged": false,
    "findings": []
  }
}
```

CLI:

```bash
forum humanize "text" --profile engineer
```

HTTP:

```json
{"text": "text", "audience": "operator", "profile": "engineer"}
```

MCP:

`forum.prose.humanize` accepts optional `profile`.

### `Orchestrator.submit`

Add optional `delivery_profile: str | None = None`.

After `_resolve_delivery` returns the answer and answer sequence, Forum assesses the
delivered answer and appends:

```json
{
  "schema": "forum.delivery-profile/v1",
  "profile": "engineer",
  "flagged": true,
  "findings": [
    {"code": "missing_evidence_language", "detail": "engineer profile requires evidence language when uncertainty is present"}
  ],
  "words": 42,
  "sentences": 3,
  "mean_sentence_words": 14.0,
  "filler_ratio": 0.0
}
```

Entry:

```text
actor="delivery-profile"
kind="delivery_profile_check"
causal_parent=<delivered answer seq>
```

The run does not fail when the profile flags. The check is a witnessed signal. A later
release can route flagged profile checks into a profile-aware reviser.

### Public Submit Surfaces

CLI:

```bash
forum submit "ship the api" --cmd "ollama run llama3" --delivery-profile engineer
```

HTTP:

```json
{"request": "ship the api", "delivery_profile": "engineer"}
```

MCP:

`submit` and `forum.submit` accept optional `delivery_profile`.

Receipts add a compact block:

```json
{
  "delivery_profile": {
    "requested": "engineer",
    "checks": 1,
    "flagged": 0
  }
}
```

## 8. Reporting

`summarize(ledger)` adds:

- `delivery_profile_checks`
- `delivery_profile_flagged`
- `delivery_profile_operator`
- `delivery_profile_engineer`
- `delivery_profile_researcher`
- `delivery_profile_executive`

`compare(a, b)` includes these numeric fields. The summary does not claim prose quality
in general; it reports how many profile contracts were checked and how many flagged.

## 9. Error Handling

- Unknown profile names raise `ValueError`.
- CLI profile parse errors return code 2 and write a clear error to stderr.
- HTTP profile parse errors return 400.
- MCP gets the same error through the HTTP adapter and marks `isError` true.
- Empty text in `humanize_text` keeps the existing `ValueError`.
- Profile assessment on an empty answer returns a flagged assessment with
  `code="empty_text"` because delivered answers should not be empty.

## 10. Testing Plan

Core profile tests:

- valid profile names list includes `operator`, `engineer`, `researcher`, `executive`;
- unknown profile raises a message containing valid names;
- model preambles and generic AI disclaimers flag;
- operator profile passes direct, concise prose;
- engineer profile flags vague unsupported optimization claims;
- researcher profile requires evidence language;
- executive profile flags long answers and indirect openings.

Humanize tests:

- `humanize_text(..., profile="engineer")` includes `profile_check`;
- `forum humanize --profile engineer` parses and returns the profile in JSON;
- HTTP and MCP humanize pass profile through the same logic.

Run integration tests:

- `Orchestrator.submit(..., delivery_profile="engineer")` appends a
  `delivery_profile_check`;
- the profile check chains to the delivered answer, including accepted revisions;
- unknown profiles fail clearly before appending a misleading profile check.

Report and receipt tests:

- summary counts profile checks and flagged checks;
- bench compares profile metrics;
- submit receipts include the compact `delivery_profile` block.

Targeted verification:

```bash
python -m pytest tests/test_delivery_profile.py tests/test_humanize.py tests/test_delivery.py tests/test_report.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py -q
python -m pytest -q
```

## 11. Rollout

1. Add `forum.delivery_profile` with pure tests.
2. Extend `humanize_text` and humanize CLI/HTTP/MCP surfaces.
3. Extend `Orchestrator.submit` with witnessed `delivery_profile_check`.
4. Add summary, bench, and receipt metrics.
5. Add submit surface parsing for `delivery_profile`.
6. Add docs and an example.
7. Run targeted and full verification.

## 12. How this advances the larger objective

Expert Delivery Profiles move Forum from "runs tasks and checks verbosity" toward a
local expert execution layer. The feature does not depend on a frontier model. It
turns delivery quality into a contract that can be selected, checked, witnessed, and
compared.

This complements Context Pressure:

- Context Pressure controls what information reaches the model.
- Expert Delivery Profiles control what standard the final answer must meet.
- Receipts and summaries show both, so a run can prove it was bounded and delivered
  through the requested expert channel.

Future milestones can build on this by adding profile-aware revisers, per-agent profile
defaults in the roster, local model endpoint routing by profile, and platform run rooms
that show context pressure and delivery profile status together.
