"""Pure read-guard logic: detection, redaction, path amplifier, decision.

No I/O, no side effects — unit-tested without Claude Code. The hook entry
(security_scan.read_guard.hook) wraps this with stdin/stdout + audit logging.
"""
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
