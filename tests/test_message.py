from forum.hashing import canonical_hash
from forum.message import new_message


def test_new_message_computes_payload_hash():
    m = new_message("request", "surface", {"task": "build api"}, id="m1")
    assert m.payload_hash == canonical_hash({"task": "build api"})
    assert m.kind == "request"
    assert m.sender == "surface"
    assert m.causal_parent is None


def test_messages_are_immutable():
    import dataclasses
    m = new_message("result", "worker", "done", id="m2", causal_parent="m1")
    assert m.causal_parent == "m1"
    try:
        m.kind = "other"  # type: ignore[misc]
        assert False, "expected frozen dataclass"
    except dataclasses.FrozenInstanceError:
        pass
