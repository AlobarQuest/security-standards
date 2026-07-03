"""Adapter: ~/.claude/audit/high-power-actions.jsonl -> factory-events store.

Watermark = {line_count, content_sha256} where content_sha256 hashes all processed
lines — any rewrite in the ingested region is detected. A hash mismatch means the
source was rewritten/rotated: fail loudly; --reanchor re-ingests from line 0 and the
deterministic event_id (sha256 of the source line) dedupes against the store.
Backfill scope is the live file only (spec §4 — .bak snapshots declined).
"""

import hashlib
import json
import os
from pathlib import Path

from factory_events import store
from factory_events.envelope import EnvelopeError, deterministic_event_id, make_event

DEFAULT_SOURCE = Path.home() / ".claude" / "audit" / "high-power-actions.jsonl"
SYSTEM = "high-power-audit"
_TARGET_KEYS = ("command", "host", "domain", "to", "name", "uuid")


class WatermarkError(RuntimeError):
    """Source file changed under the watermark — refuse to guess."""


class SourceError(RuntimeError):
    """A source line could not be parsed/mapped — refuse to guess or skip."""


def _watermark_path() -> Path:
    return store.state_dir() / "high-power.json"


def _load_watermark() -> dict | None:
    path = _watermark_path()
    return json.loads(path.read_text()) if path.exists() else None


def _save_watermark(lines: list[str]) -> None:
    path = _watermark_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Hash all lines together to detect any rewriting
    content = "\n".join(lines)
    mark = {
        "line_count": len(lines),
        "content_sha256": hashlib.sha256(content.encode()).hexdigest() if lines else None,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(mark, indent=1))
    os.replace(tmp, path)


def _extract_target(args_summary: str) -> str | None:
    # Best-effort target: first present key in priority order;
    # adapters own their target conventions.
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
        action=f"tool.{name.lower()}",
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
        if len(lines) < count:
            raise WatermarkError(
                f"{source} changed under the watermark (rewritten/rotated/truncated); "
                "re-run with --reanchor to accept the file as a new baseline"
            )
        # Check if any of the processed lines changed
        if count > 0:
            content = "\n".join(lines[:count])
            if hashlib.sha256(content.encode()).hexdigest() != mark["content_sha256"]:
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
        try:
            event = _map_line(raw_line, lineno=offset)
        except (json.JSONDecodeError, KeyError, EnvelopeError) as exc:
            raise SourceError(
                f"{source}:{offset}: unparseable/unmappable source line: {exc}"
            ) from exc
        if event["event_id"] in known:
            continue
        store.append_event(event)
        known.add(event["event_id"])
        appended += 1
    _save_watermark(lines)
    return appended
