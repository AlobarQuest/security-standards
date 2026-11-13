"""Which chain emit, adapt and verify use, without a database: the file chain stays as it was,
a configured database fails closed, a DSN never reaches output, and emit's stdout stays within
intent-packages' parse contract."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from emitter_contract import parse_event_id

from factory_events import chain, db, jsonlog, store
from factory_events.cli import main

REPO = Path(__file__).resolve().parents[1]
SENTINEL = "sentinel-pw-7f3a9c"
# Nothing listens on port 1, so the connection is refused at once.
UNREACHABLE_DSN = f"postgresql://factory_events_append:{SENTINEL}@127.0.0.1:1/factory_events"
MALFORMED_DSN = f"postgresql://u:{SENTINEL}@127.0.0.1:notaport/x?bogus_option=1"
EMIT_ARGS = ["emit", "--actor", "devon", "--action", "test.ping", "--result", "success"]
EMIT_ARGS += ["--ref", "test"]


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def _run_cli(args: list[str], env_extra: dict[str, str], home: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("FACTORY_EVENTS_")}
    env.update(PYTHONPATH=str(REPO / "src"), FACTORY_EVENTS_HOME=str(home), **env_extra)
    return subprocess.run(
        [sys.executable, "-m", "factory_events", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_file_mode_emit_is_unchanged_and_never_loads_psycopg(tmp_path):
    probe = (
        "import sys; from factory_events.cli import main; rc = main(sys.argv[1:]); "
        "assert 'psycopg' not in sys.modules, 'psycopg loaded'; sys.exit(rc)"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("FACTORY_EVENTS_")}
    env.update(PYTHONPATH=str(REPO / "src"), FACTORY_EVENTS_HOME=str(tmp_path))
    proc = subprocess.run(
        [sys.executable, "-c", probe, *EMIT_ARGS], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0, proc.stderr
    # Today's stdout: the bare id, one line, nothing else.
    lines = proc.stdout.splitlines()
    assert len(lines) == 1 and lines[0].startswith("evt-")
    assert [r["event"]["event_id"] for r in store.iter_records()] == [lines[0]]
    assert parse_event_id(proc.stdout) == lines[0]


def test_read_dsn_alone_refuses_emit_and_writes_no_file(monkeypatch, capsys):
    monkeypatch.setenv(chain.READ_DSN_VAR, UNREACHABLE_DSN)
    assert main(EMIT_ARGS) == 1
    err = capsys.readouterr().err
    assert "FACTORY_EVENTS_APPEND_DSN" in err and SENTINEL not in err
    assert not store.events_path().exists()


def test_read_dsn_alone_refuses_adapt(tmp_path, monkeypatch, capsys):
    source = tmp_path / "hp.jsonl"
    source.write_text(
        json.dumps({"tool": "Bash", "timestamp": "2026-07-03T01:00:00Z", "args_summary": "{}"})
        + "\n"
    )
    from factory_events.adapters import high_power

    monkeypatch.setattr(high_power, "DEFAULT_SOURCE", source)
    monkeypatch.setenv(chain.READ_DSN_VAR, UNREACHABLE_DSN)
    assert main(["adapt", "--source", "high-power"]) == 1
    assert "ADAPT FAIL (high-power)" in capsys.readouterr().err
    assert not store.events_path().exists()


@pytest.mark.parametrize("dsn", [UNREACHABLE_DSN, MALFORMED_DSN])
def test_emit_failure_writes_nothing_and_never_prints_the_dsn(tmp_path, dsn):
    proc = _run_cli(EMIT_ARGS, {chain.APPEND_DSN_VAR: dsn}, tmp_path)
    assert proc.returncode == 1
    assert "emit failed: append failed" in proc.stderr
    assert SENTINEL not in proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr
    assert not (tmp_path / "events.jsonl").exists()
    record = json.loads(proc.stdout.splitlines()[0])
    assert record["op"] == "append" and record["outcome"] == "failure"


@pytest.mark.parametrize("dsn", [UNREACHABLE_DSN, MALFORMED_DSN])
def test_verify_failure_never_prints_the_dsn(tmp_path, dsn):
    proc = _run_cli(["verify", "--against-anchor"], {chain.READ_DSN_VAR: dsn}, tmp_path)
    assert proc.returncode == 1
    assert "VERIFY FAIL: verify failed" in proc.stderr
    assert SENTINEL not in proc.stdout + proc.stderr


def test_import_failure_never_prints_the_dsn(tmp_path):
    store.append_event(_event())
    args = ["import-file", "--path", str(tmp_path / "events.jsonl")]
    proc = _run_cli(args, {chain.IMPORT_DSN_VAR: UNREACHABLE_DSN}, tmp_path)
    assert proc.returncode == 1
    assert "IMPORT FAIL: import failed" in proc.stderr
    assert SENTINEL not in proc.stdout + proc.stderr


def test_import_never_falls_back_to_the_append_dsn(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(chain.APPEND_DSN_VAR, UNREACHABLE_DSN)
    assert main(["import-file", "--path", str(tmp_path / "events.jsonl")]) == 1
    assert "FACTORY_EVENTS_IMPORT_DSN is not set" in capsys.readouterr().err


def test_database_verify_rejects_file_only_flag(monkeypatch, capsys):
    monkeypatch.setenv(chain.READ_DSN_VAR, UNREACHABLE_DSN)
    assert main(["verify", "--tolerate-torn-tail"]) == 1
    assert "file chain only" in capsys.readouterr().err


def test_file_verify_rejects_record_anchor(capsys):
    assert main(["verify", "--record-anchor"]) == 1
    assert "needs the database chain" in capsys.readouterr().err


def test_emit_stdout_parses_when_json_logs_share_stdout(monkeypatch, capsys):
    """Database mode logs JSON records to stdout before the bare id; both parse rules must
    yield the emitted id. A fake append stands in for the database here; the integration
    suite runs the same check against a real one."""

    def fake_append(dsn, event):
        jsonlog.log("append", "ok", event_id=event["event_id"], seq=7, head="abc123")
        return {"seq": 7, "prev_hash": store.GENESIS, "hash": "a" * 64, "event": event}

    monkeypatch.setattr(db, "append_event", fake_append)
    monkeypatch.setenv(chain.APPEND_DSN_VAR, UNREACHABLE_DSN)
    assert main(EMIT_ARGS) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert json.loads(lines[0])["event_id"] == lines[-1]
    assert parse_event_id(out) == lines[-1]
    # The last-token fallback also yields it, should the JSON line ever be dropped.
    assert parse_event_id(lines[-1]) == lines[-1]
    assert not store.events_path().exists()


def test_anchor_round_trips(tmp_path):
    assert chain.read_anchor() is None
    chain.write_anchor((5, "b" * 64))
    assert chain.read_anchor() == (5, "b" * 64)
    assert chain.anchor_path() == tmp_path / "state" / "chain-anchor.json"


def _event() -> dict:
    from factory_events.envelope import make_event

    return make_event(
        actor="devon",
        action="test.ping",
        result="success",
        source={"system": "direct", "ref": "test"},
        timestamp="2026-07-02T00:00:00Z",
    )
