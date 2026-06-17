"""PostToolUse hook entry for the BWS read-guard. Thin I/O over core.decide."""
import json
import sys
from datetime import datetime, timezone

from security_scan.read_guard import audit, core

_CONTEXT = ("A BWS token was withheld from this output by the read-guard. Fetch it at "
            "runtime from the login Keychain (security find-generic-password ...) or BWS "
            "— do not read the file. See ~/.claude/CLAUDE.md 'Secure Way of Working'.")


def run(stdin_text: str, *, now: str) -> str:
    try:
        env = json.loads(stdin_text)
        if not isinstance(env, dict):
            raise ValueError("envelope not an object")
    except Exception:
        # Cannot even parse the envelope: fail open, log the gap, never block.
        audit.log_event(now, None, None, "fail_open_gap", None, 0)
        return ""

    d = core.decide(env)
    sid = env.get("session_id")
    tool = env.get("tool_name")

    if d.action == "passthrough":
        return ""
    if d.action == "fail_open":
        audit.log_event(now, sid, tool, "fail_open_gap", d.matched_path, 0)
        return ""

    # redact or suppress -> emit a rewrite + log it
    audit.log_event(now, sid, tool, d.action, d.matched_path, d.match_count)
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "updatedToolOutput": d.output,
        "additionalContext": _CONTEXT,
    }})


def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = run(sys.stdin.read(), now=now)
    if out:
        sys.stdout.write(out)
    sys.exit(0)


if __name__ == "__main__":
    main()
