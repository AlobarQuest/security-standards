import json
import os

_DEFAULT = os.path.expanduser("~/.claude/audit/high-power-actions.jsonl")


def log_path() -> str:
    return os.environ.get("READ_GUARD_AUDIT_LOG", _DEFAULT)


def log_event(now, session_id, tool_name, event, matched_path, match_count) -> None:
    rec = {"timestamp": now, "tool": "read-guard", "session_id": session_id or "",
           "event": event, "tool_name": tool_name or "", "matched_path": matched_path,
           "match_count": match_count}
    path = log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass  # never let audit failure break the tool result
