"""Pure read-guard logic: BWS token detection. No I/O, no side effects."""
import os
from dataclasses import dataclass

from security_scan.token_shapes import BWS_TOKEN_RX


def scan_for_bws(output: str) -> list[str]:
    """Return all BWS-token substrings present in output (empty if none)."""
    return BWS_TOKEN_RX.findall(output)


@dataclass
class PeekResult:
    action: str            # "deny" | "allow"
    matched_path: str | None = None
    match_count: int = 0


def peek_decision(file_path: str | None, *, size_cap: int = 262144) -> PeekResult:
    """Decide whether a Read of file_path should be denied (file contains a BWS
    token) or allowed. Fail-open: any uncertainty returns allow."""
    if not isinstance(file_path, str) or not file_path:
        return PeekResult("allow")
    try:
        if not os.path.isfile(file_path):
            return PeekResult("allow", file_path)
        if os.path.getsize(file_path) > size_cap:
            return PeekResult("allow", file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return PeekResult("allow", file_path)
    matches = scan_for_bws(content)
    if matches:
        return PeekResult("deny", file_path, len(matches))
    return PeekResult("allow", file_path)
