# WS-1.1 Audit-Event Envelope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One common audit-event envelope (`factory-event/v1`) with a hash-chained append-only JSONL store on the mini, watermarked adapters for `high-power-actions.jsonl` and change-manager `ChangeEvent`, and a nightly ship to a local Postgres projection with head-hash anchoring.

**Architecture:** New zero-runtime-surprise package `src/factory_events/` in security-standards (sibling of `security_scan`), plus one read-only paginated events endpoint in change-manager. JSONL is the source of record; the Postgres projection is disposable (`ship --rebuild` replays it). Spec: `docs/superpowers/specs/2026-07-02-ws11-audit-event-envelope-design.md` — read it first.

**Tech Stack:** Python 3.12+, `jsonschema` + `psycopg[binary]` via a new `events` optional-dependency group (installed into `.venv-events`; `psycopg` lazily imported so emit/adapt/verify don't need it), pytest, FastAPI/SQLAlchemy (change-manager side), postgres:16 in OrbStack host Docker, launchd.

## Global Constraints

- Python `>=3.12`; ruff `line-length = 100`, lint rules `E,F,I,UP,B,C90` (run `ruff check src tests` before each commit).
- Tests run as `PYTHONPATH=src python3 -m pytest tests/ -v` from the repo root (pyproject already sets `pythonpath = ["src"]`, so plain `pytest` works too).
- All `factory_events` filesystem access goes through `store.factory_home()`, which honors `FACTORY_EVENTS_HOME` (tests point it at `tmp_path`; production default `~/.factory`).
- NEVER write a secret value into a tracked file — the `bws-write-guard` PreToolUse hook denies BWS-token-shaped content, and the session-end scan gate blocks BLOCK findings. Secrets live in `~/.factory/env` (chmod 600, outside the repo) referenced by BWS UUID in `.bws-secrets.toml`.
- Canonical JSON everywhere = `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()`. Never vary this — chain hashes depend on it.
- Timestamps in envelopes are UTC `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` (Z-suffixed, never `+00:00`).
- Commit after every task (at minimum); message prefixes `feat:` / `test:` / `docs:` / `chore:`.
- change-manager work (Task 5) happens in `~/Projects/change-manager` on a branch, as its own PR — never merge it; Devon merges.

---

### Task 1: Package skeleton, JSON Schema, envelope module

**Files:**
- Create: `schema/factory-event.v1.schema.json`
- Create: `src/factory_events/__init__.py` (empty)
- Create: `src/factory_events/envelope.py`
- Modify: `pyproject.toml` (add `events` optional-dependency group)
- Test: `tests/test_factory_envelope.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `envelope.SCHEMA_VERSION: str`, `envelope.canonical_json(obj) -> bytes`, `envelope.deterministic_event_id(system: str, payload: str) -> str`, `envelope.new_event_id() -> str`, `envelope.validate_event(event: dict) -> None` (raises `envelope.EnvelopeError`), `envelope.make_event(...) -> dict` (signature in step 3). Every later task builds events with `make_event` and validates with `validate_event`.

- [ ] **Step 1: Add the `events` dependency group and create the venv**

In `pyproject.toml`, after the `[project.optional-dependencies]` `dev` line, extend the table to:

```toml
[project.optional-dependencies]
dev = ["pytest>=7.0", "jsonschema>=4.21"]
events = ["jsonschema>=4.21", "psycopg[binary]>=3.1"]
```

Run: `cd ~/Projects/security-standards && python3 -m venv .venv-events && .venv-events/bin/pip -q install -e '.[events,dev]'`
Expected: exits 0. Check `.gitignore` covers `.venv-events/` (add a line if not).

- [ ] **Step 2: Write the JSON Schema**

Create `schema/factory-event.v1.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/AlobarQuest/security-standards/schema/factory-event.v1.schema.json",
  "title": "factory-event/v1 — common audit-event envelope (WS-1.1, companion doc §3.5)",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "event_id", "timestamp", "actor", "action", "result", "evidence", "source"],
  "properties": {
    "schema": {"const": "factory-event/v1"},
    "event_id": {"type": "string", "pattern": "^evt-[0-9a-f]{32,64}$"},
    "timestamp": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d{1,6})?Z$"},
    "actor": {"type": "string", "minLength": 1},
    "action": {"type": "string", "pattern": "^[a-z0-9_]+\\.[a-z0-9_.\\-]+$"},
    "target": {"type": ["string", "null"]},
    "work_package": {"type": ["string", "null"]},
    "input_revision": {"type": ["string", "null"]},
    "result": {"enum": ["success", "failure", "unknown"]},
    "evidence": {"type": "array", "items": {"type": "object"}},
    "authority_grant": {"type": ["object", "string", "null"]},
    "correlation_id": {"type": ["string", "null"]},
    "source": {
      "type": "object",
      "additionalProperties": false,
      "required": ["system", "ref"],
      "properties": {
        "system": {"enum": ["high-power-audit", "change-manager", "direct"]},
        "ref": {"type": "string"}
      }
    }
  }
}
```

Note: `actor` is a free string on purpose — the provisional vocabulary is convention documented in the README (Task 9); WS-1.2's registry takes over validation later. Do not turn it into an enum.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_factory_envelope.py`:

```python
import pytest

from factory_events import envelope


def _valid_event() -> dict:
    return envelope.make_event(
        actor="claude-code-unattributed",
        action="tool.vps_exec",
        result="unknown",
        source={"system": "high-power-audit", "ref": "line:1"},
        timestamp="2026-07-02T23:33:35Z",
        correlation_id="3ca07069-0000-0000-0000-000000000000",
        evidence=[{"type": "source-record", "record": {"tool": "mcp__infraops__vps_exec"}}],
        event_id=envelope.deterministic_event_id("high-power-audit", "rawline"),
    )


def test_make_event_produces_valid_event():
    ev = _valid_event()
    envelope.validate_event(ev)  # must not raise
    assert ev["schema"] == "factory-event/v1"
    assert ev["work_package"] is None and ev["input_revision"] is None


def test_deterministic_event_id_is_stable_and_prefixed():
    a = envelope.deterministic_event_id("high-power-audit", "rawline")
    b = envelope.deterministic_event_id("high-power-audit", "rawline")
    c = envelope.deterministic_event_id("change-manager", "rawline")
    assert a == b and a != c and a.startswith("evt-") and len(a) == 4 + 64


def test_new_event_id_unique_and_valid_shape():
    a, b = envelope.new_event_id(), envelope.new_event_id()
    assert a != b and a.startswith("evt-")


def test_validate_rejects_bad_result():
    ev = _valid_event()
    ev["result"] = "ok"
    with pytest.raises(envelope.EnvelopeError):
        envelope.validate_event(ev)


def test_validate_rejects_unknown_field():
    ev = _valid_event()
    ev["extra"] = 1
    with pytest.raises(envelope.EnvelopeError):
        envelope.validate_event(ev)


def test_validate_rejects_non_z_timestamp():
    ev = _valid_event()
    ev["timestamp"] = "2026-07-02T23:33:35+00:00"
    with pytest.raises(envelope.EnvelopeError):
        envelope.validate_event(ev)


def test_canonical_json_sorted_and_compact():
    assert envelope.canonical_json({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv-events/bin/python -m pytest tests/test_factory_envelope.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory_events'`.

- [ ] **Step 5: Implement the envelope module**

Create empty `src/factory_events/__init__.py`, then `src/factory_events/envelope.py`:

```python
"""factory-event/v1 envelope: canonicalization, ids, validation.

The JSON Schema at schema/factory-event.v1.schema.json is the published
contract; this module is the runtime enforcement of it.
"""

import hashlib
import json
import uuid
from functools import cache
from pathlib import Path

import jsonschema

SCHEMA_VERSION = "factory-event/v1"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "factory-event.v1.schema.json"


class EnvelopeError(ValueError):
    """Event does not conform to factory-event/v1."""


def canonical_json(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def deterministic_event_id(system: str, payload: str) -> str:
    return "evt-" + hashlib.sha256(f"{system}:{payload}".encode()).hexdigest()


def new_event_id() -> str:
    return "evt-" + uuid.uuid4().hex


@cache
def _validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text())
    return jsonschema.Draft202012Validator(schema)


def validate_event(event: dict) -> None:
    errors = sorted(_validator().iter_errors(event), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.absolute_path) or "<root>"
        raise EnvelopeError(f"invalid factory-event at {where}: {first.message}")


def make_event(
    *,
    actor: str,
    action: str,
    result: str,
    source: dict,
    timestamp: str,
    target: str | None = None,
    work_package: str | None = None,
    input_revision: str | None = None,
    evidence: list[dict] | None = None,
    authority_grant: dict | str | None = None,
    correlation_id: str | None = None,
    event_id: str | None = None,
) -> dict:
    event = {
        "schema": SCHEMA_VERSION,
        "event_id": event_id or new_event_id(),
        "timestamp": timestamp,
        "actor": actor,
        "action": action,
        "target": target,
        "work_package": work_package,
        "input_revision": input_revision,
        "result": result,
        "evidence": evidence or [],
        "authority_grant": authority_grant,
        "correlation_id": correlation_id,
        "source": source,
    }
    validate_event(event)
    return event
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv-events/bin/python -m pytest tests/test_factory_envelope.py -v`
Expected: 7 passed. Also run `ruff check src/factory_events tests/test_factory_envelope.py` → clean.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml schema/ src/factory_events/ tests/test_factory_envelope.py .gitignore
git commit -m "feat: factory-event/v1 envelope schema + validation module (WS-1.1)"
```

---

### Task 2: Hash-chained JSONL store

**Files:**
- Create: `src/factory_events/store.py`
- Test: `tests/test_factory_store.py`

**Interfaces:**
- Consumes: `envelope.canonical_json`, `envelope.validate_event`, `envelope.make_event` (Task 1).
- Produces: `store.GENESIS: str` (64 zeros), `store.factory_home() -> Path`, `store.events_path() -> Path`, `store.state_dir() -> Path`, `store.append_event(event: dict) -> dict` (returns the stored line `{"seq", "prev_hash", "hash", "event"}`), `store.iter_records() -> Iterator[dict]`, `store.event_ids() -> set[str]`, `store.head() -> tuple[int, str] | None` (seq, hash), `store.verify_chain() -> list[str]` (empty list = valid). Tasks 3, 4, 6, 7 use exactly these names.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_factory_store.py`:

```python
import json

import pytest

from factory_events import envelope, store


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def _event(n: int) -> dict:
    return envelope.make_event(
        actor="devon",
        action="test.ping",
        result="success",
        source={"system": "direct", "ref": "test"},
        timestamp="2026-07-02T00:00:00Z",
        event_id=envelope.deterministic_event_id("direct", str(n)),
    )


def test_append_builds_genesis_then_chains(tmp_path):
    line1 = store.append_event(_event(1))
    line2 = store.append_event(_event(2))
    assert line1["seq"] == 1 and line1["prev_hash"] == store.GENESIS
    assert line2["seq"] == 2 and line2["prev_hash"] == line1["hash"]
    assert store.head() == (2, line2["hash"])


def test_append_rejects_invalid_event():
    with pytest.raises(envelope.EnvelopeError):
        store.append_event({"schema": "factory-event/v1"})


def test_event_ids_and_iter_records():
    store.append_event(_event(1))
    store.append_event(_event(2))
    ids = store.event_ids()
    assert len(ids) == 2
    assert [r["seq"] for r in store.iter_records()] == [1, 2]


def test_verify_chain_clean():
    for n in range(5):
        store.append_event(_event(n))
    assert store.verify_chain() == []


def test_verify_chain_detects_tampered_middle_line(tmp_path):
    for n in range(5):
        store.append_event(_event(n))
    path = store.events_path()
    lines = path.read_text().splitlines()
    doctored = json.loads(lines[2])
    doctored["event"]["actor"] = "mallory"
    lines[2] = json.dumps(doctored, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")
    errors = store.verify_chain()
    assert errors and "seq 3" in errors[0]


def test_verify_chain_detects_deleted_line(tmp_path):
    for n in range(5):
        store.append_event(_event(n))
    path = store.events_path()
    lines = path.read_text().splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n")
    assert store.verify_chain() != []


def test_empty_store_verifies_and_has_no_head():
    assert store.verify_chain() == []
    assert store.head() is None
    assert store.event_ids() == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-events/bin/python -m pytest tests/test_factory_store.py -v`
Expected: FAIL — `cannot import name 'store'`.

- [ ] **Step 3: Implement the store**

Create `src/factory_events/store.py`:

```python
"""Append-only hash-chained JSONL store at ~/.factory/events.jsonl.

Line format: {"seq": N, "prev_hash": h, "hash": h, "event": {...}}
hash = sha256(canonical_json({"seq", "prev_hash", "event"})). The chain
evidences edits/deletions; the nightly anchor (ship.py) evidences rewrites.
"""

import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path

from factory_events.envelope import canonical_json, validate_event

GENESIS = "0" * 64


def factory_home() -> Path:
    return Path(os.environ.get("FACTORY_EVENTS_HOME", str(Path.home() / ".factory")))


def events_path() -> Path:
    return factory_home() / "events.jsonl"


def state_dir() -> Path:
    return factory_home() / "state"


def _line_hash(seq: int, prev_hash: str, event: dict) -> str:
    return hashlib.sha256(
        canonical_json({"seq": seq, "prev_hash": prev_hash, "event": event})
    ).hexdigest()


def iter_records(path: Path | None = None) -> Iterator[dict]:
    path = path or events_path()
    if not path.exists():
        return
    with path.open() as fh:
        for raw in fh:
            raw = raw.strip()
            if raw:
                yield json.loads(raw)


def event_ids() -> set[str]:
    return {rec["event"]["event_id"] for rec in iter_records()}


def head() -> tuple[int, str] | None:
    last = None
    for rec in iter_records():
        last = rec
    return (last["seq"], last["hash"]) if last else None


def append_event(event: dict) -> dict:
    validate_event(event)
    path = events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = head()
        seq = current[0] + 1 if current else 1
        prev_hash = current[1] if current else GENESIS
        record = {
            "seq": seq,
            "prev_hash": prev_hash,
            "hash": _line_hash(seq, prev_hash, event),
            "event": event,
        }
        with path.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return record


def verify_chain(path: Path | None = None) -> list[str]:
    errors: list[str] = []
    expected_seq, expected_prev = 1, GENESIS
    for rec in iter_records(path):
        seq = rec.get("seq")
        if seq != expected_seq:
            errors.append(f"seq {seq}: expected seq {expected_seq} (line missing or reordered)")
            return errors
        if rec.get("prev_hash") != expected_prev:
            errors.append(f"seq {seq}: prev_hash mismatch (chain broken)")
            return errors
        if rec.get("hash") != _line_hash(seq, rec["prev_hash"], rec["event"]):
            errors.append(f"seq {seq}: hash mismatch (line tampered)")
            return errors
        try:
            validate_event(rec["event"])
        except Exception as exc:  # noqa: BLE001 — report, don't crash the walk
            errors.append(f"seq {seq}: schema violation: {exc}")
            return errors
        expected_seq, expected_prev = seq + 1, rec["hash"]
    return errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-events/bin/python -m pytest tests/test_factory_store.py tests/test_factory_envelope.py -v`
Expected: all pass. `ruff check src/factory_events` → clean (note: `# noqa: BLE001` above is deliberate and commented — if ruff flags the bare `Exception`, this is the documented exception).

- [ ] **Step 5: Commit**

```bash
git add src/factory_events/store.py tests/test_factory_store.py
git commit -m "feat: hash-chained append-only factory-events store"
```

---

### Task 3: CLI — `emit` and `verify`

**Files:**
- Create: `src/factory_events/cli.py`
- Create: `src/factory_events/__main__.py`
- Test: `tests/test_factory_cli.py`

**Interfaces:**
- Consumes: `envelope.make_event`, `store.append_event`, `store.verify_chain` (Tasks 1–2).
- Produces: `python3 -m factory_events emit|verify` exit codes (0 ok / 1 error); `cli.main(argv: list[str] | None = None) -> int`. Tasks 4, 6, 7 register `adapt` and `ship` subcommands into the same `cli.py` parser (marked below with "Task N extends here").

- [ ] **Step 1: Write the failing tests**

Create `tests/test_factory_cli.py`:

```python
import json

import pytest

from factory_events import store
from factory_events.cli import main


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def test_emit_appends_valid_event(capsys):
    rc = main([
        "emit",
        "--actor", "devon",
        "--action", "factory.bootstrap",
        "--result", "success",
        "--ref", "manual",
    ])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("evt-")
    assert store.head()[0] == 1


def test_emit_json_payload(capsys):
    payload = json.dumps({"note": "hello"})
    rc = main([
        "emit", "--actor", "devon", "--action", "factory.note",
        "--result", "success", "--ref", "manual", "--evidence-json", payload,
    ])
    assert rc == 0
    rec = list(store.iter_records())[0]
    assert rec["event"]["evidence"] == [{"note": "hello"}]


def test_emit_rejects_bad_action(capsys):
    rc = main(["emit", "--actor", "devon", "--action", "no-dots-here!",
               "--result", "success", "--ref", "manual"])
    assert rc == 1


def test_verify_ok_and_failure(capsys, tmp_path):
    main(["emit", "--actor", "devon", "--action", "factory.bootstrap",
          "--result", "success", "--ref", "manual"])
    assert main(["verify"]) == 0
    path = store.events_path()
    line = json.loads(path.read_text())
    line["event"]["actor"] = "mallory"
    path.write_text(json.dumps(line) + "\n")
    assert main(["verify"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-events/bin/python -m pytest tests/test_factory_cli.py -v`
Expected: FAIL — no module `factory_events.cli`.

- [ ] **Step 3: Implement the CLI**

Create `src/factory_events/cli.py`:

```python
"""factory-events CLI: emit, verify (adapt/ship added by later tasks)."""

import argparse
import json
import sys
from datetime import UTC, datetime

from factory_events import store
from factory_events.envelope import EnvelopeError, make_event


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cmd_emit(args: argparse.Namespace) -> int:
    try:
        evidence = [json.loads(args.evidence_json)] if args.evidence_json else []
        event = make_event(
            actor=args.actor,
            action=args.action,
            result=args.result,
            target=args.target,
            correlation_id=args.correlation_id,
            evidence=evidence,
            timestamp=_utc_now(),
            source={"system": "direct", "ref": args.ref},
        )
    except (EnvelopeError, json.JSONDecodeError) as exc:
        print(f"emit failed: {exc}", file=sys.stderr)
        return 1
    record = store.append_event(event)
    print(event["event_id"])
    print(f"seq={record['seq']} head={record['hash']}", file=sys.stderr)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    errors = store.verify_chain()
    if errors:
        for err in errors:
            print(f"VERIFY FAIL: {err}", file=sys.stderr)
        return 1
    current = store.head()
    print(f"chain ok: {current[0] if current else 0} events"
          + (f", head {current[1]}" if current else ""))
    return 0
    # Task 7 extends verify with --against-anchor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory_events")
    sub = parser.add_subparsers(dest="command", required=True)

    emit = sub.add_parser("emit", help="append one direct event to the store")
    emit.add_argument("--actor", required=True)
    emit.add_argument("--action", required=True)
    emit.add_argument("--result", required=True, choices=["success", "failure", "unknown"])
    emit.add_argument("--ref", required=True, help="source.ref, e.g. the emitter name")
    emit.add_argument("--target", default=None)
    emit.add_argument("--correlation-id", dest="correlation_id", default=None)
    emit.add_argument("--evidence-json", dest="evidence_json", default=None,
                      help="one JSON object appended to evidence[]")
    emit.set_defaults(func=_cmd_emit)

    verify = sub.add_parser("verify", help="verify the full hash chain + schemas")
    verify.set_defaults(func=_cmd_verify)

    # Task 4 extends here: adapt
    # Task 7 extends here: ship
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
```

Create `src/factory_events/__main__.py`:

```python
import sys

from factory_events.cli import main

sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-events/bin/python -m pytest tests/test_factory_cli.py -v` → all pass.
Then smoke the real entrypoint: `FACTORY_EVENTS_HOME=$(mktemp -d) .venv-events/bin/python -m factory_events emit --actor devon --action factory.smoke --result success --ref manual`
Expected: prints one `evt-...` id, exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/factory_events/cli.py src/factory_events/__main__.py tests/test_factory_cli.py
git commit -m "feat: factory-events CLI with emit and verify"
```

---

### Task 4: High-power adapter

**Files:**
- Create: `src/factory_events/adapters/__init__.py` (empty)
- Create: `src/factory_events/adapters/high_power.py`
- Create: `tests/fixtures/high_power_sample.jsonl`
- Modify: `src/factory_events/cli.py` (add `adapt` subcommand)
- Test: `tests/test_adapter_high_power.py`

**Interfaces:**
- Consumes: `envelope.make_event`, `envelope.deterministic_event_id`, `store.append_event`, `store.event_ids`, `store.state_dir` (Tasks 1–2).
- Produces: `high_power.adapt(source: Path | None = None, reanchor: bool = False) -> int` (events appended), `high_power.WatermarkError(RuntimeError)`, `high_power.DEFAULT_SOURCE: Path`. CLI: `adapt --source high-power [--reanchor]`. Task 6 adds `change-manager` and `all` choices to the same `--source` flag; Task 8's nightly script calls `adapt --source all`.

- [ ] **Step 1: Create the golden fixture**

Create `tests/fixtures/high_power_sample.jsonl` (field shape verbatim from the real log — see spec §4; `args_summary` is a *stringified* JSON, `provenance` is the fixed literal):

```json
{"timestamp":"2026-07-02T23:33:35Z","tool":"mcp__infraops__vps_exec","session_id":"3ca07069-1111-2222-3333-444444444444","args_summary":"{\"command\":\"docker ps\",\"host\":\"vps\"}","provenance":"unknown (confirm at review: direct request vs inferred from read content)"}
{"timestamp":"2026-07-02T23:40:00Z","tool":"mcp__infraops__coolify_deploy","session_id":"3ca07069-1111-2222-3333-444444444444","args_summary":"{\"uuid\":\"abc123\"}","provenance":"unknown (confirm at review: direct request vs inferred from read content)"}
{"timestamp":"2026-07-03T01:02:03Z","tool":"Gmail__send","session_id":"9999aaaa-1111-2222-3333-444444444444","args_summary":"{\"to\":\"someone@example.com\"}","provenance":"unknown (confirm at review: direct request vs inferred from read content)"}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_adapter_high_power.py`:

```python
import json
import shutil
from pathlib import Path

import pytest

from factory_events import store
from factory_events.adapters import high_power

FIXTURE = Path(__file__).parent / "fixtures" / "high_power_sample.jsonl"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path / "factory"))
    yield tmp_path


@pytest.fixture()
def source(tmp_path) -> Path:
    src = tmp_path / "high-power-actions.jsonl"
    shutil.copy(FIXTURE, src)
    return src


def test_adapt_maps_fields(source):
    count = high_power.adapt(source=source)
    assert count == 3
    records = list(store.iter_records())
    ev = records[0]["event"]
    assert ev["action"] == "tool.vps_exec"
    assert ev["actor"] == "claude-code-unattributed"
    assert ev["result"] == "unknown"
    assert ev["correlation_id"] == "3ca07069-1111-2222-3333-444444444444"
    assert ev["source"] == {"system": "high-power-audit", "ref": "line:1"}
    assert ev["evidence"][0]["type"] == "source-record"
    assert ev["evidence"][0]["record"]["tool"] == "mcp__infraops__vps_exec"
    assert ev["target"] == "docker ps"
    # non-MCP tool name passes through
    assert records[2]["event"]["action"] == "tool.Gmail__send"


def test_adapt_is_incremental_and_idempotent(source):
    assert high_power.adapt(source=source) == 3
    assert high_power.adapt(source=source) == 0  # nothing new
    with source.open("a") as fh:
        fh.write(json.dumps({
            "timestamp": "2026-07-03T02:00:00Z", "tool": "mcp__infraops__vps_exec",
            "session_id": "s", "args_summary": "{}", "provenance": "unknown (confirm at review: direct request vs inferred from read content)",
        }) + "\n")
    assert high_power.adapt(source=source) == 1
    assert len(store.event_ids()) == 4


def test_rewritten_source_raises_without_reanchor(source):
    high_power.adapt(source=source)
    lines = source.read_text().splitlines()
    lines[0] = lines[0].replace("docker ps", "docker kill")
    source.write_text("\n".join(lines) + "\n")
    with pytest.raises(high_power.WatermarkError):
        high_power.adapt(source=source)


def test_reanchor_reingests_with_dedupe(source):
    high_power.adapt(source=source)
    lines = source.read_text().splitlines()
    lines[0] = lines[0].replace("docker ps", "docker kill")
    source.write_text("\n".join(lines) + "\n")
    count = high_power.adapt(source=source, reanchor=True)
    # only the rewritten line is new (different raw line -> different event_id)
    assert count == 1
    assert len(store.event_ids()) == 4


def test_truncated_source_raises(source):
    high_power.adapt(source=source)
    source.write_text("")
    with pytest.raises(high_power.WatermarkError):
        high_power.adapt(source=source)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv-events/bin/python -m pytest tests/test_adapter_high_power.py -v`
Expected: FAIL — no module `factory_events.adapters`.

- [ ] **Step 4: Implement the adapter**

Create empty `src/factory_events/adapters/__init__.py`, then `src/factory_events/adapters/high_power.py`:

```python
"""Adapter: ~/.claude/audit/high-power-actions.jsonl -> factory-events store.

Watermark = {line_count, last_line_sha256}. A hash mismatch means the source
was rewritten/rotated: fail loudly; --reanchor re-ingests from line 0 and the
deterministic event_id (sha256 of the source line) dedupes against the store.
Backfill scope is the live file only (spec §4 — .bak snapshots declined).
"""

import hashlib
import json
from pathlib import Path

from factory_events import store
from factory_events.envelope import deterministic_event_id, make_event

DEFAULT_SOURCE = Path.home() / ".claude" / "audit" / "high-power-actions.jsonl"
SYSTEM = "high-power-audit"
_TARGET_KEYS = ("command", "host", "domain", "to", "name", "uuid")


class WatermarkError(RuntimeError):
    """Source file changed under the watermark — refuse to guess."""


def _watermark_path() -> Path:
    return store.state_dir() / "high-power.json"


def _load_watermark() -> dict | None:
    path = _watermark_path()
    return json.loads(path.read_text()) if path.exists() else None


def _save_watermark(lines: list[str]) -> None:
    path = _watermark_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    mark = {
        "line_count": len(lines),
        "last_line_sha256": hashlib.sha256(lines[-1].encode()).hexdigest() if lines else None,
    }
    path.write_text(json.dumps(mark, indent=1))


def _extract_target(args_summary: str) -> str | None:
    try:
        args = json.loads(args_summary)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(args, dict):
        return None
    for key in _TARGET_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value:
            return value[:200]
    return None


def _map_line(raw_line: str, lineno: int) -> dict:
    raw = json.loads(raw_line)
    tool = raw["tool"]
    name = tool.split("__", 2)[2] if tool.startswith("mcp__") and tool.count("__") >= 2 else tool
    return make_event(
        event_id=deterministic_event_id(SYSTEM, raw_line),
        timestamp=raw["timestamp"],
        actor="claude-code-unattributed",
        action=f"tool.{name}",
        target=_extract_target(raw.get("args_summary", "")),
        result="unknown",
        evidence=[{"type": "source-record", "record": raw}],
        correlation_id=raw.get("session_id"),
        source={"system": SYSTEM, "ref": f"line:{lineno}"},
    )


def adapt(source: Path | None = None, reanchor: bool = False) -> int:
    source = source or DEFAULT_SOURCE
    lines = source.read_text().splitlines() if source.exists() else []
    mark = _load_watermark()
    start = 0
    if mark and not reanchor:
        count = mark["line_count"]
        if len(lines) < count or (
            count > 0
            and hashlib.sha256(lines[count - 1].encode()).hexdigest() != mark["last_line_sha256"]
        ):
            raise WatermarkError(
                f"{source} changed under the watermark (rewritten/rotated/truncated); "
                "re-run with --reanchor to accept the file as a new baseline"
            )
        start = count
    known = store.event_ids()
    appended = 0
    for offset, raw_line in enumerate(lines[start:], start=start + 1):
        if not raw_line.strip():
            continue
        event = _map_line(raw_line, lineno=offset)
        if event["event_id"] in known:
            continue
        store.append_event(event)
        known.add(event["event_id"])
        appended += 1
    _save_watermark(lines)
    return appended
```

- [ ] **Step 5: Wire the `adapt` subcommand into the CLI**

In `src/factory_events/cli.py`, replace the comment line `# Task 4 extends here: adapt` with:

```python
    adapt = sub.add_parser("adapt", help="translate source logs into the store")
    adapt.add_argument("--source", required=True, choices=["high-power"])
    adapt.add_argument("--reanchor", action="store_true")
    adapt.set_defaults(func=_cmd_adapt)
```

And add above `build_parser`:

```python
def _cmd_adapt(args: argparse.Namespace) -> int:
    from factory_events.adapters import high_power

    try:
        if args.source == "high-power":
            count = high_power.adapt(reanchor=args.reanchor)
            print(f"high-power: {count} events appended")
    except high_power.WatermarkError as exc:
        print(f"ADAPT FAIL: {exc}", file=sys.stderr)
        return 1
    return 0
```

Add a CLI test to `tests/test_factory_cli.py`:

```python
def test_adapt_high_power_via_cli(tmp_path, monkeypatch, capsys):
    src = tmp_path / "hp.jsonl"
    src.write_text('{"timestamp":"2026-07-02T23:33:35Z","tool":"mcp__infraops__vps_exec",'
                   '"session_id":"s","args_summary":"{}","provenance":"unknown (confirm at review: direct request vs inferred from read content)"}\n')
    from factory_events.adapters import high_power
    monkeypatch.setattr(high_power, "DEFAULT_SOURCE", src)
    assert main(["adapt", "--source", "high-power"]) == 0
    assert "1 events appended" in capsys.readouterr().out
```

- [ ] **Step 6: Run all tests**

Run: `.venv-events/bin/python -m pytest tests/ -v -k "factory or adapter"`
Expected: all pass. `ruff check src tests` → clean.

- [ ] **Step 7: Commit**

```bash
git add src/factory_events/adapters/ src/factory_events/cli.py tests/test_adapter_high_power.py tests/fixtures/high_power_sample.jsonl tests/test_factory_cli.py
git commit -m "feat: high-power audit-log adapter with watermark + reanchor"
```

---

### Task 5: change-manager events endpoint (separate repo, separate PR)

**Files (all in `~/Projects/change-manager`):**
- Modify: `app/api.py` (new `GET /api/events`; add `ChangeEvent` to the models import)
- Test: `tests/test_api_events.py`

**Interfaces:**
- Consumes: existing `ChangeEvent`/`ChangeItem` models, `require_m2m` router dependency (already applied router-wide), `record_event` test helper pattern.
- Produces: `GET /api/events?after_id=<int>&limit=<int>` → `{"events": [{id, item_id, at, actor, event_type, from_status, to_status, detail, attempt_id, window_run_id, item_identity, item_rule_key, item_instance}]}` ordered by `id` ascending, `id > after_id`, `limit` 1–1000 (default 500). Task 6's adapter consumes exactly this shape. (Spec §4 mentions a `provider` join; `ChangeItem` has no `provider` column — `item_instance` + `item_rule_key` carry that role.)

- [ ] **Step 1: Create a branch**

```bash
cd ~/Projects/change-manager && git checkout main && git pull && git checkout -b feat/events-endpoint
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_api_events.py`:

```python
from datetime import UTC, datetime

import app.auth as auth
from app.events import record_event
from app.models import ChangeItem

H = {"Authorization": "Bearer t"}


def _seed(db, n: int) -> ChangeItem:
    item = ChangeItem(
        identity=f"it-{n}", instance="prod", rule_key="backup.configured",
        resource_type="database", resource_uuid=f"u-{n}", resource_name=f"db-{n}",
        risk="low", kind="config", status="pending", source="drift",
    )
    db.add(item)
    db.flush()
    record_event(db, item, actor="sync", event_type="created", to_status="pending")
    record_event(db, item, actor="devon@example.com", event_type="approved",
                 from_status="pending", to_status="approved")
    db.commit()
    return item


def test_events_pagination_and_shape(client, db):
    auth.settings.m2m_token = "t"
    _seed(db, 1)
    r = client.get("/api/events?after_id=0&limit=1", headers=H)
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 1
    first = events[0]
    assert first["event_type"] == "created" and first["item_identity"] == "it-1"
    assert first["item_rule_key"] == "backup.configured" and first["item_instance"] == "prod"
    r2 = client.get(f"/api/events?after_id={first['id']}&limit=100", headers=H)
    rest = r2.json()["events"]
    assert [e["event_type"] for e in rest] == ["approved"]
    r3 = client.get(f"/api/events?after_id={rest[-1]['id']}", headers=H)
    assert r3.json()["events"] == []


def test_events_requires_m2m(client, db):
    auth.settings.m2m_token = "t"
    assert client.get("/api/events").status_code == 401
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ~/Projects/change-manager && python3 -m pytest tests/test_api_events.py -v`
Expected: FAIL — 404 (route doesn't exist). (`test_events_requires_m2m` may pass already; that's fine.)

- [ ] **Step 4: Implement the endpoint**

In `app/api.py`: change the models import line to include `ChangeEvent`:

```python
from app.models import ChangeAttempt, ChangeEvent, ChangeItem, WindowRun
```

Add after the `get_item` endpoint (keep read endpoints together):

```python
@router.get("/events")
def list_events(
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    """Read-only event feed for the factory-events adapter (WS-1.1). Cursor = id."""
    rows = db.execute(
        select(ChangeEvent, ChangeItem)
        .join(ChangeItem, ChangeEvent.item_id == ChangeItem.id)
        .where(ChangeEvent.id > after_id)
        .order_by(ChangeEvent.id.asc())
        .limit(limit)
    ).all()
    return {
        "events": [
            {
                "id": ev.id,
                "item_id": ev.item_id,
                "at": ev.at.isoformat(),
                "actor": ev.actor,
                "event_type": ev.event_type,
                "from_status": ev.from_status,
                "to_status": ev.to_status,
                "detail": ev.detail,
                "attempt_id": ev.attempt_id,
                "window_run_id": ev.window_run_id,
                "item_identity": item.identity,
                "item_rule_key": item.rule_key,
                "item_instance": item.instance,
            }
            for ev, item in rows
        ]
    }
```

- [ ] **Step 5: Run the full change-manager suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass (no regressions — this endpoint touches nothing else).

- [ ] **Step 6: Commit, push, open the PR (do NOT merge)**

```bash
git add app/api.py tests/test_api_events.py
git commit -m "feat: read-only /api/events feed for factory-events adapter (WS-1.1)"
git push -u origin feat/events-endpoint
gh pr create --title "feat: read-only /api/events feed (WS-1.1 adapter)" --body "Cursor-paginated read-only ChangeEvent feed with item identity join, M2M-authed via the existing router dependency. Consumed by security-standards factory_events adapter. No logger/schema changes.

Part of WS-1.1 (software-factory Phase 1). Spec: security-standards docs/superpowers/specs/2026-07-02-ws11-audit-event-envelope-design.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

Report the PR URL. **Devon merges; the deploy flows through change-manager's normal CI.** Task 10's change-manager backfill depends on this being deployed — the high-power half of Task 10 does not.

---

### Task 6: change-manager adapter

**Files (back in `~/Projects/security-standards`):**
- Create: `src/factory_events/adapters/change_manager.py`
- Modify: `src/factory_events/cli.py` (extend `adapt --source` choices)
- Test: `tests/test_adapter_change_manager.py`

**Interfaces:**
- Consumes: Task 5's response shape; `envelope.make_event`, `envelope.deterministic_event_id`, `store` (Tasks 1–2); env vars `CM_BASE_URL`, `CM_M2M_TOKEN` (from `~/.factory/env` at runtime).
- Produces: `change_manager.adapt(fetch: Callable[[int, int], list[dict]] | None = None) -> int`; CLI `adapt --source change-manager|all`. `fetch(after_id, limit)` returns the endpoint's `events` list — tests inject a fake; the default is `change_manager._http_fetch` (stdlib urllib, Bearer auth).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_adapter_change_manager.py`:

```python
import pytest

from factory_events import store
from factory_events.adapters import change_manager


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def _raw(id_: int, event_type: str = "created", actor: str = "sync") -> dict:
    return {
        "id": id_, "item_id": 7, "at": "2026-07-01T04:00:00+00:00",
        "actor": actor, "event_type": event_type,
        "from_status": None, "to_status": "pending", "detail": None,
        "attempt_id": None, "window_run_id": None,
        "item_identity": "db-backup-x", "item_rule_key": "backup.configured",
        "item_instance": "prod",
    }


def _fake_fetch(pages: dict[int, list[dict]]):
    def fetch(after_id: int, limit: int) -> list[dict]:
        return pages.get(after_id, [])
    return fetch


def test_adapt_maps_fields_and_paginates():
    pages = {0: [_raw(1), _raw(2, "approved", "devon@example.com")], 2: []}
    count = change_manager.adapt(fetch=_fake_fetch(pages))
    assert count == 2
    records = list(store.iter_records())
    ev1, ev2 = records[0]["event"], records[1]["event"]
    assert ev1["action"] == "change.created"
    assert ev1["actor"] == "drift-reconciler"          # "sync" mapped
    assert ev1["timestamp"] == "2026-07-01T04:00:00Z"  # Z-normalized
    assert ev1["target"] == "db-backup-x"
    assert ev1["correlation_id"] == "change-item:7"
    assert ev1["source"] == {"system": "change-manager", "ref": "change-event:1"}
    assert ev2["actor"] == "devon"                     # email mapped
    assert ev2["authority_grant"] == {
        "system": "change-manager", "item_id": 7, "approver": "devon@example.com",
    }
    assert ev2["result"] == "success"


def test_actor_and_result_mapping_table():
    pages = {0: [
        _raw(1, "applied", "executor"),
        _raw(2, "failed", "executor"),
        _raw(3, "pr_linked", "api"),
        _raw(4, "stale_handoff", "watchdog"),
    ], 4: []}
    change_manager.adapt(fetch=_fake_fetch(pages))
    events = [r["event"] for r in store.iter_records()]
    assert [e["actor"] for e in events] == [
        "change-window-agent", "change-window-agent", "unknown", "drift-reconciler",
    ]
    assert [e["result"] for e in events] == ["success", "failure", "unknown", "unknown"]
    assert all(e["authority_grant"] is None for e in events)


def test_watermark_resumes_from_last_id():
    pages = {0: [_raw(1)], 1: []}
    assert change_manager.adapt(fetch=_fake_fetch(pages)) == 1
    pages2 = {1: [_raw(2)], 2: []}
    assert change_manager.adapt(fetch=_fake_fetch(pages2)) == 1
    assert change_manager._load_watermark() == {"last_id": 2}


def test_missing_config_fails_loudly(monkeypatch):
    monkeypatch.delenv("CM_BASE_URL", raising=False)
    monkeypatch.delenv("CM_M2M_TOKEN", raising=False)
    with pytest.raises(change_manager.ConfigError):
        change_manager.adapt()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-events/bin/python -m pytest tests/test_adapter_change_manager.py -v`
Expected: FAIL — no module `change_manager`.

- [ ] **Step 3: Implement the adapter**

Create `src/factory_events/adapters/change_manager.py`:

```python
"""Adapter: change-manager /api/events -> factory-events store.

Cursor = ChangeEvent.id (watermark {"last_id": N}); the endpoint is added by
the WS-1.1 change-manager PR. Raw actor strings are preserved verbatim inside
evidence[0].record; the envelope actor is the provisional-vocabulary mapping.
"executor" covers both window-lane executors, so it maps to change-window-agent
(conflation documented in the README; WS-1.2 fixes identity properly).
"""

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from factory_events import store
from factory_events.envelope import deterministic_event_id, make_event

SYSTEM = "change-manager"
PAGE_LIMIT = 500

_ACTOR_MAP = {
    "sync": "drift-reconciler",
    "watchdog": "drift-reconciler",
    "executor": "change-window-agent",
}
_RESULT_MAP = {"applied": "success", "approved": "success", "failed": "failure"}
_GRANT_TYPES = {"approved"}


class ConfigError(RuntimeError):
    """CM_BASE_URL / CM_M2M_TOKEN missing from the environment."""


def _watermark_path() -> Path:
    return store.state_dir() / "change-manager.json"


def _load_watermark() -> dict | None:
    path = _watermark_path()
    return json.loads(path.read_text()) if path.exists() else None


def _save_watermark(last_id: int) -> None:
    path = _watermark_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_id": last_id}))


def _map_actor(raw_actor: str) -> str:
    if raw_actor in _ACTOR_MAP:
        return _ACTOR_MAP[raw_actor]
    if "@" in raw_actor:
        return "devon"  # solo operator: any SSO email is Devon
    return "unknown"


def _normalize_ts(raw: str) -> str:
    ts = datetime.fromisoformat(raw)
    naive = ts.replace(tzinfo=None) if ts.tzinfo else ts  # DB times are UTC
    suffix = f".{naive.microsecond:06d}" if naive.microsecond else ""
    return naive.strftime("%Y-%m-%dT%H:%M:%S") + suffix + "Z"


def _map_event(raw: dict) -> dict:
    event_type = raw["event_type"]
    grant = None
    if event_type in _GRANT_TYPES:
        grant = {"system": SYSTEM, "item_id": raw["item_id"], "approver": raw["actor"]}
    return make_event(
        event_id=deterministic_event_id(SYSTEM, str(raw["id"])),
        timestamp=_normalize_ts(raw["at"]),
        actor=_map_actor(raw["actor"]),
        action=f"change.{event_type}",
        target=raw.get("item_identity"),
        result=_RESULT_MAP.get(event_type, "unknown"),
        evidence=[{"type": "source-record", "record": raw}],
        authority_grant=grant,
        correlation_id=f"change-item:{raw['item_id']}",
        source={"system": SYSTEM, "ref": f"change-event:{raw['id']}"},
    )


def _http_fetch(after_id: int, limit: int) -> list[dict]:
    base_url = os.environ.get("CM_BASE_URL", "")
    token = os.environ.get("CM_M2M_TOKEN", "")
    if not base_url or not token:
        raise ConfigError("CM_BASE_URL and CM_M2M_TOKEN must be set (source ~/.factory/env)")
    query = urllib.parse.urlencode({"after_id": after_id, "limit": limit})
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/events?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — https URL from config
        return json.loads(resp.read())["events"]


def adapt(fetch: Callable[[int, int], list[dict]] | None = None) -> int:
    if fetch is None:
        if not (os.environ.get("CM_BASE_URL") and os.environ.get("CM_M2M_TOKEN")):
            raise ConfigError("CM_BASE_URL and CM_M2M_TOKEN must be set (source ~/.factory/env)")
        fetch = _http_fetch
    mark = _load_watermark()
    after_id = mark["last_id"] if mark else 0
    known = store.event_ids()
    appended = 0
    while True:
        page = fetch(after_id, PAGE_LIMIT)
        if not page:
            break
        for raw in page:
            event = _map_event(raw)
            if event["event_id"] not in known:
                store.append_event(event)
                known.add(event["event_id"])
                appended += 1
        after_id = page[-1]["id"]
        _save_watermark(after_id)
    return appended
```

- [ ] **Step 4: Extend the CLI**

In `src/factory_events/cli.py`, change the adapt choices to `["high-power", "change-manager", "all"]` and replace `_cmd_adapt` with:

```python
def _cmd_adapt(args: argparse.Namespace) -> int:
    from factory_events.adapters import change_manager, high_power

    failures = 0
    if args.source in ("high-power", "all"):
        try:
            count = high_power.adapt(reanchor=args.reanchor)
            print(f"high-power: {count} events appended")
        except high_power.WatermarkError as exc:
            print(f"ADAPT FAIL (high-power): {exc}", file=sys.stderr)
            failures += 1
    if args.source in ("change-manager", "all"):
        try:
            count = change_manager.adapt()
            print(f"change-manager: {count} events appended")
        except (change_manager.ConfigError, OSError) as exc:
            print(f"ADAPT FAIL (change-manager): {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0
```

- [ ] **Step 5: Run all tests**

Run: `.venv-events/bin/python -m pytest tests/ -q` → all pass; `ruff check src tests` → clean.

- [ ] **Step 6: Commit**

```bash
git add src/factory_events/adapters/change_manager.py src/factory_events/cli.py tests/test_adapter_change_manager.py
git commit -m "feat: change-manager events adapter with cursor watermark"
```

---

### Task 7: `ship` — Postgres projection + head-hash anchoring

**Files:**
- Create: `src/factory_events/ship.py`
- Modify: `src/factory_events/cli.py` (add `ship`; add `verify --against-anchor`)
- Test: `tests/test_factory_ship.py`

**Interfaces:**
- Consumes: `store.iter_records`, `store.head`, `store.verify_chain` (Task 2); env `FACTORY_DB_DSN`.
- Produces: `ship.ship(dsn: str | None = None, rebuild: bool = False) -> tuple[int, tuple[int, str] | None]` (rows inserted, (seq, head_hash) anchored), `ship.last_anchor(dsn: str | None = None) -> tuple[int, str] | None`. CLI: `ship [--rebuild]` prints `shipped=<n> head_seq=<seq> head=<hash>`; `verify --against-anchor` fails (exit 1) if the last anchored (seq, head_hash) is absent from the current chain. `psycopg` is imported inside functions only — emit/adapt/verify never need it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_factory_ship.py`. The Postgres integration tests are gated on `FACTORY_TEST_DSN` (skipped when absent); the anchor-check logic is tested without a DB by monkeypatching `last_anchor`.

```python
import os

import pytest

from factory_events import envelope, ship, store
from factory_events.cli import main

DSN = os.environ.get("FACTORY_TEST_DSN")
needs_pg = pytest.mark.skipif(not DSN, reason="FACTORY_TEST_DSN not set")


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def _seed(n: int) -> None:
    for i in range(n):
        store.append_event(envelope.make_event(
            actor="devon", action="test.ping", result="success",
            source={"system": "direct", "ref": "test"},
            timestamp="2026-07-02T00:00:00Z",
            event_id=envelope.deterministic_event_id("direct", str(i)),
        ))


@pytest.fixture()
def pg(monkeypatch):
    monkeypatch.setenv("FACTORY_DB_DSN", DSN)
    import psycopg

    with psycopg.connect(DSN) as conn:
        conn.execute("DROP TABLE IF EXISTS factory_events, chain_heads")
    yield DSN


@needs_pg
def test_ship_inserts_and_anchors(pg):
    _seed(3)
    inserted, head = ship.ship()
    assert inserted == 3 and head == store.head()
    assert ship.last_anchor() == head
    # idempotent: nothing new
    inserted2, _ = ship.ship()
    assert inserted2 == 0
    # anchors accumulate (a second head row, same head)
    import psycopg

    with psycopg.connect(pg) as conn:
        assert conn.execute("SELECT count(*) FROM chain_heads").fetchone()[0] == 2


@needs_pg
def test_ship_rebuild_replays_but_keeps_anchors(pg):
    _seed(2)
    ship.ship()
    inserted, _ = ship.ship(rebuild=True)
    import psycopg

    with psycopg.connect(pg) as conn:
        assert conn.execute("SELECT count(*) FROM factory_events").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM chain_heads").fetchone()[0] == 2
    assert inserted == 2


@needs_pg
def test_ship_promotes_query_columns(pg):
    _seed(1)
    ship.ship()
    import psycopg

    with psycopg.connect(pg) as conn:
        row = conn.execute(
            "SELECT actor, action, result, source_system FROM factory_events"
        ).fetchone()
    assert row == ("devon", "test.ping", "success", "direct")


def test_verify_against_anchor_passes_and_fails(monkeypatch):
    _seed(3)
    seq, head_hash = store.head()
    monkeypatch.setattr(ship, "last_anchor", lambda dsn=None: (seq, head_hash))
    assert main(["verify", "--against-anchor"]) == 0
    monkeypatch.setattr(ship, "last_anchor", lambda dsn=None: (seq, "f" * 64))
    assert main(["verify", "--against-anchor"]) == 1


def test_verify_against_anchor_with_no_anchor_yet_passes(monkeypatch):
    _seed(1)
    monkeypatch.setattr(ship, "last_anchor", lambda dsn=None: None)
    assert main(["verify", "--against-anchor"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-events/bin/python -m pytest tests/test_factory_ship.py -v`
Expected: FAIL — no module `factory_events.ship`. (The `@needs_pg` tests will SKIP unless you start a throwaway Postgres: `docker run -d --name factory-test-pg -e POSTGRES_PASSWORD=test -p 5599:5432 postgres:16` then `export FACTORY_TEST_DSN='postgresql://postgres:test@127.0.0.1:5599/postgres'`. Do this — the integration tests must actually run before Task 7 is done.)

- [ ] **Step 3: Implement ship**

Create `src/factory_events/ship.py`:

```python
"""Ship the JSONL store to the local Postgres projection + anchor the head.

The projection is disposable (--rebuild replays the JSONL). chain_heads is the
tamper-evidence anchor: --rebuild NEVER touches it, and verify --against-anchor
checks the chain still contains the last anchored (seq, head_hash).
"""

import os

from factory_events import store

DDL = """
CREATE TABLE IF NOT EXISTS factory_events (
    event_id       text PRIMARY KEY,
    seq            bigint NOT NULL,
    ts             timestamptz NOT NULL,
    actor          text NOT NULL,
    action         text NOT NULL,
    target         text,
    work_package   text,
    input_revision text,
    result         text NOT NULL,
    source_system  text NOT NULL,
    correlation_id text,
    event          jsonb NOT NULL,
    hash           text NOT NULL,
    prev_hash      text NOT NULL
);
CREATE TABLE IF NOT EXISTS chain_heads (
    id          bigserial PRIMARY KEY,
    anchored_at timestamptz NOT NULL DEFAULT now(),
    seq         bigint NOT NULL,
    head_hash   text NOT NULL
);
"""

INSERT = """
INSERT INTO factory_events (event_id, seq, ts, actor, action, target, work_package,
    input_revision, result, source_system, correlation_id, event, hash, prev_hash)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (event_id) DO NOTHING
"""


def _dsn(dsn: str | None) -> str:
    resolved = dsn or os.environ.get("FACTORY_DB_DSN", "")
    if not resolved:
        raise RuntimeError("FACTORY_DB_DSN not set (source ~/.factory/env)")
    return resolved


def _connect(dsn: str | None):
    import psycopg  # lazy: emit/adapt/verify must not require it

    return psycopg.connect(_dsn(dsn))


def last_anchor(dsn: str | None = None) -> tuple[int, str] | None:
    with _connect(dsn) as conn:
        conn.execute(DDL)
        row = conn.execute(
            "SELECT seq, head_hash FROM chain_heads ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return (row[0], row[1]) if row else None


def ship(dsn: str | None = None, rebuild: bool = False) -> tuple[int, tuple[int, str] | None]:
    from psycopg.types.json import Json  # lazy, with psycopg

    inserted = 0
    with _connect(dsn) as conn:
        conn.execute(DDL)
        if rebuild:
            conn.execute("TRUNCATE factory_events")  # never chain_heads
        with conn.cursor() as cur:
            for rec in store.iter_records():
                ev = rec["event"]
                cur.execute(INSERT, (
                    ev["event_id"], rec["seq"], ev["timestamp"], ev["actor"], ev["action"],
                    ev["target"], ev["work_package"], ev["input_revision"], ev["result"],
                    ev["source"]["system"], ev["correlation_id"], Json(ev),
                    rec["hash"], rec["prev_hash"],
                ))
                inserted += cur.rowcount
        current = store.head()
        if current:
            conn.execute(
                "INSERT INTO chain_heads (seq, head_hash) VALUES (%s, %s)", current
            )
        conn.commit()
    return inserted, current
```

- [ ] **Step 4: Wire `ship` and `verify --against-anchor` into the CLI**

In `src/factory_events/cli.py`, replace the comment `# Task 7 extends here: ship` with:

```python
    ship_cmd = sub.add_parser("ship", help="upsert events into the Postgres projection")
    ship_cmd.add_argument("--rebuild", action="store_true",
                          help="truncate factory_events (never chain_heads) and replay")
    ship_cmd.set_defaults(func=_cmd_ship)
```

Add `verify.add_argument("--against-anchor", action="store_true")` to the verify parser, then replace `_cmd_verify` and add `_cmd_ship`:

```python
def _cmd_verify(args: argparse.Namespace) -> int:
    errors = store.verify_chain()
    if errors:
        for err in errors:
            print(f"VERIFY FAIL: {err}", file=sys.stderr)
        return 1
    current = store.head()
    if getattr(args, "against_anchor", False):
        from factory_events import ship as ship_mod

        anchor = ship_mod.last_anchor()
        if anchor is not None:
            seqs = {rec["seq"]: rec["hash"] for rec in store.iter_records()}
            if seqs.get(anchor[0]) != anchor[1]:
                print(f"VERIFY FAIL: anchored head (seq {anchor[0]}) not in chain — "
                      "store rewritten since last anchor", file=sys.stderr)
                return 1
            print(f"anchor ok: seq {anchor[0]} present")
    print(f"chain ok: {current[0] if current else 0} events"
          + (f", head {current[1]}" if current else ""))
    return 0


def _cmd_ship(args: argparse.Namespace) -> int:
    from factory_events import ship as ship_mod

    try:
        inserted, current = ship_mod.ship(rebuild=args.rebuild)
    except Exception as exc:  # noqa: BLE001 — any DB failure is a hard job failure
        print(f"SHIP FAIL: {exc}", file=sys.stderr)
        return 1
    if current:
        print(f"shipped={inserted} head_seq={current[0]} head={current[1]}")
    else:
        print("shipped=0 (empty store)")
    return 0
```

- [ ] **Step 5: Run the full suite with the throwaway Postgres up**

Run: `FACTORY_TEST_DSN='postgresql://postgres:test@127.0.0.1:5599/postgres' .venv-events/bin/python -m pytest tests/ -q`
Expected: all pass, 0 skipped in test_factory_ship.py. Then `docker rm -f factory-test-pg`. `ruff check src tests` → clean.

- [ ] **Step 6: Commit**

```bash
git add src/factory_events/ship.py src/factory_events/cli.py tests/test_factory_ship.py
git commit -m "feat: postgres projection ship with chain-head anchoring"
```

---

### Task 8: Deploy assets — compose, nightly script, LaunchAgent

**Files:**
- Create: `deploy/factory-events-db/docker-compose.yml`
- Create: `scripts/factory-events-nightly.sh` (mode 755)
- Create: `scripts/com.devon.factory-events.plist.template`
- Create: `scripts/install-factory-events-launchd.sh` (mode 755)
- Modify: `.gitignore` (add `deploy/factory-events-db/.env`)

**Interfaces:**
- Consumes: the CLI surface from Tasks 3–7 (`adapt --source all`, `verify --against-anchor`, `ship`), `.venv-events` from Task 1.
- Produces: runnable nightly job. Runtime config contract (consumed by Task 10's provisioning): `~/.factory/env` (chmod 600) defines `CM_BASE_URL`, `CM_M2M_TOKEN`, `FACTORY_DB_DSN`, `FACTORY_HC_PING_URL` (optional).

- [ ] **Step 1: Write the compose file**

Create `deploy/factory-events-db/docker-compose.yml` (mirrors email-capture's local-DB pattern; port 5545 — 5544 is taken by email-capture-db):

```yaml
services:
  db:
    image: postgres:16
    container_name: factory-events-db
    restart: unless-stopped
    environment:
      POSTGRES_DB: factory_events
      POSTGRES_USER: factory_events
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set in .env}
    ports:
      - "5545:5432"
    volumes:
      - factory_events_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U factory_events -d factory_events"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s
volumes:
  factory_events_pgdata:
```

Add `deploy/factory-events-db/.env` to `.gitignore`.

- [ ] **Step 2: Write the nightly script**

Create `scripts/factory-events-nightly.sh`:

```bash
#!/bin/bash
# factory-events nightly: adapt -> verify (incl. anchor) -> ship -> healthcheck ping.
# Source of truth: security-standards scripts/factory-events-nightly.sh (WS-1.1).
# Config: ~/.factory/env (chmod 600) — CM_BASE_URL, CM_M2M_TOKEN, FACTORY_DB_DSN,
# FACTORY_HC_PING_URL (optional; ping skipped when unset).
set -euo pipefail

REPO="$HOME/Projects/security-standards"
PY="$REPO/.venv-events/bin/python"
ENV_FILE="$HOME/.factory/env"
LOG_PREFIX="[factory-events]"

log() { echo "$LOG_PREFIX $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"; }

hc_ping() { # $1 = "" | "/start" | "/fail" ; $2 = optional body
    [ -n "${FACTORY_HC_PING_URL:-}" ] || return 0
    curl -fsS --max-time 10 --data-raw "${2:-}" "${FACTORY_HC_PING_URL}$1" >/dev/null 2>&1 \
        || log "WARNING: healthcheck ping '$1' failed (non-fatal)"
}

fail() {
    log "FAILED: $1"
    hc_ping "/fail" "$1"
    exit 1
}

[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE"
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a
[ -x "$PY" ] || fail "missing venv: $PY (run: python3 -m venv .venv-events && pip install -e '.[events]')"

hc_ping "/start"
log "adapt"
"$PY" -m factory_events adapt --source all       || fail "adapt"
log "verify (chain + anchor)"
"$PY" -m factory_events verify --against-anchor  || fail "verify"
log "ship"
SHIP_OUT=$("$PY" -m factory_events ship)         || fail "ship"
log "$SHIP_OUT"
hc_ping "" "$SHIP_OUT"
log "done"
```

Run: `chmod 755 scripts/factory-events-nightly.sh && bash -n scripts/factory-events-nightly.sh`
Expected: syntax check exits 0.

Note: the spec says "same pattern as the backup jobs" for Healthchecks; the backup jobs resolve the ping URL via the Healthchecks API + BWS at runtime. This script instead reads `FACTORY_HC_PING_URL` from the chmod-600 env file — one fewer runtime dependency (no BWS token needed at 03:30), same dead-man semantics, ping URL provisioned once in Task 10. Degrades gracefully (ping skipped, run still fails loudly via launchd stderr + exit code) when unset.

- [ ] **Step 3: Write the plist template + installer**

Create `scripts/com.devon.factory-events.plist.template` (mirror of `com.devon.security-scan.plist.template`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.devon.factory-events</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>__HOME__/.claude/bin/factory-events-nightly.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>__HOME__/.factory/nightly.out</string>
    <key>StandardErrorPath</key>
    <string>__HOME__/.factory/nightly.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>__HOME__</string>
        <key>PATH</key>
        <string>/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin</string>
    </dict>
    <key>Nice</key>
    <integer>5</integer>
</dict>
</plist>
```

Create `scripts/install-factory-events-launchd.sh` (copy the structure of `scripts/install-security-scan-launchd.sh`, substituting label `com.devon.factory-events` and the template above — read that file and mirror it exactly: sed `__HOME__` → `$HOME`, write to `~/Library/LaunchAgents/com.devon.factory-events.plist`, `launchctl unload`-if-loaded then `load`). `chmod 755` it.

- [ ] **Step 4: Commit**

```bash
git add deploy/factory-events-db/ scripts/factory-events-nightly.sh scripts/com.devon.factory-events.plist.template scripts/install-factory-events-launchd.sh .gitignore
git commit -m "feat: factory-events deploy assets (compose, nightly script, launchd)"
```

---

### Task 9: Governance registration + README

**Files:**
- Modify: `governance-map.toml` (two `[[tool]]` entries)
- Create: `src/factory_events/README.md`

**Interfaces:**
- Consumes: `make verify` / `make install` (existing governance machinery), everything above (documents it).
- Produces: deployed `~/.claude/bin/factory-events-nightly.sh` under governance; the README that WS-1.2 reads to learn the `emit` seam and actor vocabulary.

- [ ] **Step 1: Register the nightly script in governance-map.toml**

Append to the deployed-artifacts section (exact `lane` value: check an existing non-detect entry first — if the loader validates lanes, use `detect` like the other security-standards artifacts; the map comment defines lanes as detect/mutate/approve and this artifact only reads logs and writes its own store, which is detect-shaped):

```toml
[[tool]]
name = "factory-events-nightly.sh"
lane = "detect"
home_repo = "security-standards"
source = "scripts/factory-events-nightly.sh"
artifact_class = "deployed"
deploy_target = "~/.claude/bin/factory-events-nightly.sh"
mode = "755"
```

Run: `cd ~/Projects/security-standards && make verify`
Expected: passes (if it flags the not-yet-deployed artifact, run `make install` first, then `make verify`).

- [ ] **Step 2: Write the package README**

Create `src/factory_events/README.md`:

```markdown
# factory_events — common audit-event envelope (WS-1.1)

One envelope (`factory-event/v1`, JSON Schema in `schema/`) across all factory
systems; hash-chained append-only JSONL store at `~/.factory/events.jsonl`;
nightly Postgres projection. Spec:
`docs/superpowers/specs/2026-07-02-ws11-audit-event-envelope-design.md`.

## CLI

    PYTHONPATH=src .venv-events/bin/python -m factory_events <cmd>

- `emit --actor A --action x.y --result success|failure|unknown --ref NAME
  [--target T] [--correlation-id C] [--evidence-json '{...}']` — append one
  direct event. **This is the WS-1.2 seam:** runtimes/executors declare their
  identity by emitting events with their registered actor id.
- `adapt --source high-power|change-manager|all [--reanchor]` — translate
  source logs (watermarked, idempotent; `--reanchor` accepts a rewritten
  high-power source file and re-ingests with event_id dedupe).
- `verify [--against-anchor]` — walk the hash chain + schema-validate every
  event; `--against-anchor` also requires the last anchored head (chain_heads
  in the projection) to still be present in the chain.
- `ship [--rebuild]` — upsert into the projection + anchor the current head.
  `--rebuild` truncates `factory_events` (never `chain_heads`) and replays.

## Provisional actor vocabulary (until WS-1.2's registry)

| actor | meaning |
|---|---|
| `claude-code-unattributed` | any Claude Code session on the mini — the high-power hook cannot distinguish interactive from headless; `correlation_id` carries the session UUID |
| `change-window-agent` | change-manager `executor` events — conflates the window agent and the 4AM security executor (both run in the window lane); WS-1.2 separates them |
| `drift-reconciler` | change-manager `sync` / `watchdog` events |
| `security-executor` | reserved for direct emits from the 4AM executor |
| `open-engine-runner` | reserved for the WS-0.6 pilot runner |
| `devon` | human decisions (any SSO email — solo operator) |
| `unknown` | unmappable source actors (e.g. change-manager `api`) |

Raw source actor strings are always preserved verbatim in
`evidence[0].record`; the envelope actor is the honest mapping, never a guess.

## Runtime config — `~/.factory/env` (chmod 600, never tracked)

    CM_BASE_URL=https://change-mgr.alobar.net
    CM_M2M_TOKEN=<from BWS — see .bws-secrets.toml>
    FACTORY_DB_DSN=postgresql://factory_events:<from BWS>@127.0.0.1:5545/factory_events
    FACTORY_HC_PING_URL=<healthchecks.io ping url>  # optional

## Nightly

`com.devon.factory-events` (launchd, 03:30) → `scripts/factory-events-nightly.sh`:
adapt all → verify --against-anchor → ship → healthcheck ping with the head hash.
```

- [ ] **Step 3: Commit**

```bash
git add governance-map.toml src/factory_events/README.md
git commit -m "docs: register factory-events nightly in governance map + package README"
```

---

### Task 10: Provisioning + first run (backfill) — main session, Devon-gated pieces

This task is executed by the MAIN session (not a subagent): it needs BWS access, the backup-integration skill, and Devon's merge of the Task 5 PR. Do the high-power half immediately; the change-manager half after that PR deploys.

**Files:** Create: `.bws-secrets.toml` (repo root). Everything else is local system state.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: live store + projection + nightly job; spec §9 success criteria all checked.

- [ ] **Step 1: Stand up the projection DB**

```bash
cd ~/Projects/security-standards/deploy/factory-events-db
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32))" > .env
chmod 600 .env
docker compose up -d && docker compose ps   # expect: healthy (host Docker engine, NOT ssh orb)
```

- [ ] **Step 2: Store secrets in BWS + write the manifest**

Store the generated DB password and locate/create the change-manager M2M token secret (`bws secret get`/`create` — check whether a change-manager M2M secret already exists in BWS before creating one; the mini-side drift tooling already talks to change-manager, so it likely does). Then create `.bws-secrets.toml` at the repo root listing the consumed secret UUIDs (follow the manifest format documented in `~/Projects/security-standards/docs/` / `genmanifest.py` — reference secrets by stable UUID, names are advisory). NEVER write the secret values into any tracked file — UUIDs only.

- [ ] **Step 3: Write `~/.factory/env`**

```bash
mkdir -p ~/.factory && touch ~/.factory/env && chmod 600 ~/.factory/env
```

Populate (values fetched from BWS at the terminal, not pasted into the transcript): `CM_BASE_URL=https://change-mgr.alobar.net`, `CM_M2M_TOKEN=...`, `FACTORY_DB_DSN=postgresql://factory_events:...@127.0.0.1:5545/factory_events`. Create a `factory-events` check in Healthchecks.io (Devon console step, or via the HC management API with the BWS key `260cc8ad-f170-44cc-a672-b47000df3350`) and add `FACTORY_HC_PING_URL=...`.

- [ ] **Step 4: High-power backfill + first ship**

```bash
cd ~/Projects/security-standards
PYTHONPATH=src .venv-events/bin/python -m factory_events adapt --source high-power
PYTHONPATH=src .venv-events/bin/python -m factory_events verify
set -a; source ~/.factory/env; set +a
PYTHONPATH=src .venv-events/bin/python -m factory_events ship
PYTHONPATH=src .venv-events/bin/python -m factory_events verify --against-anchor
```

Expected: adapt reports the full live-file line count; verify green; ship prints `shipped=N head_seq=... head=...`; anchor check passes.

- [ ] **Step 5: change-manager backfill (AFTER Devon merges + CI deploys the Task 5 PR)**

```bash
PYTHONPATH=src .venv-events/bin/python -m factory_events adapt --source change-manager
PYTHONPATH=src .venv-events/bin/python -m factory_events ship
```

Expected: the full ChangeEvent history lands (hundreds of events); re-run appends 0.

- [ ] **Step 6: Install the LaunchAgent + governance deploy**

```bash
cd ~/Projects/security-standards && make install   # deploys nightly script per governance map
bash scripts/install-factory-events-launchd.sh
launchctl list | grep com.devon.factory-events     # expect: loaded
bash ~/.claude/bin/factory-events-nightly.sh       # one full dry run end-to-end
```

- [ ] **Step 7: Register backups**

Invoke the `backup-integration` skill for `factory-events-db` (local host-engine Postgres → Recipe F, `pg_dump_local` in `backup-mini.sh`) and add `~/.factory/` to the mini config-tree coverage (the JSONL is the source of record — it must be in the nightly mini backup).

- [ ] **Step 8: Success-criteria checklist (spec §9) + proof query**

```bash
docker exec -i factory-events-db psql -U factory_events -d factory_events -c \
  "SELECT source_system, actor, action, count(*) FROM factory_events
   GROUP BY 1,2,3 ORDER BY 1,4 DESC LIMIT 20;"
```

Expected: rows from BOTH `high-power-audit` and `change-manager`. Check off each spec §9 criterion explicitly in the session summary; note criterion 2's day-2 anchor check (`verify --against-anchor` after the first scheduled nightly run) as a follow-up Devon can confirm from the healthcheck payload.

- [ ] **Step 9: Commit + wrap**

```bash
git add .bws-secrets.toml
git commit -m "chore: BWS manifest for factory-events runtime secrets"
```

Then run `/code-review` on the full diff, the `verify` skill (drive the nightly script end-to-end), and `/save`. Update the master-plan Phase 1 section (WS-1.1 → DONE with evidence pointers) and the `project-software-factory` memory.

---

## Verification (whole-plan)

1. `PYTHONPATH=src .venv-events/bin/python -m pytest tests/ -q` — green, including the FACTORY_TEST_DSN integration tests.
2. `ruff check src tests` — clean.
3. Nightly script executed end-to-end once by hand (Task 10 Step 6) with a healthcheck ping observed.
4. The spec §9 proof query returns both source systems.
5. change-manager suite green in its repo; PR open (merge = Devon).
