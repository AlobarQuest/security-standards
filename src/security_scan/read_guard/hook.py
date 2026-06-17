"""PreToolUse hook for the BWS read-guard. Denies a Read whose target file
contains a BWS token, before the read executes. Thin I/O over core.peek_decision."""
import json
import sys
from datetime import datetime, timezone

from security_scan.read_guard import audit, core

_REDIRECT = ("This file contains a BWS token; the read was blocked so the token does not "
             "enter the transcript. Fetch the value at runtime from the login Keychain "
             "(security find-generic-password ...) or BWS by UUID — do not read the file.")


def run(stdin_text: str, *, now: str) -> str:
    try:
        env = json.loads(stdin_text)
        if not isinstance(env, dict):
            raise ValueError("envelope not an object")
    except Exception:
        return ""  # fail-open: cannot parse -> allow
    tool = env.get("tool_name")
    sid = env.get("session_id")
    fp = (env.get("tool_input") or {}).get("file_path")
    try:
        d = core.peek_decision(fp)
    except Exception:
        audit.log_event(now, sid, tool, "fail_open", fp if isinstance(fp, str) else None, 0)
        return ""
    if d.action == "deny":
        audit.log_event(now, sid, tool, "deny", d.matched_path, d.match_count)
        return json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"{_REDIRECT} (file: {d.matched_path})",
        }})
    return ""  # allow


def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = run(sys.stdin.read(), now=now)
    if out:
        sys.stdout.write(out)
    sys.exit(0)


if __name__ == "__main__":
    main()
