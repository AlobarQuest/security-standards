"""The Mac's conformance inputs -> one `mac_conformance.reported` event per infra-drift report
(ADR-0059 Amendment 13, decision items 2, 3 and 5). Every input here is under tmp_path; the
chain is MemoryChain."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from factory_events import db, envelope
from factory_events.adapters import change_manager, high_power, mac_conformance
from factory_events.cli import main

GENERATED_AT = "2026-11-18T08:00:39Z"
PREVIOUS_AT = "2026-11-17T08:00:41Z"
RUN_AT = datetime(2026, 11, 18, 8, 30, 5, 123456, tzinfo=UTC)
MARKER = "zz-marker"
UUID_A = "00000000-0000-4000-8000-00000000000a"
UUID_B = "00000000-0000-4000-8000-00000000000b"
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """The state directory and the three inputs under tmp_path (conftest already keeps the real
    ones out of reach; this names the ones each test writes)."""
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    monkeypatch.setenv(mac_conformance.REPORT_DIR_ENV, str(tmp_path / "reports"))
    monkeypatch.setenv(mac_conformance.LAUNCHAGENTS_ENV, str(tmp_path / "LaunchAgents"))
    monkeypatch.setenv(mac_conformance.SETTINGS_ENV, str(tmp_path / "settings.json"))
    yield tmp_path


@pytest.fixture
def other_sources(tmp_path, monkeypatch):
    """`--source all` also runs the other adapters: an empty high-power log and an empty
    change-manager page; conftest already points the portfolio feed at an absent file."""
    monkeypatch.setattr(high_power, "DEFAULT_SOURCE", tmp_path / "no-high-power.jsonl")
    monkeypatch.setenv("CM_BASE_URL", "https://change-manager.invalid")
    monkeypatch.setenv("CM_M2M_TOKEN", "placeholder")
    monkeypatch.setattr(change_manager, "_http_fetch", lambda after_id, limit: [])


def _reports() -> Path:
    """Read from the environment and not through report_dir(), so a broken report_dir() can never
    make a test write the real reports."""
    path = Path(os.environ[mac_conformance.REPORT_DIR_ENV])
    path.mkdir(exist_ok=True)
    return path


def _proposal(uuid: str, name: str, pid: str) -> dict:
    """A proposal as infra-drift writes it, every free-text field carrying MARKER."""
    return {
        "id": pid,
        "kind": "remediation",
        "source": f"standards {MARKER}",
        "status": "open",
        "target": {
            "provider": "coolify",
            "resource_type": "application",
            "uuid": uuid,
            "name": name,
        },
        "description": f"description {MARKER}",
        "reasoning": f"reasoning {MARKER}",
        "question": f"question {MARKER}",
        "confidence": "high",
        "risk": "safe",
        "planned_action": {"tool": f"coolify_update {MARKER}", "args": {"note": MARKER}},
    }


def _instance(ok: bool = True, proposals: list | None = None) -> dict:
    return {
        "ok": ok,
        "standards_source": f"infra-brain {MARKER}",
        "summary": {"total_proposals": len(proposals or [])},
        "proposals": proposals or [],
        "errors": [f"error {MARKER}"],
    }


def _report(**overrides) -> dict:
    report = {
        "generated_at": GENERATED_AT,
        "instances": {
            "prod": _instance(proposals=[_proposal(UUID_A, "app-a", "drift-1")]),
            "dev": _instance(proposals=[_proposal(UUID_B, "app-b", "drift-2")]),
        },
        "totals": {"total_proposals": 2},
        "delta": {"new": [f"new {MARKER}"], "resolved": [], "unchanged": 0},
    }
    report.update(overrides)
    return report


def _write(report: object, name: str = "2026-11-18.json") -> Path:
    path = _reports() / name
    path.write_text(json.dumps(report, indent=2) + "\n")
    return path


def _wire(*, agents: tuple[str, ...] = (), hooks: tuple[str, ...] = ()) -> None:
    directory = Path(os.environ[mac_conformance.LAUNCHAGENTS_ENV])
    directory.mkdir(exist_ok=True)
    for label in agents:
        (directory / f"{label}.plist").write_text("<plist/>")
    settings = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {"type": "command", "command": f"bash ~/.claude/hooks/{h} --x"}
                        for h in hooks
                    ]
                }
            ]
        },
        "env": {"NOTE": MARKER},
    }
    Path(os.environ[mac_conformance.SETTINGS_ENV]).write_text(json.dumps(settings))


def _wiring(present: set[str]) -> list[dict]:
    return [
        {"type": "wiring", "executor": e, "status": "present" if e in present else "absent"}
        for e in mac_conformance.WIRING
    ]


def test_a_report_gives_one_event_of_ids_and_statuses_and_a_rerun_appends_nothing(memory_chain):
    _write(_report())
    _wire(agents=("com.devon.security-scan",), hooks=("bws-scan-gate.sh",))
    assert mac_conformance.adapt(RUN_AT) == 1
    (event,) = memory_chain.events
    assert event == {
        "schema": "factory-event/v1",
        "event_id": envelope.deterministic_event_id("mac-conformance-facts", GENERATED_AT),
        "timestamp": GENERATED_AT,
        "actor": "mac-conformance-facts",
        "action": "mac_conformance.reported",
        "target": None,
        "work_package": None,
        "input_revision": None,
        "result": "success",
        "evidence": [
            {"type": "infra-drift-report", "generated_at": GENERATED_AT},
            {"type": "infra-drift-instance", "name": "prod", "ok": True},
            {"type": "infra-drift-instance", "name": "dev", "ok": True},
            {
                "type": "infra-drift-proposal",
                "instance": "prod",
                "id": "drift-1",
                "target": {"uuid": UUID_A, "name": "app-a"},
            },
            {
                "type": "infra-drift-proposal",
                "instance": "dev",
                "id": "drift-2",
                "target": {"uuid": UUID_B, "name": "app-b"},
            },
            *_wiring({"launchagent:com.devon.security-scan", "hook:bws-scan-gate.sh"}),
        ],
        "authority_grant": None,
        "correlation_id": None,
        "source": {"system": "mac-conformance-facts", "ref": GENERATED_AT},
    }
    envelope.validate_event(event)

    # Same inputs twice append one event; so does a rerun whose wiring changed (one per report).
    assert mac_conformance.adapt(RUN_AT) == 0
    _wire(agents=("com.devon.change-window",))
    assert mac_conformance.adapt(RUN_AT) == 0
    assert len(memory_chain.events) == 1


def test_the_event_carries_no_free_text_from_the_report_or_the_settings(memory_chain, capsys):
    """Every free-text field the report and settings carry holds MARKER; none reaches the event
    or the output, and each evidence item holds only its layout's id and status keys."""
    _write(_report())
    _wire(agents=("com.devon.factory-events",), hooks=("bws-scan-gate.sh",))
    assert main(["adapt", "--source", "mac-conformance-facts"]) == 0
    out, err = capsys.readouterr()
    (event,) = memory_chain.events
    assert MARKER not in json.dumps(event) + out + err
    layout = {
        "infra-drift-report": {"type", "generated_at"},
        "infra-drift-instance": {"type", "name", "ok"},
        "infra-drift-proposal": {"type", "instance", "id", "target"},
        "wiring": {"type", "executor", "status"},
    }
    for item in event["evidence"]:
        assert set(item) == layout[item["type"]]
        if item["type"] == "infra-drift-proposal":
            assert set(item["target"]) == {"uuid", "name"}
    # No path: nothing under tmp_path, and no settings or plist path, is named.
    assert str(Path(os.environ[mac_conformance.REPORT_DIR_ENV]).parent) not in json.dumps(event)
    assert ".plist" not in json.dumps(event) and ".claude" not in json.dumps(event)


def test_a_new_report_appends_a_new_event_at_its_own_time(memory_chain):
    _write(_report(generated_at=PREVIOUS_AT), "2026-11-17.json")
    mac_conformance.adapt(RUN_AT)
    _write(_report())
    mac_conformance.adapt(RUN_AT)
    assert [e["timestamp"] for e in memory_chain.events] == [PREVIOUS_AT, GENERATED_AT]


def test_the_newest_report_is_picked_by_name_and_siblings_are_ignored(memory_chain):
    _write(_report(generated_at=PREVIOUS_AT), "2026-11-17.json")
    _write(_report(), "2026-11-18.json")
    _write(
        {"schema_version": 1, "generated_at": "2026-11-19T00:00:00Z"}, "2026-11-18.remediation.json"
    )
    (_reports() / "2026-11-19.md").write_text(MARKER)
    (_reports() / "2026-11-20.json").mkdir()  # not a file: never picked
    assert mac_conformance.adapt(RUN_AT) == 1
    assert memory_chain.events[0]["timestamp"] == GENERATED_AT


@pytest.mark.parametrize(
    ("raw", "written"),
    [
        ("2026-11-18T08:00:39+00:00", "2026-11-18T08:00:39Z"),
        ("2026-11-18T03:00:39-05:00", "2026-11-18T08:00:39Z"),
        ("2026-11-18T08:00:39.5Z", "2026-11-18T08:00:39.500000Z"),
    ],
)
def test_generated_at_is_written_in_the_envelopes_utc_form(raw, written, memory_chain):
    _write(_report(generated_at=raw))
    assert mac_conformance.adapt(RUN_AT) == 1
    (event,) = memory_chain.events
    assert event["timestamp"] == event["source"]["ref"] == written
    assert event["evidence"][0] == {"type": "infra-drift-report", "generated_at": written}


def test_a_naive_generated_at_is_system_local_as_the_matrix_reads_it(memory_chain):
    naive = "2026-11-18T03:00:39"
    _write(_report(generated_at=naive))
    mac_conformance.adapt(RUN_AT)
    expected = datetime.fromisoformat(naive).astimezone().astimezone(UTC)
    assert memory_chain.events[0]["timestamp"] == expected.strftime("%Y-%m-%dT%H:%M:%SZ")


# Each instance the matrix calls unusable (`checkers._infra_instance_unusable`) is ok: false,
# and the event's result is unknown.
UNUSABLE = {
    "ok false": _instance(ok=False),
    "ok missing": {"proposals": []},
    "not an object": [MARKER],
    "proposals not a list": {"ok": True, "proposals": {"id": MARKER}},
}


@pytest.mark.parametrize("instance", UNUSABLE.values(), ids=UNUSABLE.keys())
def test_an_unusable_instance_reads_not_ok_and_unknown(instance, memory_chain):
    _write(_report(instances={"prod": _instance(), "dev": instance}))
    assert mac_conformance.adapt(RUN_AT) == 1
    (event,) = memory_chain.events
    assert event["result"] == "unknown"
    assert {"type": "infra-drift-instance", "name": "dev", "ok": False} in event["evidence"]
    assert MARKER not in json.dumps(event)


def test_odd_proposals_keep_strings_only(memory_chain):
    proposals = [
        MARKER,
        {"id": 7, "target": None},
        {"id": "drift-3", "target": {"uuid": {"x": MARKER}, "name": ["x"]}},
    ]
    _write(_report(instances={"prod": _instance(proposals=proposals)}))
    mac_conformance.adapt(RUN_AT)
    items = [e for e in memory_chain.events[0]["evidence"] if e["type"] == "infra-drift-proposal"]
    assert items == [
        {
            "type": "infra-drift-proposal",
            "instance": "prod",
            "id": None,
            "target": {"uuid": None, "name": None},
        },
        {
            "type": "infra-drift-proposal",
            "instance": "prod",
            "id": "drift-3",
            "target": {"uuid": None, "name": None},
        },
    ]


# Each newest report the matrix calls "infra report unreadable" (`checkers.check_infra`).
# Where the bad part is a string, it carries MARKER, which neither the event nor the output echoes.
UNREADABLE = {
    "not an object": ([MARKER], "report is not an object with generated_at and instances"),
    "no generated_at": (
        {"instances": {}},
        "report is not an object with generated_at and instances",
    ),
    "no instances": (
        {"generated_at": GENERATED_AT},
        "report is not an object with generated_at and instances",
    ),
    "instances not an object": (_report(instances=[MARKER]), "instances is not an object"),
    "generated_at not a time": (
        _report(generated_at=f"yesterday {MARKER}"),
        "generated_at is not an ISO time",
    ),
    "generated_at null": (_report(generated_at=None), "generated_at is not an ISO time"),
}


def _unreadable_file(make: str) -> Path:
    path = _reports() / "2026-11-18.json"
    if make == "a directory":
        # A directory isn't a candidate, so the older report is newest; use a mode-000 file.
        path.write_text(json.dumps(_report()))
        path.chmod(0)
    elif make == "not utf-8":
        path.write_bytes(b"\xff\xfe{")
    elif make == "not json":
        path.write_text(f"{{{MARKER}")
    elif make == "nested too deeply":
        path.write_text("[" * 100_000)
    else:
        path.write_text(json.dumps(UNREADABLE[make][0]))
    return path


def _assert_unreadable_record(event: dict, reasons: list[str]) -> None:
    """The run time is the CLI's clock here, so the check is the one the reader needs: later than
    the previous day's event."""
    ref = "unreadable:2026-11-18.json"
    assert event["event_id"] == envelope.deterministic_event_id("mac-conformance-facts", ref)
    assert event["source"] == {"system": "mac-conformance-facts", "ref": ref}
    assert event["timestamp"] > PREVIOUS_AT
    assert event["result"] == "unknown"
    (record, *wiring) = event["evidence"]
    assert record["type"] == "infra-drift-report-unreadable"
    assert record["reason"] in reasons
    assert "generated_at" not in record
    assert wiring == _wiring(set())
    envelope.validate_event(event)


FILE_FAULTS = {
    "not readable": ["report unreadable (PermissionError)"],
    "not utf-8": ["report unreadable (UnicodeDecodeError)"],
    "not json": ["report is not JSON"],
    # Deep nesting surfaces as RecursionError or JSONDecodeError depending on the stack.
    "nested too deeply": ["report is nested too deeply to parse", "report is not JSON"],
}


@pytest.mark.parametrize("make", [*UNREADABLE, *FILE_FAULTS], ids=[*UNREADABLE, *FILE_FAULTS])
def test_an_unreadable_newest_report_is_recorded_not_skipped(
    make, capsys, memory_chain, other_sources
):
    _write(_report(generated_at=PREVIOUS_AT), "2026-11-17.json")
    assert mac_conformance.adapt(RUN_AT) == 1
    _unreadable_file("a directory" if make == "not readable" else make)
    try:
        assert main(["adapt", "--source", "all"]) == 0
    finally:
        (_reports() / "2026-11-18.json").chmod(0o600)
    out, err = capsys.readouterr()
    _previous, record = memory_chain.events
    reasons = FILE_FAULTS.get(make) or [UNREADABLE[make][1]]
    _assert_unreadable_record(record, reasons)
    assert "mac-conformance-facts: 1 events appended" in out.splitlines()
    assert "ADAPT FAIL" not in err
    assert MARKER not in out + err + json.dumps(record)


def test_an_unreadable_record_is_newer_than_the_previous_days_event(memory_chain):
    """Decision item 3: the reader takes the newest event by timestamp, so the unreadable record
    must sort after the previous day's usable event, even when that report was written late."""
    late = "2026-11-18T07:59:59Z"  # the previous file, generated late in its day
    _write(_report(generated_at=late), "2026-11-17.json")
    mac_conformance.adapt(RUN_AT)
    _unreadable_file("not json")
    mac_conformance.adapt(RUN_AT)
    previous, record = memory_chain.events
    assert record["timestamp"] == "2026-11-18T08:30:05Z"  # RUN_AT, whole seconds
    assert previous["result"] == "success"
    assert record["result"] == "unknown"
    newest = max(memory_chain.events, key=lambda e: e["timestamp"])
    assert newest is record
    assert record["timestamp"] > previous["timestamp"]

    # A rerun of the same unreadable report appends nothing, whatever the run time.
    assert mac_conformance.adapt(datetime(2026, 11, 18, 9, 0, tzinfo=UTC)) == 0
    assert len(memory_chain.events) == 2


def test_the_run_time_defaults_to_now(memory_chain):
    _unreadable_file("not json")
    before = datetime.now(UTC).replace(microsecond=0)
    mac_conformance.adapt()
    stamp = datetime.strptime(memory_chain.events[0]["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
    assert stamp.replace(tzinfo=UTC) >= before


@pytest.mark.parametrize("make", ["no directory", "empty directory", "only siblings"])
def test_no_report_appends_nothing_and_leaves_the_exit_alone(
    make, capsys, memory_chain, other_sources
):
    if make != "no directory":
        _reports()
    if make == "only siblings":
        _write(_report(), "2026-11-18.remediation.json")
    assert main(["adapt", "--source", "all"]) == 0
    out, err = capsys.readouterr()
    assert memory_chain.events == []
    reason = (
        "no infra-drift report directory" if make == "no directory" else "no infra-drift report"
    )
    assert f"mac-conformance-facts: 0 events appended (report skipped: {reason})" in out
    assert "ADAPT FAIL" not in err


def test_an_unlistable_report_directory_appends_nothing(capsys, memory_chain, other_sources):
    directory = _reports()
    directory.chmod(0)
    try:
        assert main(["adapt", "--source", "all"]) == 0
    finally:
        directory.chmod(0o700)
    out, _err = capsys.readouterr()
    assert memory_chain.events == []
    assert "report skipped: report directory unreadable (PermissionError)" in out


# Settings the matrix reads as "not registered" (`wiring._verify_hook`); each is absent here too.
BAD_SETTINGS = {
    "missing": None,
    "not json": f"{{{MARKER}",
    "not utf-8": b"\xff\xfe",
    "not an object": json.dumps([MARKER]),
    "hooks a list": json.dumps({"hooks": [MARKER]}),
    "entries not lists": json.dumps({"hooks": {"Stop": {"hooks": MARKER}}}),
    "inner not a list": json.dumps({"hooks": {"Stop": [{"hooks": MARKER}]}}),
    "command not a string": json.dumps({"hooks": {"Stop": [{"hooks": [{"command": 7}]}]}}),
    "only a substring": json.dumps(
        {"hooks": {"Stop": [{"hooks": [{"command": "~/x/not-bws-scan-gate.sh"}]}]}}
    ),
    "nested too deeply": "[" * 100_000,
}


@pytest.mark.parametrize("settings", BAD_SETTINGS.values(), ids=BAD_SETTINGS.keys())
def test_unreadable_or_odd_settings_read_absent_without_failing(settings, memory_chain, capsys):
    _write(_report())
    path = Path(os.environ[mac_conformance.SETTINGS_ENV])
    if isinstance(settings, bytes):
        path.write_bytes(settings)
    elif settings is not None:
        path.write_text(settings)
    assert main(["adapt", "--source", "mac-conformance-facts"]) == 0
    (event,) = memory_chain.events
    assert [e for e in event["evidence"] if e["type"] == "wiring"] == _wiring(set())
    assert MARKER not in json.dumps(event) + capsys.readouterr().out


def test_a_hook_is_present_by_any_token_basename(memory_chain):
    _write(_report())
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "x",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/bin/bash /Users/x/.claude/hooks/bws-scan-gate.sh",
                        }
                    ],
                }
            ]
        }
    }
    Path(os.environ[mac_conformance.SETTINGS_ENV]).write_text(json.dumps(settings))
    mac_conformance.adapt(RUN_AT)
    assert {"type": "wiring", "executor": "hook:bws-scan-gate.sh", "status": "present"} in (
        memory_chain.events[0]["evidence"]
    )


def test_a_launchagent_is_present_only_as_a_plist_file(memory_chain):
    _write(_report())
    _wire(agents=("com.devon.change-window", "com.devon.vps-backup"))
    (Path(os.environ[mac_conformance.LAUNCHAGENTS_ENV]) / "com.devon.factory-events.plist").mkdir()
    mac_conformance.adapt(RUN_AT)
    wiring = [e for e in memory_chain.events[0]["evidence"] if e["type"] == "wiring"]
    assert wiring == _wiring({"launchagent:com.devon.change-window"})


# The wiring bounds (Amendment 13 verify items). Each member's `launchagent:` and `hook:`
# required_checks executors, read from PROJECT.md at its `main` on 2026-11-18 for the 13
# repositories of orchestrator `docs/operations/membership-seed.toml`. Members not listed declare
# none (brain, orchestrator, infraops-mcp-server, intent-packages, factory-runner) or have no
# PROJECT.md (rtk, claude-octopus, rea, n8n-as-code, n8n-manager).
MEMBER_DECLARATIONS = {
    "alobarquest/change-manager": {"launchagent:com.devon.change-window"},  # 89f87345
    "alobarquest/project-standards": {"launchagent:com.devon.portfolio-scan"},  # 4673d726
    "alobarquest/security-standards": {  # 23854235
        "hook:bws-scan-gate.sh",
        "launchagent:com.devon.security-scan",
        "launchagent:com.devon.factory-events",
    },
}


def test_the_wiring_set_holds_every_declared_entry_and_nothing_else():
    declared = set().union(*MEMBER_DECLARATIONS.values())
    assert len(declared) == 5
    assert set(mac_conformance.WIRING) == declared
    assert len(mac_conformance.WIRING) == len(set(mac_conformance.WIRING))


def test_this_repositorys_own_declarations_are_in_the_set():
    """The one member whose declarations this repository holds: a live check of the lower bound,
    and of the recorded row above."""
    text = (REPO_ROOT / "PROJECT.md").read_text()
    front = yaml.safe_load(text.split("---")[1])
    mine = {
        entry["executor"]
        for entry in front["required_checks"]
        if entry["executor"].split(":")[0] in ("launchagent", "hook")
    }
    assert mine == MEMBER_DECLARATIONS["alobarquest/security-standards"]
    assert mine <= set(mac_conformance.WIRING)


def test_the_defaults_are_project_standards_paths(tmp_path, monkeypatch):
    for name in (
        mac_conformance.REPORT_DIR_ENV,
        mac_conformance.LAUNCHAGENTS_ENV,
        mac_conformance.SETTINGS_ENV,
    ):
        monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert mac_conformance.report_dir() == tmp_path / "infra-drift" / "reports"
    assert mac_conformance.launchagents_dir() == tmp_path / "Library" / "LaunchAgents"
    assert mac_conformance.settings_path() == tmp_path / ".claude" / "settings.json"


def test_a_chain_error_fails_the_adapt_and_the_others_still_run(
    capsys, memory_chain, other_sources, monkeypatch
):
    def refuse(params, event):
        raise db.ChainError("append failed (OperationalError)")

    monkeypatch.setattr(db, "append_event", refuse)
    _write(_report())
    assert main(["adapt", "--source", "all"]) == 1
    out, err = capsys.readouterr()
    assert "ADAPT FAIL (mac-conformance-facts): append failed" in err
    assert out.splitlines() == [
        "high-power: 0 events appended",
        "change-manager: 0 events appended",
        "portfolio-scan: 0 events appended (feed skipped: no feed file)",
    ]


def test_an_envelope_error_is_a_failure_not_a_skip(
    capsys, memory_chain, other_sources, monkeypatch
):
    monkeypatch.setattr(mac_conformance, "ACTOR", "an-id-nobody-registered")
    _write(_report())
    assert main(["adapt", "--source", "all"]) == 1
    _out, err = capsys.readouterr()
    assert "ADAPT FAIL (mac-conformance-facts)" in err
    assert memory_chain.events == []


def test_the_step_runs_before_portfolio_scan_in_all(capsys, memory_chain, other_sources):
    _write(_report())
    assert main(["adapt", "--source", "all"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "high-power: 0 events appended",
        "change-manager: 0 events appended",
        "mac-conformance-facts: 1 events appended",
        "portfolio-scan: 0 events appended (feed skipped: no feed file)",
    ]
