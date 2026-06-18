from __future__ import annotations

import os
from pathlib import Path

from .loader import Manifest, Repo

START = "<!-- governance:start -->"
END = "<!-- governance:end -->"

_HEADER = (
    "## Security & Governance\n\n"
    "<!-- Generated from governance-map.toml in security-standards. Do not hand-edit. -->\n"
    "<!-- Regenerate: cd ~/Projects/security-standards && make sync -->\n"
)


def render_stanza(repo: Repo, manifest: Manifest) -> str:
    lines = [_HEADER]
    if repo.cls == "tool-home":
        owned = ", ".join(f"`{o}`" for o in repo.owns) or "(none)"
        cons = ", ".join(repo.consumers) or "(none)"
        lines += [
            "**Build-agent class:** tool-home — you open this repo to *develop* its tools.",
            f"**Lane:** {repo.lane} (detect / mutate / approve).",
            f"**Owns:** {owned}.",
            "**Deploy:** `make install`  •  **Verify:** `make verify`.",
            f"**Consumers:** {cons}.",
        ]
    else:  # consumer
        lines += [
            "**Build-agent class:** consumer — governed by **security-standards** (lane: detect).",
            "**Enforcement is automatic** via global hooks "
            "(`bws-write-guard`, `bws-read-guard`, `bws-scan-gate` in `~/.claude/hooks/`). "
            "You run nothing.",
            "**Audit on demand:** the `security-standards` skill, or "
            "`python -m security_scan.cli . --category security`.",
        ]
        if repo.uses_bws:
            lines.append(
                "**BWS usage** is declared in `.bws-secrets.toml` (stable UUIDs only — never token values)."
            )
    return "\n".join(lines).rstrip() + "\n"


def block(repo: Repo, manifest: Manifest) -> str:
    return f"{START}\n{render_stanza(repo, manifest)}{END}\n"


_BWS_SKELETON = (
    "# .bws-secrets.toml — BWS secret UUIDs this repo consumes (NEVER token values).\n"
    "# Stable UUIDs only; resolved at runtime from BWS_ACCESS_TOKEN.\n"
    "# [[secret]]\n"
    '# uuid = "00000000-0000-0000-0000-000000000000"\n'
    '# name = "EXAMPLE_API_KEY"   # human label; the UUID is authoritative\n'
)


def _claude_md(repo: Repo) -> Path:
    return Path(os.path.expanduser(repo.path)) / "CLAUDE.md"


def sync_stanza(repo: Repo, manifest: Manifest) -> str:
    path = _claude_md(repo)
    desired = block(repo, manifest)
    text = path.read_text() if path.exists() else ""
    if START in text and END in text:
        s = text.index(START)
        e = text.index(END) + len(END)
        if text[s:e] == desired.rstrip("\n"):
            return "unchanged"
        updated = text[:s] + desired.rstrip("\n") + text[e:]
        path.write_text(updated)
        return "written"
    prefix = (text.rstrip() + "\n\n") if text.strip() else ""
    path.write_text(prefix + desired)
    return "created"


def verify_stanza(repo: Repo, manifest: Manifest) -> str:
    path = _claude_md(repo)
    if not path.exists():
        return "missing"
    text = path.read_text()
    if START not in text or END not in text:
        return "missing"
    s = text.index(START)
    e = text.index(END) + len(END)
    return "ok" if text[s:e] == block(repo, manifest).rstrip("\n") else "drift"


def ensure_bws_manifest(repo: Repo) -> str:
    if not repo.uses_bws:
        return "skip"
    path = Path(os.path.expanduser(repo.path)) / ".bws-secrets.toml"
    if path.exists():
        return "exists"
    path.write_text(_BWS_SKELETON)
    return "created"
