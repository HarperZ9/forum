import itertools

from forum.metrics import (
    DURATION_BUCKETS_SECONDS,
    MetricsRegistry,
)


def _reg(boundaries=(1.0, 2.0), clock=None):
    return MetricsRegistry(
        clock=clock or (lambda: 0),
        boundaries=boundaries,
    )


def _only(reg):
    points = reg.collect()
    assert len(points) == 1
    return points[0]


def test_bucketing_is_upper_inclusive():
    # boundaries (1,2) -> buckets (-inf,1], (1,2], (2,+inf)
    reg = _reg()
    reg.record_request(method="GET", status_code=200, duration_seconds=1.0)  # == bound -> bucket 0
    reg.record_request(method="GET", status_code=200, duration_seconds=2.0)  # == bound -> bucket 1
    p = _only(reg)
    assert p.bucket_counts == (1, 1, 0)  # 1.0 closes bucket 0, 2.0 closes bucket 1
    assert p.count == 2 and p.sum == 3.0
    assert p.min == 1.0 and p.max == 2.0


def test_below_first_and_above_last_bounds():
    reg = _reg()
    reg.record_request(method="GET", status_code=200, duration_seconds=0.5)  # below first
    reg.record_request(method="GET", status_code=200, duration_seconds=9.9)  # above last -> overflow
    p = _only(reg)
    assert p.bucket_counts == (1, 0, 1)
    assert p.min == 0.5 and p.max == 9.9


def test_count_sum_min_max_accumulate():
    reg = _reg()
    for d in (0.5, 1.5, 2.5):
        reg.record_request(method="GET", status_code=200, duration_seconds=d)
    p = _only(reg)
    assert p.count == 3
    assert p.sum == 4.5
    assert p.min == 0.5 and p.max == 2.5


def test_distinct_attribute_sets_are_distinct_cells():
    reg = _reg()
    reg.record_request(method="GET", status_code=200, duration_seconds=0.5, route="/status")
    reg.record_request(method="POST", status_code=200, duration_seconds=0.5, route="/status")
    reg.record_request(method="GET", status_code=500, duration_seconds=0.5, route="/status")
    assert len(reg.collect()) == 3  # method and status each split the series


def test_none_route_collapses_into_one_no_route_cell():
    reg = _reg()
    # two different unknown targets, both route=None -> one cell, no http.route attr
    reg.record_request(method="GET", status_code=404, duration_seconds=0.5, route=None)
    reg.record_request(method="GET", status_code=404, duration_seconds=0.5, route=None)
    p = _only(reg)
    assert p.count == 2
    keys = [k for k, _ in p.attributes]
    assert "http.route" not in keys  # unknown paths carry no route attribute


def test_attributes_are_sorted_key_pairs():
    reg = _reg()
    reg.record_request(method="GET", status_code=200, duration_seconds=0.5, route="/status")
    p = _only(reg)
    keys = [k for k, _ in p.attributes]
    assert keys == sorted(keys)
    assert dict(p.attributes) == {
        "http.request.method": "GET",
        "http.response.status_code": 200,
        "http.route": "/status",
    }


def test_start_unix_nano_is_captured_once_while_now_advances():
    clock = itertools.count(100)
    reg = MetricsRegistry(clock=lambda: next(clock))
    assert reg.start_unix_nano == 100  # construction consumed the first tick
    assert reg.now() == 101
    assert reg.now() == 102
    assert reg.start_unix_nano == 100  # fixed cumulative start, does not advance


def test_collect_is_cumulative_and_repeatable():
    reg = _reg()
    reg.record_request(method="GET", status_code=200, duration_seconds=1.5)
    first = reg.collect()
    second = reg.collect()
    assert first == second  # collect does not reset (cumulative)
    reg.record_request(method="GET", status_code=200, duration_seconds=1.5)
    assert _only(reg).count == 2  # later records accumulate on top


def test_empty_registry_collects_nothing():
    assert MetricsRegistry().collect() == []


def test_default_boundaries_are_the_stable_semconv_set():
    reg = MetricsRegistry()
    assert reg.boundaries == DURATION_BUCKETS_SECONDS
    reg.record_request(method="GET", status_code=200, duration_seconds=0.5)
    # 0.5 is a boundary (index 7); upper-inclusive puts it in bucket 7
    p = reg.collect()[0]
    assert len(p.bucket_counts) == len(DURATION_BUCKETS_SECONDS) + 1
    assert p.bucket_counts[7] == 1
