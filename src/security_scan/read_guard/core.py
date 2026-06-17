"""Pure read-guard logic: detection, redaction, path amplifier, decision.

No I/O, no side effects — unit-tested without Claude Code. The hook entry
(security_scan.read_guard.hook) wraps this with stdin/stdout + audit logging.
"""
import re as _re
from dataclasses import dataclass
from security_scan.token_shapes import BWS_TOKEN_RX


SENTINEL = "[REDACTED — BWS token withheld from transcript; fetch at runtime from Keychain/BWS, do not read the file]"


def scan_for_bws(output: str) -> list[str]:
    """Return all BWS-token substrings present in output (empty if none)."""
    return BWS_TOKEN_RX.findall(output)


def redact(output: str, matches: list[str]) -> str:
    """Replace every matched token with SENTINEL; preserve everything else."""
    red = output
    for m in matches:
        red = red.replace(m, SENTINEL)
    return red


# Known secret-file path shapes (v1 amplifier set — modest by design).
_SECRET_PATH_RX = _re.compile(
    r"(/\.config/[^/]+/env\b"      # ~/.config/<workload>/env
    r"|/\.ssh/id_[^/]*"            # ssh private keys
    r"|/\.aws/credentials\b"       # aws creds
    r"|/\.env\b"                   # dotenv files
    r"|/\.netrc\b)"
)


def is_secret_path(path) -> bool:
    if not path:
        return False
    return _SECRET_PATH_RX.search(path) is not None


def extract_path(envelope: dict):
    ti = envelope.get("tool_input") or {}
    if envelope.get("tool_name") == "Read":
        return ti.get("file_path")
    cmd = ti.get("command")
    if isinstance(cmd, str):
        m = _SECRET_PATH_RX.search(cmd)
        if m:
            return cmd[m.start():m.end()]
    return None


SUPPRESS_MESSAGE = ("[OUTPUT WITHHELD by read-guard: a BWS token was present and "
                    "could not be safely redacted. Fetch the value at runtime from "
                    "Keychain/BWS; do not read the file.]")


@dataclass
class Decision:
    action: str            # passthrough | redact | suppress | fail_open
    output: str | None = None
    match_count: int = 0
    matched_path: str | None = None


def decide(envelope: dict) -> Decision:
    path = extract_path(envelope)
    output = envelope.get("tool_output")
    if not isinstance(output, str):                 # cannot read content
        if is_secret_path(path):
            return Decision("suppress", SUPPRESS_MESSAGE, 0, path)
        return Decision("fail_open", None, 0, path)
    try:
        matches = scan_for_bws(output)
    except Exception:                               # scan blew up
        if is_secret_path(path):
            return Decision("suppress", SUPPRESS_MESSAGE, 0, path)
        return Decision("fail_open", None, 0, path)
    if not matches:
        return Decision("passthrough", None, 0, path)
    try:
        return Decision("redact", redact(output, matches), len(matches), path)
    except Exception:
        return Decision("suppress", SUPPRESS_MESSAGE, 0, path)
