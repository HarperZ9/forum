from forum.hashing import canonical_hash


def test_hash_is_stable_under_key_reordering():
    a = canonical_hash({"x": 1, "y": 2})
    b = canonical_hash({"y": 2, "x": 1})
    assert a == b
    assert len(a) == 64


def test_hash_distinguishes_different_payloads():
    assert canonical_hash({"x": 1}) != canonical_hash({"x": 2})
