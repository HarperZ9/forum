from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

from forum.http_response import Response, error, json_response

if TYPE_CHECKING:
    from forum.engine import Orchestrator


class HttpReadMixin:
    """Request-body validation helpers and the read (GET) endpoint handlers.

    A mixin on HttpSurface: every method reaches the orchestrator through
    ``self._orch`` and the shared validation helpers through ``self``. It holds no
    state of its own and is never instantiated alone. Split out of http_surface to
    keep each module within the size gate; behavior is unchanged.
    """

    if TYPE_CHECKING:  # supplied by HttpSurface, the composed host
        _orch: Orchestrator

    # --- validation helpers ---

    def _read_json(self, body: bytes):
        if not body:
            return None, error(400, "expected a JSON body")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None, error(400, "body is not valid JSON")
        if not isinstance(data, dict):
            return None, error(400, "body must be a JSON object")
        return data, None

    def _str_field(self, data: dict, name: str):
        value = data.get(name)
        if not isinstance(value, str) or not value:
            return None, error(400, f"field {name!r} (a non-empty string) is required")
        return value, None

    def _seq_suffix(self, path: str, prefix: str):
        try:
            return int(path[len(prefix):]), None
        except ValueError:
            return None, error(400, f"{prefix}<seq> requires an integer seq")

    def _context_budget(self, data: dict):
        from forum.context_budget import ContextBudget

        mapping = {
            "context_token_budget": "max_total_tokens",
            "request_context_token_budget": "max_request_tokens",
            "task_context_token_budget": "max_task_tokens",
            "upstream_token_budget": "max_upstream_tokens",
        }
        kwargs = {}
        for field, target in mapping.items():
            if field not in data:
                continue
            value = data[field]
            if type(value) is not int:
                return None, None, error(400, f"field {field!r} must be an integer")
            kwargs[target] = value
        if not kwargs:
            return None, {}, None
        try:
            budget = ContextBudget(**kwargs)
        except ValueError as exc:
            return None, None, error(400, str(exc))
        return budget, budget.configured_limits(), None

    def _non_negative_int_field(self, data: dict, name: str, *, default: int):
        value = data.get(name, default)
        if type(value) is not int:
            return None, error(400, f"field {name!r} must be an integer when provided")
        if value < 0:
            return None, error(400, f"field {name!r} must be >= 0")
        return value, None

    # --- read handlers ---

    def _ledger_get(self, path: str) -> Response:
        seq, err = self._seq_suffix(path, "/ledger/")
        if err:
            return err
        try:
            entry = self._orch.ledger.get(seq)
        except KeyError:
            return error(404, f"no ledger entry at seq {seq}")
        return json_response(dataclasses.asdict(entry))

    def _replay(self, path: str) -> Response:
        seq, err = self._seq_suffix(path, "/replay/")
        if err:
            return err
        entries = self._orch.ledger.replay(until=seq)
        return json_response({"entries": [dataclasses.asdict(e) for e in entries]})

    def _capsule(self) -> Response:
        from forum.context_capsule import build_context_capsule

        return json_response(build_context_capsule(self._orch.ledger))

    def _room(self) -> Response:
        from forum.run_room import build_run_room

        return json_response(build_run_room(self._orch.ledger))

    def _gates(self) -> Response:
        from forum.gates import gate_resolution

        led = self._orch.ledger
        pending = []
        for entry in led.query(kind="gate_pending"):
            body = led.get_payload(entry.payload_hash)
            run_seq = body.get("run_seq")
            wave = body.get("wave")
            if gate_resolution(led, run_seq, wave) == "pending":
                item = {
                    "seq": entry.seq,
                    "run_seq": run_seq,
                    "wave": wave,
                    "tasks": list(body.get("tasks") or []),
                    "question": body.get("question", ""),
                }
                deadline = body.get("deadline")
                if isinstance(deadline, (int, float)):
                    # bounded gate: expose the deadline and the auto-decision that
                    # fires on resume if it lapses (reject unless operator opted in)
                    item["deadline"] = float(deadline)
                    item["on_expiry"] = str(body.get("on_expiry") or "reject")
                pending.append(item)
        return json_response({"pending": pending})

    def _runtime(self) -> Response:
        from forum.runtime_descriptor import descriptors_from_executor
        from forum.runtime_inspect import inspect_runtime

        default, tiers = descriptors_from_executor(self._orch.executor)
        return json_response(inspect_runtime(default, tiers, self._orch.roster))
