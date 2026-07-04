"""Read-guard logic: BWS token detection and file-content peek. Fail-open."""

# Deferred annotations: this module is executed by the ambient `python3` of the
# Claude Code hook environment (system Python 3.9 under launchd), below the 3.12
# dev floor. `from __future__ import annotations` keeps PEP 604 `X | None`
# annotations from being evaluated at import, so the guard never crashes (and
# silently fails open) on an older interpreter. See test_read_guard_py39_compat.
from __future__ import annotations

import os
from dataclasses import dataclass

from security_scan.token_shapes import BWS_TOKEN_RX


def scan_for_bws(output: str) -> list[str]:
    """Return all BWS-token substrings present in output (empty if none)."""
    return BWS_TOKEN_RX.findall(output)


@dataclass
class PeekResult:
    action: str  # "deny" | "allow"
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
        with open(file_path, encoding="utf-8") as f:
            content = f.read(size_cap + 1)
        if len(content) > size_cap:
            return PeekResult("allow", file_path)
    except (OSError, UnicodeDecodeError):
        return PeekResult("allow", file_path)
    matches = scan_for_bws(content)
    if matches:
        return PeekResult("deny", file_path, len(matches))
    return PeekResult("allow", file_path)
