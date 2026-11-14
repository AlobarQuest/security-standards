"""Which chain emit, adapt and verify use, without a database: the file chain stays as it was,
a configured database fails closed by name, a password never reaches output, and emit's stdout
stays within intent-packages' parse contract."""

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
SETTINGS = {chain.DB_HOST_VAR: "127.0.0.1", chain.DB_NAME_VAR: "factory_events"}
# Nothing listens on port 1, so the connection is refused at once.
UNREACHABLE = {**SETTINGS, chain.DB_PORT_VAR: "1"}
MALFORMED = {**SETTINGS, chain.DB_PORT_VAR: "notaport"}
APPEND = {chain.APPEND_PASSWORD_VAR: SENTINEL, **UNREACHABLE}
READ = {chain.READ_PASSWORD_VAR: SENTINEL, **UNREACHABLE}
EMIT_ARGS = ["emit", "--actor", "devon", "--action", "test.ping", "--result", "success"]
EMIT_ARGS += ["--ref", "test"]


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def _setenv(monkeypatch, env: dict[str, str]) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)


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


# --- the connection builder ------------------------------------------------------------


def test_builder_returns_keyword_parameters_for_the_role(monkeypatch):
    _setenv(monkeypatch, {**APPEND, chain.READ_PASSWORD_VAR: "other-pw"})
    append = chain.connection_params(chain.APPEND_ROLE)
    assert append.as_kwargs() == {
        "host": "127.0.0.1",
        "port": "1",
        "dbname": "factory_events",
        "user": "factory_events_append",
        "password": SENTINEL,
    }
    read = chain.connection_params(chain.READ_ROLE)
    assert (read.user, read.password) == ("factory_events_read", "other-pw")
    assert SENTINEL not in repr(append) and SENTINEL not in str(append)


def test_role_names_match_the_schema():
    schema = (REPO / "src" / "factory_events" / "chain_schema.sql").read_text()
    for role in (chain.APPEND_ROLE, chain.READ_ROLE):
        assert f"CREATE ROLE {role}" in schema


@pytest.mark.parametrize(
    "missing",
    [chain.APPEND_PASSWORD_VAR, chain.DB_HOST_VAR, chain.DB_PORT_VAR, chain.DB_NAME_VAR],
)
@pytest.mark.parametrize("empty", [False, True], ids=["unset", "empty"])
def test_each_missing_setting_refuses_by_name(monkeypatch, capsys, missing, empty):
    env = {**APPEND, chain.READ_PASSWORD_VAR: SENTINEL}
    if empty:
        env[missing] = ""
    else:
        del env[missing]
    _setenv(monkeypatch, env)
    with pytest.raises(db.ChainError) as info:
        chain.connection_params(chain.APPEND_ROLE)
    assert str(info.value) == f"{missing} is not set"
    assert main(EMIT_ARGS) == 1
    captured = capsys.readouterr()
    assert f"emit failed: {missing} is not set" in captured.err
    assert SENTINEL not in captured.out + captured.err
    assert not store.events_path().exists()


@pytest.mark.parametrize("retired", chain.RETIRED_VARS)
@pytest.mark.parametrize(
    "args",
    [EMIT_ARGS, ["verify"], ["ship"], ["adapt", "--source", "high-power"]],
    ids=["emit", "verify", "ship", "adapt"],
)
def test_a_set_retired_variable_refuses_every_command(monkeypatch, capsys, retired, args):
    """No password is set, so ignoring the retired variable would drop to the file chain."""
    leaked = f"postgresql://factory_events_append:{SENTINEL}@127.0.0.1:1/factory_events"
    monkeypatch.setenv(retired, leaked)
    assert main(args) == 1
    captured = capsys.readouterr()
    assert f"{retired} is retired" in captured.err
    assert SENTINEL not in captured.out + captured.err
    assert not store.events_path().exists()


def test_a_retired_variable_refuses_beside_a_password(monkeypatch, tmp_path, capsys):
    _setenv(monkeypatch, {**APPEND, "FACTORY_EVENTS_IMPORT_DSN": SENTINEL})
    assert main(["import-file", "--path", str(tmp_path / "events.jsonl")]) == 1
    err = capsys.readouterr().err
    assert "FACTORY_EVENTS_IMPORT_DSN is retired" in err and SENTINEL not in err


# --- mode selection --------------------------------------------------------------------


def test_settings_without_a_password_stay_on_the_file_chain(monkeypatch):
    _setenv(monkeypatch, UNREACHABLE)
    assert chain.database_mode() is False and chain.verify_params() is None
    assert main(EMIT_ARGS) == 0
    assert len(list(store.iter_records())) == 1


@pytest.mark.parametrize(
    ("env", "role"),
    [(READ, chain.READ_ROLE), (APPEND, chain.APPEND_ROLE), ({**APPEND, **READ}, chain.READ_ROLE)],
    ids=["read-only", "append-only", "both"],
)
def test_verify_reads_under_the_read_password_else_the_append(monkeypatch, env, role):
    _setenv(monkeypatch, env)
    params = chain.verify_params()
    assert params is not None and params.user == role


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


def test_read_password_alone_refuses_emit_and_writes_no_file(monkeypatch, capsys):
    _setenv(monkeypatch, READ)
    assert main(EMIT_ARGS) == 1
    err = capsys.readouterr().err
    assert "emit failed: FACTORY_EVENTS_APPEND_PASSWORD is not set" in err and SENTINEL not in err
    assert not store.events_path().exists()


def test_read_password_alone_refuses_adapt(tmp_path, monkeypatch, capsys):
    source = tmp_path / "hp.jsonl"
    source.write_text(
        json.dumps({"tool": "Bash", "timestamp": "2026-07-03T01:00:00Z", "args_summary": "{}"})
        + "\n"
    )
    from factory_events.adapters import high_power

    monkeypatch.setattr(high_power, "DEFAULT_SOURCE", source)
    _setenv(monkeypatch, READ)
    assert main(["adapt", "--source", "high-power"]) == 1
    assert "ADAPT FAIL (high-power)" in capsys.readouterr().err
    assert not store.events_path().exists()


@pytest.mark.parametrize("settings", [UNREACHABLE, MALFORMED], ids=["unreachable", "malformed"])
def test_emit_failure_writes_nothing_and_never_prints_the_password(tmp_path, settings):
    proc = _run_cli(EMIT_ARGS, {chain.APPEND_PASSWORD_VAR: SENTINEL, **settings}, tmp_path)
    assert proc.returncode == 1
    assert "emit failed: append failed" in proc.stderr
    assert SENTINEL not in proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr
    assert not (tmp_path / "events.jsonl").exists()
    record = json.loads(proc.stdout.splitlines()[0])
    assert record["op"] == "append" and record["outcome"] == "failure"


@pytest.mark.parametrize("settings", [UNREACHABLE, MALFORMED], ids=["unreachable", "malformed"])
def test_verify_failure_never_prints_the_password(tmp_path, settings):
    env = {chain.READ_PASSWORD_VAR: SENTINEL, **settings}
    proc = _run_cli(["verify", "--against-anchor"], env, tmp_path)
    assert proc.returncode == 1
    assert "VERIFY FAIL: verify failed" in proc.stderr
    assert SENTINEL not in proc.stdout + proc.stderr


def test_import_failure_never_prints_the_password(tmp_path):
    store.append_event(_event())
    args = ["import-file", "--path", str(tmp_path / "events.jsonl")]
    proc = _run_cli(args, APPEND, tmp_path)
    assert proc.returncode == 1
    assert "IMPORT FAIL: import failed" in proc.stderr
    assert SENTINEL not in proc.stdout + proc.stderr


def test_import_needs_the_append_password(tmp_path, monkeypatch, capsys):
    _setenv(monkeypatch, READ)
    assert main(["import-file", "--path", str(tmp_path / "events.jsonl")]) == 1
    err = capsys.readouterr().err
    assert "IMPORT FAIL: FACTORY_EVENTS_APPEND_PASSWORD is not set" in err
    assert SENTINEL not in err


def test_database_verify_rejects_file_only_flag(monkeypatch, capsys):
    _setenv(monkeypatch, READ)
    assert main(["verify", "--tolerate-torn-tail"]) == 1
    assert "file chain only" in capsys.readouterr().err


def test_file_verify_rejects_record_anchor(capsys):
    assert main(["verify", "--record-anchor"]) == 1
    assert "needs the database chain" in capsys.readouterr().err


def test_emit_stdout_parses_when_json_logs_share_stdout(monkeypatch, capsys):
    """Database mode logs JSON records to stdout before the bare id; both parse rules must
    yield the emitted id. A fake append stands in for the database here; the integration
    suite runs the same check against a real one."""

    def fake_append(params, event):
        jsonlog.log("append", "ok", event_id=event["event_id"], seq=7, head="abc123")
        return {"seq": 7, "prev_hash": store.GENESIS, "hash": "a" * 64, "event": event}

    monkeypatch.setattr(db, "append_event", fake_append)
    _setenv(monkeypatch, APPEND)
    assert main(EMIT_ARGS) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert json.loads(lines[0])["event_id"] == lines[-1]
    assert parse_event_id(out) == lines[-1]
    # The last-token fallback also yields it, should the JSON line ever be dropped.
    assert parse_event_id(lines[-1]) == lines[-1]
    assert not store.events_path().exists()


def test_corrupt_anchor_fails_verify_cleanly(monkeypatch, capsys):
    chain.anchor_path().parent.mkdir(parents=True)
    chain.anchor_path().write_text('{"seq": 3')
    _setenv(monkeypatch, READ)
    assert main(["verify", "--against-anchor"]) == 1
    assert "VERIFY FAIL: the anchor at" in capsys.readouterr().err


def test_ship_refuses_in_database_mode(monkeypatch, capsys):
    _setenv(monkeypatch, APPEND)
    assert main(["ship"]) == 1
    assert "SHIP FAIL" in capsys.readouterr().err


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
