"""Self-check for the PreToolUse read-guard wiring: detect silent failure.

The guard's wiring is machine-local config and fails open, so a broken or
missing guard removes protection with no signal. These checks make that loud.
"""
import json
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass

_DEFAULT_SETTINGS = os.path.expanduser("~/.claude/settings.json")
_DEFAULT_SHIM = os.path.expanduser("~/.claude/hooks/bws-read-guard.sh")


@dataclass
class Result:
    ok: bool
    detail: str


def check_presence(settings_path: str = _DEFAULT_SETTINGS,
                   shim_path: str = _DEFAULT_SHIM) -> Result:
    """Config-level: is the read-guard wired into settings.json and the shim present+executable?"""
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, ValueError) as e:
        return Result(False, f"cannot read settings.json: {e}")
    if not isinstance(settings, dict):
        return Result(False, "settings.json is not a JSON object")
    hooks = settings.get("hooks")
    pre = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    if not isinstance(pre, list):
        return Result(False, "no PreToolUse hooks list in settings.json")
    entry = next((h for h in pre if isinstance(h, dict) and h.get("matcher") == "Read"), None)
    if entry is None:
        return Result(False, "no PreToolUse 'Read' hook entry in settings.json")
    cmds = [hk.get("command") for hk in (entry.get("hooks") or []) if isinstance(hk, dict)]
    if shim_path not in cmds:
        return Result(False, f"PreToolUse 'Read' entry does not point at {shim_path}")
    if not os.path.isfile(shim_path):
        return Result(False, f"shim missing: {shim_path}")
    if not os.access(shim_path, os.X_OK):
        return Result(False, f"shim not executable: {shim_path}")
    return Result(True, "read-guard wired (Read -> shim, executable)")


def _envelope(file_path: str) -> str:
    return json.dumps({"tool_name": "Read", "tool_input": {"file_path": file_path}})


def check_canary(shim_path: str = _DEFAULT_SHIM) -> Result:
    """Functional, end-to-end through the real shim: a token file must be denied,
    a clean file allowed. Builds a synthetic token at runtime; isolates audit writes
    to a temp path; cleans up. Any failure/exception -> not-ok."""
    if not os.path.isfile(shim_path):
        return Result(False, f"shim missing: {shim_path}")
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix="rg-canary-")
        secret = os.path.join(tmpdir, "secret.env")
        clean = os.path.join(tmpdir, "clean.txt")
        token = "0." + str(uuid.uuid4()) + "." + ("A" * 30)  # runtime-built; never a literal
        with open(secret, "w") as f:
            f.write(f"BWS_ACCESS_TOKEN={token}\n")
        with open(clean, "w") as f:
            f.write("nothing here\n")
        env = {**os.environ, "READ_GUARD_AUDIT_LOG": os.path.join(tmpdir, "audit.jsonl")}
        deny = subprocess.run([shim_path], input=_envelope(secret), capture_output=True,
                              text=True, env=env, timeout=10)
        try:
            decision = json.loads(deny.stdout)["hookSpecificOutput"]["permissionDecision"]
        except Exception:
            return Result(False, f"shim emitted no deny decision for a token file (stdout={deny.stdout[:200]!r})")
        if decision != "deny":
            return Result(False, f"shim returned '{decision}', expected 'deny' for a token file")
        allow = subprocess.run([shim_path], input=_envelope(clean), capture_output=True,
                               text=True, env=env, timeout=10)
        if allow.stdout.strip():
            return Result(False, f"shim did not allow a clean file (stdout={allow.stdout[:200]!r})")
        return Result(True, "canary ok (token file denied, clean file allowed)")
    except Exception as e:
        return Result(False, f"canary error: {e}")
    finally:
        if tmpdir:
            for n in ("secret.env", "clean.txt", "audit.jsonl"):
                try:
                    os.remove(os.path.join(tmpdir, n))
                except OSError:
                    pass
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--canary" in argv:
        r1 = check_presence()
        r2 = check_canary()
        print(f"presence: {'OK' if r1.ok else 'FAIL'} - {r1.detail}")
        print(f"canary:   {'OK' if r2.ok else 'FAIL'} - {r2.detail}")
        return 0 if (r1.ok and r2.ok) else 1
    r = check_presence()
    print(f"presence: {'OK' if r.ok else 'FAIL'} - {r.detail}")
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
