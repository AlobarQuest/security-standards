"""The portfolio scan's feed -> one `portfolio.scanned` event per scan (ADR-0059 Amendment 11,
decision items 2 and 6). Every feed here is a file under tmp_path; the chain is MemoryChain."""

import json
import os
from pathlib import Path

import pytest

from factory_events import db, envelope
from factory_events.adapters import change_manager, high_power, portfolio_scan
from factory_events.cli import main

SCANNED_AT = "2026-11-17T08:00:35Z"
MARKER = "zz-marker"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """The state directory, and a feed path under tmp_path (conftest already keeps the real
    feed out of reach; this names the one each test writes)."""
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    monkeypatch.setenv(portfolio_scan.FEED_ENV, str(tmp_path / "portfolio-feed.json"))
    yield tmp_path


@pytest.fixture
def other_sources(tmp_path, monkeypatch):
    """`--source all` also runs the other two adapters: an empty high-power log and an empty
    change-manager page, so neither touches a real file or the network."""
    monkeypatch.setattr(high_power, "DEFAULT_SOURCE", tmp_path / "no-high-power.jsonl")
    monkeypatch.setenv("CM_BASE_URL", "https://change-manager.invalid")
    monkeypatch.setenv("CM_M2M_TOKEN", "placeholder")
    monkeypatch.setattr(change_manager, "_http_fetch", lambda after_id, limit: [])


def _rows() -> list[dict]:
    return [
        {
            "repository": "example-owner/repo-a",
            "checks": {
                "factory.landing_known": "pass",
                "factory.pat_access": "pass",
                "factory.secrets": "pass",
                "runner.caller": "pass",
            },
        },
        {
            "repository": "example-owner/repo-b",
            "checks": {"factory.pat_access": "violation", "runner.caller": "violation"},
        },
    ]


def _feed(**overrides) -> dict:
    feed = {
        "schema": "portfolio-feed.v1",
        "scanned_at": SCANNED_AT,
        "member_record_unreadable": None,
        "repositories": _rows(),
    }
    feed.update(overrides)
    return feed


def _feed_file() -> Path:
    """The fixture's path, read from the environment and not through feed_path(), so a broken
    feed_path() can never make a test write the real feed."""
    return Path(os.environ[portfolio_scan.FEED_ENV])


def _write(feed: object) -> None:
    _feed_file().write_text(json.dumps(feed, indent=2, sort_keys=True) + "\n")


def test_a_valid_feed_gives_exactly_one_event_and_a_rerun_appends_nothing(memory_chain):
    _write(_feed())
    assert portfolio_scan.adapt() == 1
    (event,) = memory_chain.events
    assert event == {
        "schema": "factory-event/v1",
        "event_id": envelope.deterministic_event_id("portfolio-scan", SCANNED_AT),
        "timestamp": SCANNED_AT,
        "actor": "portfolio-scan",
        "action": "portfolio.scanned",
        "target": None,
        "work_package": None,
        "input_revision": None,
        "result": "success",
        "evidence": [{"type": "repository", **row} for row in _rows()],
        "authority_grant": None,
        "correlation_id": None,
        "source": {"system": "portfolio-scan", "ref": SCANNED_AT},
    }
    envelope.validate_event(event)

    assert portfolio_scan.adapt() == 0
    assert len(memory_chain.events) == 1


def test_the_event_id_depends_only_on_scanned_at(memory_chain):
    later = "2026-11-18T08:00:31Z"
    _write(_feed())
    portfolio_scan.adapt()
    _write(_feed(scanned_at=later))
    portfolio_scan.adapt()
    # The same scan time with different rows is the same scan: nothing new.
    _write(_feed(scanned_at=later, repositories=_rows()[:1]))
    assert portfolio_scan.adapt() == 0

    assert [event["event_id"] for event in memory_chain.events] == [
        envelope.deterministic_event_id("portfolio-scan", SCANNED_AT),
        envelope.deterministic_event_id("portfolio-scan", later),
    ]
    assert [event["timestamp"] for event in memory_chain.events] == [SCANNED_AT, later]


def test_an_unreadable_member_record_gives_unknown_and_one_typed_item(memory_chain):
    reason = "the orchestrator answered 401 for GET /api/v1/members"
    _write(_feed(member_record_unreadable=reason, repositories=[]))
    assert portfolio_scan.adapt() == 1
    (event,) = memory_chain.events
    assert event["result"] == "unknown"
    assert event["evidence"] == [{"type": "member-record-unreadable", "reason": reason}]


def test_an_unknown_status_value_is_copied_not_refused(memory_chain):
    rows = [{"repository": "example-owner/repo-a", "checks": {"runner.caller": "not-applicable"}}]
    _write(_feed(repositories=rows))
    assert portfolio_scan.adapt() == 1
    assert memory_chain.events[0]["evidence"] == [
        {"type": "repository", "repository": "example-owner/repo-a", "checks": rows[0]["checks"]}
    ]


def test_rows_are_copied_in_the_feeds_order(memory_chain):
    rows = list(reversed(_rows()))
    _write(_feed(repositories=rows))
    portfolio_scan.adapt()
    assert [item["repository"] for item in memory_chain.events[0]["evidence"]] == [
        "example-owner/repo-b",
        "example-owner/repo-a",
    ]


def test_the_override_names_the_feed(tmp_path, monkeypatch):
    monkeypatch.setenv(portfolio_scan.FEED_ENV, str(tmp_path / "elsewhere.json"))
    assert portfolio_scan.feed_path() == tmp_path / "elsewhere.json"


def test_the_default_feed_is_the_portfolio_homes(tmp_path, monkeypatch):
    monkeypatch.delenv(portfolio_scan.FEED_ENV)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert portfolio_scan.feed_path() == tmp_path / ".portfolio" / "portfolio-feed.json"


def _row(**overrides) -> dict:
    return {**_rows()[1], **overrides}


# Each case breaks the feed's contract once (project-standards feed-a report, "For the next
# steps"). Where the bad part is a string, it carries MARKER, which the reason must not echo.
BAD_FEEDS = {
    "not an object": [_feed()],
    "missing key": {k: v for k, v in _feed().items() if k != "member_record_unreadable"},
    "extra key": _feed(detail=MARKER),
    "other schema": _feed(schema=f"portfolio-feed.v2-{MARKER}"),
    "scanned_at pattern": _feed(scanned_at=f"2026-11-17T08:00:35+00:00{MARKER}"),
    "scanned_at with fractions": _feed(scanned_at="2026-11-17T08:00:35.1Z"),
    "scanned_at unpadded": _feed(scanned_at="2026-11-7T08:00:35Z"),
    "scanned_at not a date": _feed(scanned_at="2026-13-45T08:00:35Z"),
    "scanned_at not a string": _feed(scanned_at=1),
    "reason not a string": _feed(member_record_unreadable=401, repositories=[]),
    "reason empty": _feed(member_record_unreadable="", repositories=[]),
    "rows with an unreadable record": _feed(member_record_unreadable=MARKER),
    "repositories not a list": _feed(repositories={"example-owner/repo-a": {}}),
    "row not an object": _feed(repositories=[MARKER]),
    "row with another key": _feed(repositories=[_row(owner=MARKER)]),
    "row without checks": _feed(repositories=[{"repository": "example-owner/repo-a"}]),
    "repository not lowercased": _feed(repositories=[_row(repository=f"Example-Owner/{MARKER}")]),
    "repository without owner": _feed(repositories=[_row(repository=MARKER)]),
    "repository with two slashes": _feed(repositories=[_row(repository=f"a/b/{MARKER}")]),
    "repository not a string": _feed(repositories=[_row(repository=7)]),
    "duplicate repository": _feed(repositories=[_rows()[0], _rows()[0]]),
    "checks not an object": _feed(repositories=[_row(checks=[MARKER])]),
    "check id outside the four": _feed(repositories=[_row(checks={f"factory.{MARKER}": "pass"})]),
    "status not a string": _feed(repositories=[_row(checks={"runner.caller": None})]),
}


@pytest.mark.parametrize("feed", BAD_FEEDS.values(), ids=BAD_FEEDS.keys())
def test_a_bad_feed_appends_nothing_and_leaves_the_exit_alone(
    feed, capsys, memory_chain, other_sources
):
    _write(feed)
    assert main(["adapt", "--source", "all"]) == 0
    out, err = capsys.readouterr()
    assert memory_chain.events == []
    (line,) = [ln for ln in out.splitlines() if ln.startswith("portfolio-scan:")]
    assert line.startswith("portfolio-scan: 0 events appended (feed skipped: ")
    assert MARKER not in out.lower() + err.lower()
    assert "ADAPT FAIL" not in err


@pytest.mark.parametrize("make", ["missing", "a directory", "not utf-8", "not json"])
def test_a_feed_that_cannot_be_read_appends_nothing(make, capsys, memory_chain, other_sources):
    path = _feed_file()
    if make == "a directory":
        path.mkdir()
    elif make == "not utf-8":
        path.write_bytes(b"\xff\xfe{")
    elif make == "not json":
        path.write_text(f"{{{MARKER}")
    assert main(["adapt", "--source", "all"]) == 0
    out, err = capsys.readouterr()
    assert memory_chain.events == []
    reason = {
        "missing": "no feed file",
        "a directory": "feed unreadable (IsADirectoryError)",
        "not utf-8": "feed unreadable (UnicodeDecodeError)",
        "not json": "feed is not JSON",
    }[make]
    assert f"portfolio-scan: 0 events appended (feed skipped: {reason})" in out
    assert MARKER not in out + err


def test_a_chain_error_fails_the_adapt(capsys, memory_chain, other_sources, monkeypatch):
    def refuse(params, event):
        raise db.ChainError("append failed (OperationalError)")

    monkeypatch.setattr(db, "append_event", refuse)
    _write(_feed())
    assert main(["adapt", "--source", "all"]) == 1
    out, err = capsys.readouterr()
    assert "ADAPT FAIL (portfolio-scan): append failed" in err
    # The other two ran first, and still reported.
    assert out.splitlines()[:2] == [
        "high-power: 0 events appended",
        "change-manager: 0 events appended",
    ]


def test_an_envelope_error_is_a_failure_not_a_bad_feed(
    capsys, memory_chain, other_sources, monkeypatch
):
    monkeypatch.setattr(portfolio_scan, "ACTOR", "an-id-nobody-registered")
    _write(_feed())
    assert main(["adapt", "--source", "all"]) == 1
    _out, err = capsys.readouterr()
    assert "ADAPT FAIL (portfolio-scan)" in err
    assert memory_chain.events == []


def test_portfolio_scan_runs_last_in_all(capsys, memory_chain, other_sources):
    _write(_feed())
    assert main(["adapt", "--source", "all"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "high-power: 0 events appended",
        "change-manager: 0 events appended",
        "portfolio-scan: 1 events appended",
    ]


def test_portfolio_scan_alone_via_cli(capsys, memory_chain):
    _write(_feed())
    assert main(["adapt", "--source", "portfolio-scan"]) == 0
    assert capsys.readouterr().out == "portfolio-scan: 1 events appended\n"
