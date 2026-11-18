"""Adapter: the Mac's conformance inputs -> one `mac_conformance.reported` event per report.

Orchestrator ADR-0059 Amendment 13, decision items 2, 3 and 5 (D-62 C). The bump driver's
container can't read the Mac's infra-drift report, LaunchAgent plists or Claude hook settings, so
the 03:30 nightly records them in the chain: ids and statuses only, never a description, a
reasoning, a question or any other text from the report, and never a path, a command line or
settings content.

The inputs are read exactly as project-standards reads them (`portfolio.config`, `checkers.
check_infra` and `wiring.py` at `4673d726`), from the same paths and override variables, so the
event holds what the Mac's compliance matrix would see:

- The infra-drift part. The newest `YYYY-MM-DD.json` in the report directory. A report the matrix
  would call "infra report unreadable" is recorded as unreadable, not skipped. A directory with no
  report raises NoReportError, and the CLI appends nothing: the container keeps the newest event
  until it ages out, as the Mac keeps the newest file.
- The wiring part. Each executor in WIRING, present or absent. Reading these never fails: a
  missing plist, or settings that can't be read, are absent, as the matrix reads them.

`source.ref` is the report's `generated_at` (or `unreadable:<file name>`), and the event id
derives from it, so a nightly that finds the same report again appends nothing.
"""

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from factory_events import chain
from factory_events.envelope import deterministic_event_id, make_event

SYSTEM = "mac-conformance-facts"
ACTOR = "mac-conformance-facts"
ACTION = "mac_conformance.reported"
# project-standards' own override variables (`portfolio.config` at 4673d726).
REPORT_DIR_ENV = "INFRADRIFT_REPORT_DIR"
LAUNCHAGENTS_ENV = "LAUNCHAGENTS_DIR"
SETTINGS_ENV = "CLAUDE_SETTINGS_JSON"
# Every `launchagent:` and `hook:` executor a member declares in its PROJECT.md `required_checks`,
# and nothing else (Amendment 13 verify items, the wiring bounds). Read from the 13 repositories
# of orchestrator `docs/operations/membership-seed.toml` at their `main` on 2026-11-18:
# change-manager, project-standards and security-standards declare these five; no other member
# declares one. A member that declares a new one must add it here, or the container reads it as
# not wired.
WIRING = (
    "hook:bws-scan-gate.sh",
    "launchagent:com.devon.change-window",
    "launchagent:com.devon.factory-events",
    "launchagent:com.devon.portfolio-scan",
    "launchagent:com.devon.security-scan",
)
_REPORT_NAME = re.compile(r"\d{4}-\d{2}-\d{2}\.json")


class NoReportError(RuntimeError):
    """No infra-drift report to record. The message names the condition, never a path."""


class UnreadableError(Exception):
    """The newest report is one the matrix would call unreadable. The message names a field,
    never a value. Internal: build() turns it into the unreadable record."""


def report_dir() -> Path:
    override = os.environ.get(REPORT_DIR_ENV)
    return Path(override) if override else Path.home() / "infra-drift" / "reports"


def launchagents_dir() -> Path:
    override = os.environ.get(LAUNCHAGENTS_ENV)
    return Path(override) if override else Path.home() / "Library" / "LaunchAgents"


def settings_path() -> Path:
    override = os.environ.get(SETTINGS_ENV)
    return Path(override) if override else Path.home() / ".claude" / "settings.json"


def newest_report(directory: Path) -> Path:
    """The newest report by file name, as `checkers._latest_infra_report` picks it."""
    if not directory.is_dir():
        raise NoReportError("no infra-drift report directory")
    try:
        names = [p for p in directory.iterdir() if _REPORT_NAME.fullmatch(p.name)]
    except OSError as exc:
        raise NoReportError(f"report directory unreadable ({type(exc).__name__})") from None
    candidates = [p for p in names if p.is_file()]
    if not candidates:
        raise NoReportError("no infra-drift report")
    return max(candidates, key=lambda p: p.name)


def _envelope_time(value: object) -> str:
    """`generated_at` as the matrix parses it, written in the envelope's UTC form. A naive time is
    system-local, as `check_infra` treats it."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        parsed = parsed.astimezone() if parsed.tzinfo is None else parsed
        utc = parsed.astimezone(UTC)
    except ValueError, OverflowError:
        raise UnreadableError("generated_at is not an ISO time") from None
    return _utc_text(utc)


def _utc_text(moment: datetime) -> str:
    """The envelope's form: isoformat pads the year and writes microseconds only when set."""
    return moment.astimezone(UTC).replace(tzinfo=None).isoformat() + "Z"


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _instance_ok(instance: object) -> bool:
    """`not checkers._infra_instance_unusable`: a malformed instance never reads as ok."""
    if not isinstance(instance, dict) or not instance.get("ok"):
        return False
    return isinstance(instance.get("proposals", []), list)


def _proposals(name: str, instance: object) -> list[dict]:
    """Each proposal's id and its target's UUID and name: the only fields the matrix matches."""
    if not isinstance(instance, dict) or not isinstance(instance.get("proposals", []), list):
        return []
    items = []
    for proposal in instance.get("proposals", []):
        if not isinstance(proposal, dict):
            continue
        target = proposal.get("target")
        target = target if isinstance(target, dict) else {}
        items.append(
            {
                "type": "infra-drift-proposal",
                "instance": name,
                "id": _string_or_none(proposal.get("id")),
                "target": {
                    "uuid": _string_or_none(target.get("uuid")),
                    "name": _string_or_none(target.get("name")),
                },
            }
        )
    return items


def _read_report(path: Path) -> tuple[str, list[dict], str]:
    """The report's (generated_at, evidence, result), or UnreadableError."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise UnreadableError(f"report unreadable ({type(exc).__name__})") from None
    except json.JSONDecodeError:
        raise UnreadableError("report is not JSON") from None
    except RecursionError:
        raise UnreadableError("report is nested too deeply to parse") from None
    if not isinstance(data, dict) or "generated_at" not in data or "instances" not in data:
        raise UnreadableError("report is not an object with generated_at and instances")
    instances = data["instances"]
    if not isinstance(instances, dict):
        raise UnreadableError("instances is not an object")
    generated_at = _envelope_time(data["generated_at"])
    evidence: list[dict] = [{"type": "infra-drift-report", "generated_at": generated_at}]
    oks = {name: _instance_ok(instance) for name, instance in instances.items()}
    evidence += [{"type": "infra-drift-instance", "name": n, "ok": ok} for n, ok in oks.items()]
    for name, instance in instances.items():
        evidence += _proposals(name, instance)
    return generated_at, evidence, "success" if all(oks.values()) else "unknown"


def _hook_commands(hooks: object):
    """Every registered hook command string, walked as `wiring._iter_hook_commands` walks it."""
    if not isinstance(hooks, dict):
        return
    for entries in hooks.values():
        for entry in entries if isinstance(entries, list) else []:
            inner = entry.get("hooks") if isinstance(entry, dict) else None
            for hook in inner if isinstance(inner, list) else []:
                if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                    yield hook["command"]


def _registered_hooks(path: Path) -> set[str]:
    """The basenames of every token of every hook command: `wiring._hook_name_registered`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError, RecursionError:
        # The matrix reads unreadable settings as "not registered" (`wiring._verify_hook`), and so
        # does the event: absent is the status, not an error.
        return set()
    hooks = data.get("hooks", {}) if isinstance(data, dict) else None
    return {PurePosixPath(token).name for cmd in _hook_commands(hooks) for token in cmd.split()}


def wiring_evidence() -> list[dict]:
    hooks = _registered_hooks(settings_path())
    agents = launchagents_dir()
    items = []
    for executor in WIRING:
        kind, _, name = executor.partition(":")
        present = name in hooks if kind == "hook" else (agents / f"{name}.plist").is_file()
        items.append(
            {"type": "wiring", "executor": executor, "status": "present" if present else "absent"}
        )
    return items


def build(now: datetime | None = None) -> tuple[str, str, list[dict], str]:
    """The event's (source.ref, timestamp, evidence, result), or NoReportError.

    An unreadable report has no `generated_at`, so its record takes the nightly's run time, which
    is later than any earlier report's: the reader takes it over the previous day's event."""
    path = newest_report(report_dir())
    try:
        generated_at, report, result = _read_report(path)
        ref, timestamp = generated_at, generated_at
    except UnreadableError as exc:
        report = [{"type": "infra-drift-report-unreadable", "reason": str(exc)}]
        ref, result = f"unreadable:{path.name}", "unknown"
        timestamp = _utc_text((now or datetime.now(UTC)).replace(microsecond=0))
    return ref, timestamp, report + wiring_evidence(), result


def adapt(now: datetime | None = None) -> int:
    """Append the Mac's facts as one event. Raises NoReportError when there is no report (append
    nothing), EnvelopeError for a code or deploy fault, ChainError for the chain."""
    ref, timestamp, evidence, result = build(now)
    event_id = deterministic_event_id(SYSTEM, ref)
    if event_id in chain.event_ids():
        return 0
    chain.append_event(
        make_event(
            event_id=event_id,
            timestamp=timestamp,
            actor=ACTOR,
            action=ACTION,
            target=None,
            result=result,
            evidence=evidence,
            source={"system": SYSTEM, "ref": ref},
        )
    )
    return 1
