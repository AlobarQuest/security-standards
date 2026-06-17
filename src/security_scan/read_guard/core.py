"""Pure read-guard logic: BWS token detection. No I/O, no side effects."""
from security_scan.token_shapes import BWS_TOKEN_RX


def scan_for_bws(output: str) -> list[str]:
    """Return all BWS-token substrings present in output (empty if none)."""
    return BWS_TOKEN_RX.findall(output)
