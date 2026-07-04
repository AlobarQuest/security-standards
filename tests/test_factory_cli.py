import json

import pytest

from factory_events import store
from factory_events.cli import main


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def test_emit_appends_valid_event(capsys):
    rc = main(
        [
            "emit",
            "--actor",
            "devon",
            "--action",
            "factory.bootstrap",
            "--result",
            "success",
            "--ref",
            "manual",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("evt-")
    head = store.head()
    assert head is not None
    assert head[0] == 1


def test_emit_json_payload(capsys):
    payload = json.dumps({"note": "hello"})
    rc = main(
        [
            "emit",
            "--actor",
            "devon",
            "--action",
            "factory.note",
            "--result",
            "success",
            "--ref",
            "manual",
            "--evidence-json",
            payload,
        ]
    )
    assert rc == 0
    rec = list(store.iter_records())[0]
    assert rec is not None
    assert rec["event"]["evidence"] == [{"note": "hello"}]


def test_emit_rejects_bad_action(capsys):
    rc = main(
        [
            "emit",
            "--actor",
            "devon",
            "--action",
            "no-dots-here!",
            "--result",
            "success",
            "--ref",
            "manual",
        ]
    )
    assert rc == 1


def test_verify_ok_and_failure(capsys, tmp_path):
    main(
        [
            "emit",
            "--actor",
            "devon",
            "--action",
            "factory.bootstrap",
            "--result",
            "success",
            "--ref",
            "manual",
        ]
    )
    assert main(["verify"]) == 0
    path = store.events_path()
    line = json.loads(path.read_text())
    line["event"]["actor"] = "mallory"
    path.write_text(json.dumps(line) + "\n")
    assert main(["verify"]) == 1


def test_usage_error_exits_1(capsys):
    rc = main(
        [
            "emit",
            "--actor",
            "devon",
            "--action",
            "factory.x",
            "--result",
            "bogus",
            "--ref",
            "manual",
        ]
    )
    assert rc == 1


def test_help_exits_0(capsys):
    assert main(["--help"]) == 0


def test_verify_tolerate_torn_tail_cli_path(capsys):
    main(
        [
            "emit",
            "--actor",
            "devon",
            "--action",
            "factory.bootstrap",
            "--result",
            "success",
            "--ref",
            "manual",
        ]
    )
    from factory_events import store

    with store.events_path().open("a") as fh:
        fh.write('{"seq": 2, "prev_hash": "abc", "ha')
    assert main(["verify"]) == 1
    assert main(["verify", "--tolerate-torn-tail"]) == 0


def test_adapt_high_power_via_cli(tmp_path, monkeypatch, capsys):
    src = tmp_path / "hp.jsonl"
    record = {
        "timestamp": "2026-07-02T23:33:35Z",
        "tool": "mcp__infraops__vps_exec",
        "session_id": "s",
        "args_summary": "{}",
        "provenance": "unknown (confirm at review: direct request vs inferred from read content)",
    }
    src.write_text(json.dumps(record) + "\n")
    from factory_events.adapters import high_power

    monkeypatch.setattr(high_power, "DEFAULT_SOURCE", src)
    assert main(["adapt", "--source", "high-power"]) == 0
    assert "1 events appended" in capsys.readouterr().out
