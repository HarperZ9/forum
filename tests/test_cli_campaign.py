import json

from forum.cli import main
from forum.ledger import Ledger
from forum.storage import FileStorage


def _campaign_file(tmp_path):
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps({
        "campaign_id": "camp1",
        "title": "uplift",
        "projects": [
            {
                "project_id": "crucible", "owner": "forum", "priority": 10,
                "features": [
                    {"feature_id": "c1", "title": "schema", "agent": "backend",
                     "instruction": "build schema", "priority": 5,
                     "depends_on": [], "done_when": []},
                    {"feature_id": "c2", "title": "endpoint", "agent": "backend",
                     "instruction": "endpoint", "priority": 3,
                     "depends_on": ["c1"], "done_when": []},
                ],
            },
            {
                "project_id": "telos", "owner": "external:telos", "priority": 8,
                "features": [
                    {"feature_id": "t1", "title": "engine", "agent": "external",
                     "instruction": "engine", "priority": 0,
                     "depends_on": [], "done_when": []},
                ],
            },
        ],
    }))
    return str(path)


# --- E2: CLI declare -> status -> next -> ingest-status round-trip ---


def test_campaign_declare_writes_declared_entry(tmp_path, capsys):
    d = str(tmp_path / "led")
    f = _campaign_file(tmp_path)
    rc = main(["campaign", "declare", "--file", f, "--ledger", d])
    assert rc == 0
    led = Ledger(FileStorage(d))
    declared = led.query(kind="campaign_declared")
    assert len(declared) == 1
    assert led.get_payload(declared[0].payload_hash)["campaign_id"] == "camp1"


def test_campaign_status_json(tmp_path, capsys):
    d = str(tmp_path / "led")
    f = _campaign_file(tmp_path)
    main(["campaign", "declare", "--file", f, "--ledger", d])
    capsys.readouterr()  # drop declare output
    rc = main(["campaign", "status", "--campaign-id", "camp1", "--ledger", d, "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["campaign_id"] == "camp1"
    assert out["complete"] is False
    assert out["counts"]["pending"] == 3


def test_campaign_status_text(tmp_path, capsys):
    d = str(tmp_path / "led")
    f = _campaign_file(tmp_path)
    main(["campaign", "declare", "--file", f, "--ledger", d])
    rc = main(["campaign", "status", "--campaign-id", "camp1", "--ledger", d, "--text"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "campaign room" in out
    assert "camp1" in out


def test_campaign_next_json(tmp_path, capsys):
    d = str(tmp_path / "led")
    f = _campaign_file(tmp_path)
    main(["campaign", "declare", "--file", f, "--ledger", d])
    capsys.readouterr()  # drop declare output
    rc = main(["campaign", "next", "--campaign-id", "camp1", "--ledger", d, "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    kinds = [a["kind"] for a in out["next_actions"]]
    assert "dispatch_feature" in kinds


def test_campaign_ingest_status_records_external(tmp_path, capsys):
    d = str(tmp_path / "led")
    f = _campaign_file(tmp_path)
    main(["campaign", "declare", "--file", f, "--ledger", d])
    rc = main([
        "campaign", "ingest-status", "--campaign-id", "camp1", "--ledger", d,
        "--project", "telos", "--feature", "t1", "--status", "done",
        "--source", "external:telos", "--reason", "shipped",
    ])
    assert rc == 0
    led = Ledger(FileStorage(d))
    fs = led.query(kind="feature_status")
    assert fs
    body = led.get_payload(fs[-1].payload_hash)
    assert body["source"] == "external:telos"
    assert body["feature_id"] == "t1"
    # and it shows up in status
    capsys.readouterr()  # drop declare + ingest output
    rc = main(["campaign", "status", "--campaign-id", "camp1", "--ledger", d, "--json"])
    out = json.loads(capsys.readouterr().out)
    t1 = next(x for x in out["features"] if x["feature_id"] == "t1")
    assert t1["status"] == "done"
    assert t1["external_source"] == "external:telos"


def test_campaign_ingest_project_status_without_feature(tmp_path):
    d = str(tmp_path / "led")
    f = _campaign_file(tmp_path)
    main(["campaign", "declare", "--file", f, "--ledger", d])
    rc = main([
        "campaign", "ingest-status", "--campaign-id", "camp1", "--ledger", d,
        "--project", "telos", "--status", "in_progress",
        "--source", "external:telos",
    ])
    assert rc == 0
    led = Ledger(FileStorage(d))
    assert led.query(kind="project_status")
    assert led.query(kind="feature_status") == []


def test_campaign_run_dispatches_forum_features(tmp_path, capsys):
    d = str(tmp_path / "led")
    f = _campaign_file(tmp_path)
    main(["campaign", "declare", "--file", f, "--ledger", d])
    # --cmd echoes success for each feature
    rc = main([
        "campaign", "run", "--campaign-id", "camp1", "--ledger", d,
        "--cmd", "python -c \"import sys;print('ok')\"",
    ])
    assert rc == 0
    led = Ledger(FileStorage(d))
    status_entries = led.query(kind="feature_status")
    done = {led.get_payload(e.payload_hash)["feature_id"]
            for e in status_entries
            if led.get_payload(e.payload_hash)["status"] == "done"}
    # both forum features complete; external t1 is never dispatched
    assert "c1" in done and "c2" in done
    assert "t1" not in done


def test_campaign_no_subcommand_prints_help(capsys):
    rc = main(["campaign"])
    assert rc == 1


def test_campaign_declare_cycle_reports_error(tmp_path, capsys):
    d = str(tmp_path / "led")
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "campaign_id": "cyc", "title": "t",
        "projects": [{
            "project_id": "p", "owner": "forum", "priority": 1,
            "features": [
                {"feature_id": "a", "title": "a", "agent": "x", "instruction": "ia",
                 "priority": 0, "depends_on": ["b"], "done_when": []},
                {"feature_id": "b", "title": "b", "agent": "x", "instruction": "ib",
                 "priority": 0, "depends_on": ["a"], "done_when": []},
            ],
        }],
    }))
    rc = main(["campaign", "declare", "--file", str(path), "--ledger", d])
    assert rc != 0
