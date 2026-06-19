# Slim the Governance Projection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the drift-prone per-repo `CLAUDE.md` governance stanzas with one generated `~/.claude/OWNERSHIP.md` ownership map plus self-documenting source headers, while keeping `governance-map.toml` as the single source of truth.

**Architecture:** Keep the generation engine; change its projection target. The `governance` package gains an ownership-map generator, a source-header verifier, and a one-shot stanza-stripper; the per-repo stanza projection (`render_stanza`/`sync_stanza`/`verify_stanza`) is removed. `make install` deploys → reconciles (prong 1, already built) → regenerates `OWNERSHIP.md` → verifies.

**Tech Stack:** Python 3.12+, `tomllib`, `pytest`, GNU Make, bash.

## Global Constraints

- **Python 3.12+** (uses `tomllib`, `str | Path` unions).
- **TDD:** failing test → run-it-fails → implement → run-it-passes → commit. Frequent commits.
- **Deploy is DEFERRED.** Do NOT run a real `make install` during implementation — it would deploy the item-#3 marker scanner (intentionally held) to the live control plane. Consequence: full `make verify` will FAIL on `artifact drift` until Devon's deferred deploy. During implementation, verify header logic with the targeted command given in Task 4, and rely on `pytest` (which uses tmp paths). The real deploy + migration is Task 7 (a runbook Devon runs, NOT the implementer).
- **Do NOT restructure `governance-map.toml`'s `[[tool]]`/`[[repo]]` entries** — prong 2 (infraops, in flight) may read them. Comment/doc edits only, if any.
- **Canonical source-header (verbatim — used by Task 3's generator AND Task 4's hand-added headers; they MUST be byte-identical):**
  - Line 1: `# Source of truth: <repo.path>/<tool.source> (deployed → <tool.deploy_target>)`
    where `<repo.path>` is the home repo's `path` field verbatim (e.g. `~/Projects/security-standards`, unexpanded).
  - Line 2: `# Edit here, not in place; then: cd ~/Projects/security-standards && make install`
- **OWNERSHIP.md default path:** `~/.claude/OWNERSHIP.md`.
- **The 5 deployed artifacts** (`artifact_class = "deployed"` in `governance-map.toml`):
  | tool name | source | deploy_target |
  |---|---|---|
  | `security-scan.sh` | `scripts/security-scan.sh` | `~/.claude/bin/security-scan.sh` |
  | `skills-security-scan.sh` | `scripts/skills-security-scan.sh` | `~/.claude/bin/skills-security-scan.sh` |
  | `bws-write-guard.sh` | `hooks/bws-write-guard.sh` | `~/.claude/hooks/bws-write-guard.sh` |
  | `bws-read-guard.sh` | `hooks/bws-read-guard.sh` | `~/.claude/hooks/bws-read-guard.sh` |
  | `bws-scan-gate.sh` | `hooks/bws-scan-gate.sh` | `~/.claude/hooks/bws-scan-gate.sh` |
- **The 10 stanza-bearing repos** (for `strip-stanzas`): tool-home — security-standards, infraops-mcp-server, change-manager; consumers — Contacts, FacelessTT, imap-mcp-server, InfraManager, rental-investment-calculator, VideoCreator, vps-backup.
- **`--artifacts-only` is redefined** to mean "deployed-faithfulness" = artifacts + source headers (NOT OWNERSHIP.md freshness). The scanner's Check-14 line (`verify --artifacts-only`) stays byte-identical and gains header coverage for free.

## File Structure

- `src/security_scan/governance/ownership.py` — (renamed from `stanza.py`) ownership map + header verify + stanza strip + BWS manifest. One responsibility: project the map into the world (non-deploy artifacts) and verify those projections.
- `src/security_scan/governance/__main__.py` — CLI dispatch: `deploy`, `verify`, `ownership`, `strip-stanzas`.
- `src/security_scan/governance/deploy.py` — unchanged (deploy + reconcile + artifact verify). `_source_path` reused by `ownership.verify_headers`.
- `Makefile` — `install`, `verify`, `ownership`, `strip-stanzas`, `test`.
- `scripts/security-scan.sh` — gains a source header (Task 4); Check-14 line unchanged.
- `tests/test_governance_ownership.py` — (renamed from `test_governance_stanza.py`) ownership/header/strip/bws tests.
- `tests/test_governance_deploy.py` — one CLI test fixture updated (Task 6).

---

### Task 1: Rename `stanza.py` → `ownership.py` (mechanical, no behavior change)

**Files:**
- Rename: `src/security_scan/governance/stanza.py` → `src/security_scan/governance/ownership.py`
- Modify: `src/security_scan/governance/__main__.py` (import line)
- Rename: `tests/test_governance_stanza.py` → `tests/test_governance_ownership.py`

**Interfaces:**
- Produces: module `security_scan.governance.ownership` exposing the current symbols unchanged (`START`, `END`, `render_stanza`, `block`, `sync_stanza`, `verify_stanza`, `ensure_bws_manifest`, `_BWS_SKELETON`, `_claude_md`).

- [ ] **Step 1: Rename the module and test file (preserve history)**

```bash
cd ~/Projects/security-standards
git mv src/security_scan/governance/stanza.py src/security_scan/governance/ownership.py
git mv tests/test_governance_stanza.py tests/test_governance_ownership.py
```

- [ ] **Step 2: Update the import in `__main__.py`**

Change the stanza import line to:

```python
from .ownership import sync_stanza, verify_stanza, ensure_bws_manifest
```

- [ ] **Step 3: Update the import in the renamed test file**

In `tests/test_governance_ownership.py`, change both occurrences of `from security_scan.governance.stanza import ...` to `from security_scan.governance.ownership import ...`.

- [ ] **Step 4: Run the full suite to verify the rename is clean**

Run: `PYTHONPATH=src python3 -m pytest -q`
Expected: PASS (same count as before — 100).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(governance): rename stanza module to ownership (no behavior change)"
```

---

### Task 2: Ownership map — `render_ownership` / `write_ownership` / `verify_ownership`

**Files:**
- Modify: `src/security_scan/governance/ownership.py`
- Test: `tests/test_governance_ownership.py`

**Interfaces:**
- Consumes: `Manifest`, `Tool`, `Repo` from `.loader`.
- Produces:
  - `render_ownership(manifest: Manifest) -> str`
  - `write_ownership(manifest: Manifest, path: str | Path) -> str` (`"unchanged"` | `"written"`)
  - `verify_ownership(manifest: Manifest, path: str | Path) -> str` (`"ok"` | `"drift"` | `"missing"`)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_governance_ownership.py`:

```python
from security_scan.governance.ownership import (
    render_ownership, write_ownership, verify_ownership,
)
from security_scan.governance.loader import Manifest, Tool, Repo


def _own_manifest():
    tool = Tool(name="security-scan.sh", lane="detect", home_repo="security-standards",
                source="scripts/security-scan.sh", artifact_class="deployed",
                deploy_target="~/.claude/bin/security-scan.sh", mode="755")
    th = Repo(name="security-standards", path="~/Projects/security-standards",
              cls="tool-home", lane="detect", owns=["security-scan.sh"])
    cons = Repo(name="FacelessTT", path="~/Projects/FacelessTT", cls="consumer", uses_bws=True)
    return Manifest(tools=[tool], repos=[th, cons], runtime_dirs=[])


def test_render_ownership_has_artifact_lane_and_gating():
    s = render_ownership(_own_manifest())
    assert "security-scan.sh" in s
    assert "~/.claude/bin/security-scan.sh" in s
    assert "~/Projects/security-standards/scripts/security-scan.sh" in s
    # honest-gating note migrated from item #2
    assert "autonomous" in s.lower() and "interactive" in s.lower()
    assert "guardrail-gated" in s.lower()
    # repos surfaced
    assert "security-standards" in s and "FacelessTT" in s


def test_write_ownership_idempotent(tmp_path):
    m = _own_manifest()
    p = tmp_path / "OWNERSHIP.md"
    assert write_ownership(m, p) == "written"
    assert write_ownership(m, p) == "unchanged"


def test_verify_ownership_missing_then_ok_then_drift(tmp_path):
    m = _own_manifest()
    p = tmp_path / "OWNERSHIP.md"
    assert verify_ownership(m, p) == "missing"
    write_ownership(m, p)
    assert verify_ownership(m, p) == "ok"
    p.write_text(p.read_text() + "tamper\n")
    assert verify_ownership(m, p) == "drift"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/test_governance_ownership.py -k ownership -v`
Expected: FAIL with `ImportError: cannot import name 'render_ownership'`.

- [ ] **Step 3: Implement the three functions**

Add to `src/security_scan/governance/ownership.py` (keep existing imports; ensure `import os` and `from pathlib import Path` and `from .loader import Manifest, Repo` are present — add `Tool` is not needed here):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/test_governance_ownership.py -k ownership -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/governance/ownership.py tests/test_governance_ownership.py
git commit -m "feat(governance): generate + verify ~/.claude/OWNERSHIP.md from the map"
```

---

### Task 3: Source-header verifier — `source_header_lines` / `verify_headers`

**Files:**
- Modify: `src/security_scan/governance/ownership.py`
- Test: `tests/test_governance_ownership.py`

**Interfaces:**
- Consumes: `Tool`, `Manifest` from `.loader`; `_source_path` from `.deploy`.
- Produces:
  - `source_header_lines(tool: Tool, manifest: Manifest) -> list[str]` (the canonical 2 lines from Global Constraints)
  - `verify_headers(manifest: Manifest) -> list[tuple[str, str]]` — list of `(tool_name, "missing" | "wrong")`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_governance_ownership.py`:

```python
from security_scan.governance.ownership import source_header_lines, verify_headers


def _hdr_manifest(tmp_path, body_first_tool="echo a\n", with_header=True):
    home = tmp_path / "home"
    (home / "scripts").mkdir(parents=True)
    tool = Tool(name="a.sh", lane="detect", home_repo="home",
                source="scripts/a.sh", artifact_class="deployed",
                deploy_target="~/.claude/bin/a.sh", mode="755")
    repo = Repo(name="home", path=str(home), cls="tool-home")
    m = Manifest(tools=[tool], repos=[repo], runtime_dirs=[])
    hdr = "\n".join(source_header_lines(tool, m)) + "\n" if with_header else ""
    (home / "scripts" / "a.sh").write_text("#!/bin/bash\n" + hdr + body_first_tool)
    return m


def test_source_header_first_line_names_source_and_target(tmp_path):
    m = _hdr_manifest(tmp_path)
    first = source_header_lines(m.tools[0], m)[0]
    assert "Source of truth:" in first
    assert "scripts/a.sh" in first
    assert "~/.claude/bin/a.sh" in first


def test_verify_headers_ok_when_present(tmp_path):
    m = _hdr_manifest(tmp_path, with_header=True)
    assert verify_headers(m) == []


def test_verify_headers_flags_missing(tmp_path):
    m = _hdr_manifest(tmp_path, with_header=False)
    assert verify_headers(m) == [("a.sh", "missing")]


def test_verify_headers_flags_wrong_when_stale_header(tmp_path):
    m = _hdr_manifest(tmp_path, with_header=False)
    src = next(iter([m.tools[0]]))
    p = (tmp_path / "home" / "scripts" / "a.sh")
    p.write_text("#!/bin/bash\n# Source of truth: WRONG/path (deployed → nope)\necho a\n")
    assert verify_headers(m) == [("a.sh", "wrong")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/test_governance_ownership.py -k header -v`
Expected: FAIL with `ImportError: cannot import name 'source_header_lines'`.

- [ ] **Step 3: Implement**

Add to `src/security_scan/governance/ownership.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/test_governance_ownership.py -k header -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/governance/ownership.py tests/test_governance_ownership.py
git commit -m "feat(governance): verify source-of-truth headers on deployed artifacts"
```

---

### Task 4: Add the real source headers to the 5 deployed source files

**Files:**
- Modify: `scripts/security-scan.sh`, `scripts/skills-security-scan.sh`, `hooks/bws-write-guard.sh`, `hooks/bws-read-guard.sh`, `hooks/bws-scan-gate.sh`

**Interfaces:**
- Consumes: `source_header_lines` (Task 3) defines the exact text per file.

- [ ] **Step 1: Insert the 2-line header into each of the 5 files**

For each file, read its top, then insert the canonical 2 lines (Global Constraints) immediately **after** the shebang + top description comment block (after the last consecutive comment line that follows `#!/bin/bash`, before the first blank line, `set`, or code). The exact first line per file:

- `scripts/security-scan.sh`:
  `# Source of truth: ~/Projects/security-standards/scripts/security-scan.sh (deployed → ~/.claude/bin/security-scan.sh)`
  (place it just after the first `###...###` description block, BEFORE the `OUTPUT CONTRACT` block.)
- `scripts/skills-security-scan.sh`:
  `# Source of truth: ~/Projects/security-standards/scripts/skills-security-scan.sh (deployed → ~/.claude/bin/skills-security-scan.sh)`
- `hooks/bws-write-guard.sh`:
  `# Source of truth: ~/Projects/security-standards/hooks/bws-write-guard.sh (deployed → ~/.claude/hooks/bws-write-guard.sh)`
- `hooks/bws-read-guard.sh`:
  `# Source of truth: ~/Projects/security-standards/hooks/bws-read-guard.sh (deployed → ~/.claude/hooks/bws-read-guard.sh)`
- `hooks/bws-scan-gate.sh`:
  `# Source of truth: ~/Projects/security-standards/hooks/bws-scan-gate.sh (deployed → ~/.claude/hooks/bws-scan-gate.sh)`

Second line (identical for all five):
`# Edit here, not in place; then: cd ~/Projects/security-standards && make install`

> NOTE: editing `hooks/bws-*.sh` content is safe — the write-guard only blocks live BWS *token* shapes, not comments. Editing `scripts/security-scan.sh` is the file prong 2 reads; this is the additive edit already flagged in the spec.

- [ ] **Step 2: Verify the real headers pass `verify_headers` (without touching artifacts/ownership)**

Run:
```bash
PYTHONPATH=src python3 -c "from security_scan.governance.loader import load_map; from security_scan.governance.ownership import verify_headers; print(verify_headers(load_map('governance-map.toml')))"
```
Expected: `[]` (all five headers present and correct).

- [ ] **Step 3: Confirm the scanner still runs and the header is inert in stdout**

Run: `bash scripts/security-scan.sh >/tmp/s.txt 2>&1; grep -c 'Source of truth' /tmp/s.txt`
Expected: `0` (header is a comment, never emitted).

- [ ] **Step 4: Commit**

```bash
git add scripts/security-scan.sh scripts/skills-security-scan.sh hooks/bws-write-guard.sh hooks/bws-read-guard.sh hooks/bws-scan-gate.sh
git commit -m "feat(governance): add source-of-truth headers to deployed artifacts"
```

---

### Task 5: Stanza stripper — `strip_stanza`

**Files:**
- Modify: `src/security_scan/governance/ownership.py`
- Test: `tests/test_governance_ownership.py`

**Interfaces:**
- Consumes: `Repo` from `.loader`; existing `START`, `END`, `_claude_md`.
- Produces: `strip_stanza(repo: Repo) -> str` (`"stripped"` | `"absent"` | `"missing"`).

- [ ] **Step 1: Write failing tests**

Add to `tests/test_governance_ownership.py`:

```python
from security_scan.governance.ownership import strip_stanza, START, END


def test_strip_removes_block_preserves_surrounding(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    cm = d / "CLAUDE.md"
    cm.write_text(f"# Title\n\nIntro.\n\n{START}\nGENERATED\n{END}\n\nTail.\n")
    repo = Repo(name="R", path=str(d), cls="consumer")
    assert strip_stanza(repo) == "stripped"
    text = cm.read_text()
    assert "GENERATED" not in text and START not in text and END not in text
    assert "Intro." in text and "Tail." in text
    # idempotent
    assert strip_stanza(repo) == "absent"


def test_strip_block_at_end(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    cm = d / "CLAUDE.md"
    cm.write_text(f"# Title\n\nBody.\n\n{START}\nX\n{END}\n")
    repo = Repo(name="R", path=str(d), cls="consumer")
    assert strip_stanza(repo) == "stripped"
    assert cm.read_text() == "# Title\n\nBody.\n"


def test_strip_missing_claude_md(tmp_path):
    repo = Repo(name="R", path=str(tmp_path / "nope"), cls="consumer")
    assert strip_stanza(repo) == "missing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/test_governance_ownership.py -k strip -v`
Expected: FAIL with `ImportError: cannot import name 'strip_stanza'`.

- [ ] **Step 3: Implement**

Add to `src/security_scan/governance/ownership.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/test_governance_ownership.py -k strip -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/governance/ownership.py tests/test_governance_ownership.py
git commit -m "feat(governance): add idempotent stanza stripper for migration"
```

---

### Task 6: Switch over — rewire CLI + Makefile, remove the per-repo stanza projection

**Files:**
- Modify: `src/security_scan/governance/__main__.py`
- Modify: `src/security_scan/governance/ownership.py` (remove obsolete stanza functions)
- Modify: `tests/test_governance_ownership.py` (remove obsolete stanza tests; add CLI tests)
- Modify: `tests/test_governance_deploy.py` (one CLI fixture gains a header)
- Modify: `Makefile`

**Interfaces:**
- Consumes: `deploy_artifacts`, `reconcile_control_plane`, `verify_artifacts` (`.deploy`); `write_ownership`, `verify_ownership`, `verify_headers`, `strip_stanza`, `ensure_bws_manifest` (`.ownership`).
- Produces: CLI commands `deploy`, `verify` (`--artifacts-only` = artifacts + headers; full adds ownership; `--ownership-path` overridable), `ownership`, `strip-stanzas`.

- [ ] **Step 1: Write failing CLI tests**

Add to `tests/test_governance_ownership.py` (and remove the obsolete stanza/sync tests in Step 4):

```python
from security_scan.governance.__main__ import main as gov_main


def _cli_map(tmp_path, with_header=True):
    home = tmp_path / "home"
    (home / "scripts").mkdir(parents=True)
    target = tmp_path / "out" / "t.sh"
    tool_src = home / "scripts" / "t.sh"
    toml = tmp_path / "g.toml"
    toml.write_text(f'''
[[tool]]
name = "t.sh"
lane = "detect"
home_repo = "home"
source = "scripts/t.sh"
artifact_class = "deployed"
deploy_target = "{target}"
mode = "755"

[[repo]]
name = "home"
path = "{home}"
class = "tool-home"
''')
    hdr = (f"# Source of truth: {home}/scripts/t.sh (deployed → {target})\n"
           "# Edit here, not in place; then: cd ~/Projects/security-standards && make install\n"
           ) if with_header else ""
    tool_src.write_text("#!/bin/bash\n" + hdr + "echo x\n")
    return toml, target


def test_cli_ownership_then_full_verify(tmp_path, capsys):
    toml, target = _cli_map(tmp_path)
    own = tmp_path / "OWNERSHIP.md"
    assert gov_main(["deploy", "--map", str(toml)]) == 0
    assert gov_main(["ownership", "--map", str(toml), "--ownership-path", str(own)]) == 0
    assert own.exists()
    assert gov_main(["verify", "--map", str(toml), "--ownership-path", str(own)]) == 0


def test_cli_verify_fails_on_missing_header(tmp_path, capsys):
    toml, target = _cli_map(tmp_path, with_header=False)
    gov_main(["deploy", "--map", str(toml)])
    assert gov_main(["verify", "--artifacts-only", "--map", str(toml)]) == 1
    assert "header" in capsys.readouterr().out


def test_cli_strip_stanzas(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    (home / "CLAUDE.md").write_text(f"# H\n\n{START}\nX\n{END}\n")
    toml = tmp_path / "g.toml"
    toml.write_text(f'[[repo]]\nname = "home"\npath = "{home}"\nclass = "tool-home"\n')
    assert gov_main(["strip-stanzas", "--map", str(toml)]) == 0
    assert START not in (home / "CLAUDE.md").read_text()
```

- [ ] **Step 2: Run new CLI tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/test_governance_ownership.py -k "cli_ownership or cli_verify or cli_strip" -v`
Expected: FAIL (e.g. `argument command: invalid choice: 'ownership'`).

- [ ] **Step 3: Rewrite `__main__.py`**

Replace the body of `src/security_scan/governance/__main__.py` with:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from .loader import load_map
from .deploy import deploy_artifacts, reconcile_control_plane, verify_artifacts
from .ownership import (
    write_ownership, verify_ownership, verify_headers, strip_stanza, ensure_bws_manifest,
)

DEFAULT_MAP = Path(__file__).resolve().parents[3] / "governance-map.toml"
DEFAULT_OWNERSHIP = "~/.claude/OWNERSHIP.md"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="security_scan.governance")
    ap.add_argument("command", choices=["deploy", "verify", "ownership", "strip-stanzas"])
    ap.add_argument("--map", default=str(DEFAULT_MAP))
    ap.add_argument("--artifacts-only", action="store_true",
                    help="verify: deployed-faithfulness only (artifacts + source headers); "
                         "skip OWNERSHIP.md freshness")
    ap.add_argument("--ownership-path", default=DEFAULT_OWNERSHIP)
    args = ap.parse_args(argv)
    manifest = load_map(args.map)

    if args.command == "deploy":
        for name, act in deploy_artifacts(manifest):
            print(f"{act}: {name}")
        for root, note in reconcile_control_plane(manifest):
            print(f"{note}: {root}")
        return 0

    if args.command == "ownership":
        print(f"{write_ownership(manifest, args.ownership_path)}: {args.ownership_path}")
        for r in manifest.repos:
            print(f"{ensure_bws_manifest(r)}: {r.name}/.bws-secrets.toml")
        return 0

    if args.command == "verify":
        problems = [f"artifact {kind}: {name}" for name, kind in verify_artifacts(manifest)]
        problems += [f"header {kind}: {name}" for name, kind in verify_headers(manifest)]
        if not args.artifacts_only:
            ov = verify_ownership(manifest, args.ownership_path)
            if ov != "ok":
                problems.append(f"ownership {ov}: {args.ownership_path}")
        if problems:
            print("\n".join(problems))
            return 1
        scope = "artifacts + headers" if args.artifacts_only else "artifacts + headers + ownership"
        print(f"governance verify: {scope} in sync")
        return 0

    if args.command == "strip-stanzas":
        for r in manifest.repos:
            print(f"{strip_stanza(r)}: {r.name}/CLAUDE.md")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Remove the obsolete stanza projection from `ownership.py` and its tests**

In `src/security_scan/governance/ownership.py`, delete: `_HEADER`, `render_stanza`, `block`, `sync_stanza`, `verify_stanza`. Keep: `START`, `END`, `_BWS_SKELETON`, `_claude_md`, `ensure_bws_manifest`, and everything added in Tasks 2/3/5.

In `tests/test_governance_ownership.py`, delete the obsolete tests: `test_toolhome_stanza_mentions_ownership_and_lane`, `test_toolhome_stanza_states_honest_gating_scope`, `test_consumer_stanza_mentions_enforcement_and_bws`, `test_consumer_without_bws_omits_manifest_line`, `test_block_is_wrapped_in_markers`, `test_sync_creates_then_is_idempotent`, `test_sync_updates_stale_block_in_place`, `test_verify_reports_missing_and_drift`, `test_cli_sync_then_full_verify`, and the now-unused imports (`render_stanza`, `block`, `sync_stanza`, `verify_stanza`). Keep `test_ensure_bws_manifest` and its import.

- [ ] **Step 5: Update the one affected deploy CLI test fixture**

In `tests/test_governance_deploy.py`, in `test_cli_deploy_then_verify`, the tmp source must now carry a header (because `--artifacts-only` checks headers). Change:

```python
    (repo_root / "scripts" / "t.sh").write_text("x\n")
```
to:
```python
    (repo_root / "scripts" / "t.sh").write_text(
        f"#!/bin/bash\n# Source of truth: {repo_root}/scripts/t.sh (deployed → {target})\n"
        "# Edit here, not in place; then: cd ~/Projects/security-standards && make install\nx\n"
    )
```

- [ ] **Step 6: Update the Makefile**

Replace the Makefile body with:

```make
PY := PYTHONPATH=src python3

.PHONY: install verify ownership strip-stanzas test

install:  ## deploy artifacts, reconcile control-plane, regenerate OWNERSHIP.md, then verify
	$(PY) -m security_scan.governance deploy
	$(PY) -m security_scan.governance ownership
	$(PY) -m security_scan.governance verify

ownership:  ## regenerate ~/.claude/OWNERSHIP.md + ensure consumer .bws-secrets.toml
	$(PY) -m security_scan.governance ownership

verify:   ## assert deployed artifacts + source headers + OWNERSHIP.md match the map
	$(PY) -m security_scan.governance verify

strip-stanzas:  ## one-shot migration: remove generated governance stanzas from all repos' CLAUDE.md
	$(PY) -m security_scan.governance strip-stanzas

test:
	$(PY) -m pytest -q
```

- [ ] **Step 7: Run the full suite**

Run: `PYTHONPATH=src python3 -m pytest -q`
Expected: PASS (all ownership + deploy + other tests green; no references to removed stanza functions).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(governance): retire per-repo stanzas; project ownership map + headers instead"
```

---

### Task 7: Migration runbook (DEFERRED — Devon runs; NOT the implementer)

This task is **not executed during implementation.** It documents the exact, ordered live steps to cut over, to be run by Devon as a single deliberate session after item #4's code lands and (ideally) after prong 2 stabilizes — because it includes the deferred control-plane deploy of the item-#3 marker scanner.

- [ ] **Step 1: Deploy + regenerate ownership + verify (single live `make install`)**

```bash
cd ~/Projects/security-standards && make install
```
This deploys all artifacts (including the held item-#3 marker scanner), reconciles the control-plane git (prong 1 auto-commits the deployed hooks), regenerates `~/.claude/OWNERSHIP.md`, and runs the broadened `verify`. Expected final line: `governance verify: artifacts + headers + ownership in sync`.

- [ ] **Step 2: Add the one-line OWNERSHIP.md reference to `~/.claude/CLAUDE.md` and commit it**

Add a line such as `See ~/.claude/OWNERSHIP.md for control-plane artifact ownership (generated from security-standards/governance-map.toml).` to `~/.claude/CLAUDE.md`, then commit it in the control-plane repo (CLAUDE.md is in Check 13's critical set; prong 1 only auto-commits deployed *artifacts*, so this hand-edit needs a manual commit):

```bash
git -C ~/.claude add CLAUDE.md && git -C ~/.claude commit -m "docs: reference generated OWNERSHIP.md"
```

- [ ] **Step 3: Strip the old stanzas from all 10 repos**

```bash
cd ~/Projects/security-standards && make strip-stanzas
```
Expected: `stripped`/`absent` per repo. This reverts the item-#2 stanza sync; the gating language now lives in OWNERSHIP.md. Review and commit the `CLAUDE.md` change in each affected repo separately (each is reversible via git there).

- [ ] **Step 4: Confirm clean state**

```bash
cd ~/Projects/security-standards && make verify && bash scripts/security-scan.sh 2>&1 | grep -E 'controlplane|governance|SCANNER'
```
Expected: `governance verify: ... in sync`; `controlplane.clean`; Check 14 `governance.artifacts_in_sync`.

---

## Self-Review

**Spec coverage:** Component 1 (ownership map) → Task 2. Component 2 (source headers) → Tasks 3+4. Component 3 (code: rename, remove stanza funcs, add ownership/headers/strip, CLI commands) → Tasks 1,2,3,5,6. Component 4 (Makefile) → Task 6. Component 5 (Check 14 via redefined `--artifacts-only`) → Task 6 (no scanner-line edit needed; covered by the flag redefinition). Migration → Task 7. `ensure_bws_manifest` retained + wired into `ownership` command → Task 6. ✓

**Placeholder scan:** none — every code step shows complete code; Task 4 gives exact header strings per file and an explicit placement rule (the only rule-based step, because 3 of the 5 file tops aren't pre-read; acceptable and bounded).

**Type consistency:** `write_ownership`/`verify_ownership` take `(manifest, path)` everywhere; `verify_headers`/`verify_artifacts` both return `list[tuple[str, str]]` and are rendered identically in `__main__`; `strip_stanza` returns `"stripped"|"absent"|"missing"` matching its tests; `--ownership-path` default `~/.claude/OWNERSHIP.md` consistent across `ownership` + `verify`. ✓
