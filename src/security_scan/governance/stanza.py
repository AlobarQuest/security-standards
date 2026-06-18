from __future__ import annotations

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
