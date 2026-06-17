"""Canonical BWS secret-shape patterns — the single source of truth.

The bare-token shape mirrors the regex in ~/.claude/hooks/bws-write-guard.sh
(kept identical by hand; that hook is bash and cannot import this). Any change
here must be reflected there.
"""
import re

# BWS access token: "0." + 36-char uuid-ish + "." + base64-ish secret (>=20).
BWS_TOKEN_REGEX = r"0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}"
BWS_TOKEN_RX = re.compile(BWS_TOKEN_REGEX)
