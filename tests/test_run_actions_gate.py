from forum.run_actions import derive_next_actions


def _base(**signals):
    s = {
        "budget_stops": 0,
        "failed_results": 0,
        "failed_verdicts": 0,
        "flagged_delivery": 0,
        "flagged_intent": 0,
        "refuted_verifications": 0,
        "pending_gates": 0,
    }
    s.update(signals)
    return s


def test_pending_gate_produces_high_priority_review_action():
    actions = derive_next_actions(
        request={"seq": 0},
        tasks=[],
        checkpoints=[],
        answer=None,
        signals=_base(pending_gates=1),
        pending_gates=[{"run_seq": 1, "wave": 1, "tasks": ["T2"], "question": "approve?"}],
    )
    gate_actions = [a for a in actions if a["kind"] == "review_gate"]
    assert len(gate_actions) == 1
    action = gate_actions[0]
    assert action["priority"] == "high"
    assert action["target"] == {"run_seq": 1, "wave": 1}


def test_review_gate_ranks_before_export_when_answer_present():
    actions = derive_next_actions(
        request={"seq": 0},
        tasks=[],
        checkpoints=[],
        answer={"seq": 5},
        signals=_base(pending_gates=1),
        pending_gates=[{"run_seq": 1, "wave": 1, "tasks": ["T2"], "question": "q"}],
    )
    kinds = [a["kind"] for a in actions]
    assert "review_gate" in kinds
    # a pending gate is a blocking (high) action, so no export is offered
    assert "export_receipt" not in kinds


def test_no_pending_gate_no_review_action():
    actions = derive_next_actions(
        request={"seq": 0},
        tasks=[],
        checkpoints=[],
        answer=None,
        signals=_base(),
    )
    assert all(a["kind"] != "review_gate" for a in actions)
