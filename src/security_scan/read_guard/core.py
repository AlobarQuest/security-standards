"""Pure read-guard logic: detection, redaction, path amplifier, decision.

No I/O, no side effects — unit-tested without Claude Code. The hook entry
(security_scan.read_guard.hook) wraps this with stdin/stdout + audit logging.
"""
from security_scan.token_shapes import BWS_TOKEN_RX


def scan_for_bws(output: str) -> list[str]:
    """Return all BWS-token substrings present in output (empty if none)."""
    return BWS_TOKEN_RX.findall(output)
