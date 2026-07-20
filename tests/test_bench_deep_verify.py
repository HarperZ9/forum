import json

from forum.bench_deep_verify import benchmark_matrix
from forum.cli import main


def test_deep_verify_benchmark_reports_payload_and_deep_timings():
    payload = benchmark_matrix(
        entry_counts=[3],
        payload_body_bytes=[32],
        storage_modes=["memory"],
        redaction_ratios=[0.0, 1.0],
        repeats=1,
        warmups=0,
    )

    assert payload["schema"] == "forum.deep-verify-benchmark/v1"
    assert len(payload["cases"]) == 2
    assert payload["cases"][0]["verify_deep"]["ok"] is True
    assert payload["cases"][0]["payloads_present"] == 3
    assert payload["cases"][1]["payloads_redacted"] == 3
    assert payload["cases"][1]["payloads_present"] == 0


def test_bench_deep_verify_cli_json(capsys):
    rc = main([
        "bench-deep-verify",
        "--entries",
        "2",
        "--payload-bytes",
        "16",
        "--redaction-ratio",
        "0",
        "--warmups",
        "0",
        "--repeats",
        "1",
        "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["schema"] == "forum.deep-verify-benchmark/v1"
    assert payload["cases"][0]["entry_count"] == 2
    assert payload["cases"][0]["verify_payloads"]["ok"] is True
