"""Adapter: the portfolio scan's feed -> one `portfolio.scanned` event per scan.

Orchestrator ADR-0059 Amendment 11, decision item 2 (D-56 A). The 03:00 scan writes
`~/.portfolio/portfolio-feed.json` (project-standards `src/portfolio/feed.py`); this adapter
copies it, unchanged, into the chain for the work carrier to read. It reads no member record and
never adds, drops, renames or re-cases a row or a status.

The feed's whole contract is checked before the event is built, and a feed that breaks it raises
FeedError, whose message names the field and never its content. The CLI prints that reason and
appends nothing (decision item 6). The event id derives from the scan time alone, so a nightly
that finds the same feed again appends nothing.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from factory_events import chain
from factory_events.envelope import deterministic_event_id, make_event

SYSTEM = "portfolio-scan"
ACTOR = "portfolio-scan"
ACTION = "portfolio.scanned"
FEED_SCHEMA = "portfolio-feed.v1"
FEED_ENV = "FACTORY_EVENTS_PORTFOLIO_FEED"
# The four ids the feed may carry, the work carrier's CAPABILITY_CHECKS and PERMISSION_CHECKS
# (project-standards FEED_CHECKS). Their status values are not a closed set: copy them.
CHECK_IDS = frozenset(
    {"runner.caller", "factory.secrets", "factory.landing_known", "factory.pat_access"}
)
_FEED_KEYS = frozenset({"schema", "scanned_at", "member_record_unreadable", "repositories"})
_ROW_KEYS = frozenset({"repository", "checks"})
_SCANNED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
# The producer's own shape (project-standards `onboard_checks.repo_slug`, lowercased): one slash,
# no whitespace either side. Matched with fullmatch: `$` would also match before a newline.
_REPOSITORY = re.compile(r"[^/\s]+/[^/\s]+")


class FeedError(RuntimeError):
    """The feed is missing, unreadable, or breaks its contract. The message names a field,
    never a value."""


def feed_path() -> Path:
    override = os.environ.get(FEED_ENV)
    return Path(override) if override else Path.home() / ".portfolio" / "portfolio-feed.json"


def _read(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FeedError("no feed file") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise FeedError(f"feed unreadable ({type(exc).__name__})") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise FeedError("feed is not JSON") from None
    except RecursionError:
        raise FeedError("feed is nested too deeply to parse") from None


def _check_scanned_at(value: object) -> str:
    if not isinstance(value, str) or not _SCANNED_AT.fullmatch(value):
        raise FeedError("scanned_at is not a YYYY-MM-DDTHH:MM:SSZ time")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise FeedError("scanned_at is not a calendar time") from None
    return value


def _check_rows(rows: object) -> list[dict]:
    if not isinstance(rows, list):
        raise FeedError("repositories is not a list")
    seen: set[str] = set()
    for index, row in enumerate(rows):
        where = f"repositories[{index}]"
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            raise FeedError(f"{where} is not exactly repository and checks")
        repository = row["repository"]
        if (
            not isinstance(repository, str)
            or not _REPOSITORY.fullmatch(repository)
            or repository != repository.lower()
        ):
            raise FeedError(f"{where}.repository is not a lowercased owner/repo")
        if repository in seen:
            raise FeedError(f"{where}.repository repeats an earlier row")
        seen.add(repository)
        checks = row["checks"]
        if not isinstance(checks, dict):
            raise FeedError(f"{where}.checks is not an object")
        if not set(checks) <= CHECK_IDS:
            raise FeedError(f"{where}.checks has an id outside the four")
        if not all(isinstance(status, str) for status in checks.values()):
            raise FeedError(f"{where}.checks has a status that is not a string")
    return rows


def load_feed(path: Path) -> tuple[str, list[dict], str]:
    """The feed's (scanned_at, evidence, result), or FeedError. Validates the whole feed first."""
    feed = _read(path)
    if not isinstance(feed, dict) or set(feed) != _FEED_KEYS:
        raise FeedError("feed is not exactly the four portfolio-feed.v1 keys")
    if feed["schema"] != FEED_SCHEMA:
        raise FeedError(f"schema is not {FEED_SCHEMA}")
    scanned_at = _check_scanned_at(feed["scanned_at"])
    reason = feed["member_record_unreadable"]
    rows = _check_rows(feed["repositories"])
    if reason is None:
        return scanned_at, [{"type": "repository", **row} for row in rows], "success"
    if not isinstance(reason, str):
        raise FeedError("member_record_unreadable is neither null nor a reason string")
    if rows:
        raise FeedError("repositories is not empty for an unreadable member record")
    return scanned_at, [{"type": "member-record-unreadable", "reason": reason}], "unknown"


def adapt(path: Path | None = None) -> int:
    """Append the feed's scan as one event. Raises FeedError for a bad feed (append nothing),
    EnvelopeError for a code or deploy fault, ChainError for the chain."""
    scanned_at, evidence, result = load_feed(path or feed_path())
    event = make_event(
        event_id=deterministic_event_id(SYSTEM, scanned_at),
        timestamp=scanned_at,
        actor=ACTOR,
        action=ACTION,
        target=None,
        result=result,
        evidence=evidence,
        source={"system": SYSTEM, "ref": scanned_at},
    )
    if event["event_id"] in chain.event_ids():
        return 0
    chain.append_event(event)
    return 1
