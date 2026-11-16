import json

import pytest

from factory_events.cli import main


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """The state directory: the adapters' watermarks and the anchor."""
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def test_emit_appends_valid_event(capsys, memory_chain):
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
    [record] = memory_chain.records
    assert record["seq"] == 1 and record["event"]["event_id"] == out


def test_emit_json_payload(memory_chain):
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
    assert memory_chain.events[0]["evidence"] == [{"note": "hello"}]


def test_emit_rejects_bad_action(memory_chain):
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
    assert memory_chain.records == []


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


def test_adapt_high_power_via_cli(tmp_path, monkeypatch, capsys, memory_chain):
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
    assert [event["action"] for event in memory_chain.events] == ["tool.vps_exec"]


def test_no_test_reaches_the_real_portfolio_feed(tmp_path):
    """conftest's floor: `adapt --source all` reads the feed, so a test that names no feed path
    still never reads ~/.portfolio/portfolio-feed.json."""
    from factory_events.adapters import portfolio_scan

    path = portfolio_scan.feed_path()
    assert path.is_relative_to(tmp_path)
    assert not path.exists()
