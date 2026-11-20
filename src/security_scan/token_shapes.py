"""Canonical secret-shape patterns — the single source of truth.

``SECRET_SHAPES`` is the portfolio's list of what a secret looks like, as ``(kind, pattern)``
pairs; code-standards' review-prepare imports it to refuse a vendor review that would send one.
The scanner itself enforces only the BWS shape.

The bare-token shape mirrors the regex in ~/.claude/hooks/bws-write-guard.sh
(kept identical by hand; that hook is bash and cannot import this). Any change
here must be reflected there.
"""

import re

# BWS access token: "0." + 36-char uuid-ish + "." + base64-ish secret (>=20).
BWS_TOKEN_REGEX = r"0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}"
BWS_TOKEN_RX = re.compile(BWS_TOKEN_REGEX)

SECRET_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("GitHub token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("Slack token", re.compile(r"xox[abposr]-[A-Za-z0-9-]{10,}")),
    # Not preceded by a lowercase letter, digit or "-", so a slug like "risk-based-..." isn't
    # read as "sk-...", while a key joined to an uppercase name or a "_" ("MYKEYsk-...") is.
    ("OpenAI or Anthropic API key", re.compile(r"(?<![a-z0-9-])sk-(ant-)?[A-Za-z0-9_-]{20,}")),
    ("BWS access token", BWS_TOKEN_RX),
)
