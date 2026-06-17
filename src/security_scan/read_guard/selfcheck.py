"""Self-check for the PreToolUse read-guard wiring: detect silent failure.

The guard's wiring is machine-local config and fails open, so a broken or
missing guard removes protection with no signal. These checks make that loud.
"""
import json
import os
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
    pre = (settings.get("hooks") or {}).get("PreToolUse") or []
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
