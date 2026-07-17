"""The operator brief must not conflate ledger-integrity with answer-acceptance,
and must not downgrade a CONFIRMED intent drift to a possible one."""
from forum.run_brief import build_room_brief


def _room(**over):
    room = {
        "request": {"text": "q"},
        "verified": True,
        "answer": {"text": "an answer"},
        "signals": {},
        "next_actions": [],
        "tasks": [],
        "route_frame": {},
    }
    room.update(over)
    return room


def test_complete_does_not_claim_answer_acceptance_from_ledger_alone():
    # a run with an intact ledger but NO external verification must not read as
    # if the answer was accepted: the summary is ledger-scoped, and a bullet
    # names that no external check ran
    b = build_room_brief(_room(signals={}))
    assert b["state"] == "complete"
    assert "verified" not in b["summary"].lower() or "ledger" in b["summary"].lower()
    assert any("external verification" in bl.lower() for bl in b["bullets"])
    assert any("none" in bl.lower() and "verification" in bl.lower() for bl in b["bullets"])


def test_confirmed_intent_drift_is_not_downgraded_to_possible():
    # a semantic intent judge ruling (intent_drift_judged) is a CONFIRMED drift,
    # not a 'possible' one from the lexical check
    b = build_room_brief(_room(signals={"intent_drift_judged": 1, "flagged_intent": 1}))
    assert "confirmed" in b["risk"].lower() and "drift" in b["risk"].lower()
    assert "possible" not in b["risk"].lower()


def test_lexical_flag_alone_stays_possible():
    b = build_room_brief(_room(signals={"flagged_intent": 1}))
    assert "possible" in b["risk"].lower()
