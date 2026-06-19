from __future__ import annotations

import os
from pathlib import Path

from .loader import Manifest, Repo

START = "<!-- governance:start -->"
END = "<!-- governance:end -->"

_BWS_SKELETON = (
    "# .bws-secrets.toml — BWS secret UUIDs this repo consumes (NEVER token values).\n"
    "# Stable UUIDs only; resolved at runtime from BWS_ACCESS_TOKEN.\n"
    "# [[secret]]\n"
    '# uuid = "00000000-0000-0000-0000-000000000000"\n'
    '# name = "EXAMPLE_API_KEY"   # human label; the UUID is authoritative\n'
)


def _claude_md(repo: Repo) -> Path:
    return Path(os.path.expanduser(repo.path)) / "CLAUDE.md"


def ensure_bws_manifest(repo: Repo) -> str:
    if not repo.uses_bws:
        return "skip"
    path = Path(os.path.expanduser(repo.path)) / ".bws-secrets.toml"
    if path.exists():
        return "exists"
    path.write_text(_BWS_SKELETON)
    return "created"


def render_ownership(manifest: Manifest) -> str:
    homes = {r.name: r for r in manifest.repos}
    lines: list[str] = [
        "# Control-plane ownership map",
        "",
        "<!-- Generated from governance-map.toml in security-standards. Do not hand-edit. -->",
        "<!-- Regenerate: cd ~/Projects/security-standards && make ownership -->",
        "",
        "**Lane model:** security-standards DETECTS · infraops-mcp-server MUTATES · "
        "change-manager APPROVES.",
        "",
        "**Gating scope (be honest):** the *approve* lane (change-manager) gates the "
        "**autonomous** 4am drift executor only. An **interactive** session reaches infraops "
        "mutation tools directly — guardrail-gated (`permissions.deny` + high-power-gate hook "
        "+ audit log), not approval-gated.",
        "",
        "## Deployed artifacts → source of truth",
        "",
        "| Artifact | Lane | Source | Deployed to |",
        "| --- | --- | --- | --- |",
    ]
    for t in manifest.tools:
        if t.artifact_class != "deployed":
            continue
        home = homes[t.home_repo].path
        lines.append(f"| `{t.name}` | {t.lane} | `{home}/{t.source}` | `{t.deploy_target}` |")
    lines += [
        "",
        "To change any deployed artifact: edit the source, then "
        "`cd ~/Projects/security-standards && make install`.",
        "",
        "## Tool-home repos",
        "",
    ]
    for r in manifest.repos:
        if r.cls != "tool-home":
            continue
        owned = ", ".join(f"`{o}`" for o in r.owns) or "(none)"
        lines.append(f"- **{r.name}** ({r.lane}) — owns: {owned}")
    consumers = [r.name for r in manifest.repos if r.cls == "consumer"]
    lines += [
        "",
        "## Consumer repos",
        "",
        "Governed by **security-standards** (detect). Enforcement is automatic via the global "
        "hooks (`bws-write-guard`, `bws-read-guard`, `bws-scan-gate` in `~/.claude/hooks/`). "
        "Audit on demand via the `security-standards` skill. BWS usage is declared per-repo in "
        "`.bws-secrets.toml`.",
        "",
    ]
    if consumers:
        lines.append(", ".join(consumers))
    return "\n".join(lines).rstrip() + "\n"


def write_ownership(manifest: Manifest, path) -> str:
    p = Path(os.path.expanduser(str(path)))
    desired = render_ownership(manifest)
    if p.exists() and p.read_text() == desired:
        return "unchanged"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(desired)
    return "written"


def verify_ownership(manifest: Manifest, path) -> str:
    p = Path(os.path.expanduser(str(path)))
    if not p.exists():
        return "missing"
    return "ok" if p.read_text() == render_ownership(manifest) else "drift"


def source_header_lines(tool, manifest: Manifest) -> list[str]:
    home = next(r.path for r in manifest.repos if r.name == tool.home_repo)
    return [
        f"# Source of truth: {home}/{tool.source} (deployed → {tool.deploy_target})",
        "# Edit here, not in place; then: cd ~/Projects/security-standards && make install",
    ]


def verify_headers(manifest: Manifest) -> list[tuple[str, str]]:
    from .deploy import _source_path
    problems: list[tuple[str, str]] = []
    for t in manifest.tools:
        if t.artifact_class != "deployed":
            continue
        try:
            text = _source_path(t, manifest).read_text()
        except (FileNotFoundError, KeyError):
            problems.append((t.name, "missing"))
            continue
        if source_header_lines(t, manifest)[0] in text:
            continue
        problems.append((t.name, "wrong" if "# Source of truth:" in text else "missing"))
    return problems


def strip_stanza(repo: Repo) -> str:
    path = _claude_md(repo)
    if not path.exists():
        return "missing"
    text = path.read_text()
    if START not in text or END not in text:
        return "absent"
    s = text.index(START)
    e = text.index(END) + len(END)
    before = text[:s].rstrip()
    after = text[e:].lstrip()
    if before and after:
        result = before + "\n\n" + after
    else:
        result = before or after
    result = (result.rstrip() + "\n") if result.strip() else ""
    path.write_text(result)
    return "stripped"
