# Build-Agent Tool Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every security/scanning/change-management tool exactly one home repo, make `~/.claude/{bin,hooks}` pure verifiable deploy targets, and project a single `governance-map.toml` manifest into per-repo CLAUDE.md governance stanzas.

**Architecture:** A new `security_scan.governance` subpackage in the **security-standards** repo reads a root-level `governance-map.toml` and performs three operations: `deploy` (push deployed artifacts from home repos to `~/.claude/{bin,hooks}`), `sync` (write a generated governance stanza into each repo's CLAUDE.md), and `verify` (assert deployed artifacts match source and stanzas match the manifest projection). Phase 1 repatriates the scattered detectors and hooks into security-standards and stands up deploy/verify; Phase 2 adds the stanza generator on top of the same manifest.

**Tech Stack:** Python ≥3.12 (stdlib `tomllib`, `dataclasses`, `argparse`, `shutil`), pytest, bash (the detector scripts), GNU make.

## Global Constraints

- Python floor: **3.12** (`requires-python = ">=3.12"` in pyproject.toml). `tomllib` is stdlib — **add no new dependencies**.
- Tests run via pytest with `pythonpath = ["src"]`, `testpaths = ["tests"]` (already configured). Match existing test style: `def test_*`, `tmp_path`/`monkeypatch` fixtures, plain `assert`.
- This plan spans **two repos**: `~/Projects/security-standards` (primary) and `~/Projects/infraops-mcp-server` (files move out of it). Every command states its working directory. Each repo's changes are committed separately.
- **Secrets:** never write a BWS token into a tracked file. `.bws-secrets.toml` holds UUIDs only. The `bws-write-guard` hook will hard-deny any literal token in a write.
- Module invocation pattern (per global CLAUDE.md): `PYTHONPATH=src python3 -m security_scan.<module>`.
- Manifest is the single source of truth. Generated stanzas live between `<!-- governance:start -->` / `<!-- governance:end -->` markers and are **never hand-edited**.
- Frequent commits: each task ends with a commit.

---

## File Structure

**Created in `security-standards`:**
- `governance-map.toml` (repo root) — the single source of truth.
- `src/security_scan/governance/__init__.py` — subpackage marker.
- `src/security_scan/governance/loader.py` — TOML → dataclasses (`Tool`, `Repo`, `RuntimeDir`, `Manifest`), `load_map()`.
- `src/security_scan/governance/deploy.py` — `deploy_artifacts()`, `verify_artifacts()`.
- `src/security_scan/governance/stanza.py` — `render_stanza()`, `block()`, `sync_stanza()`, `verify_stanza()`, `ensure_bws_manifest()`.
- `src/security_scan/governance/__main__.py` — CLI dispatch (`deploy` / `sync` / `verify`).
- `scripts/security-scan.sh`, `scripts/skills-security-scan.sh` — detectors (imported from deployed copies).
- `scripts/install-security-scan-launchd.sh`, `scripts/com.devon.security-scan.plist.template` — moved from infraops.
- `hooks/bws-write-guard.sh`, `hooks/bws-read-guard.sh`, `hooks/bws-scan-gate.sh` — imported from deployed copies.
- `Makefile` (repo root) — `install` / `sync` / `verify` targets.
- `tests/test_governance_loader.py`, `tests/test_governance_deploy.py`, `tests/test_governance_stanza.py`.

**Modified in `security-standards`:**
- `scripts/security-scan.sh` — gains one artifact-sync check (Task 8).

**Removed from `infraops-mcp-server`:**
- `scripts/security-scan.sh`, `scripts/skills-security-scan.sh`, `scripts/install-security-scan-launchd.sh`, `scripts/com.devon.security-scan.plist.template`.

---

# PHASE 1 — Repatriate Ownership + Deploy/Verify

### Task 1: Governance manifest + loader

**Files:**
- Create: `~/Projects/security-standards/governance-map.toml`
- Create: `~/Projects/security-standards/src/security_scan/governance/__init__.py`
- Create: `~/Projects/security-standards/src/security_scan/governance/loader.py`
- Test: `~/Projects/security-standards/tests/test_governance_loader.py`

**Interfaces:**
- Produces: `load_map(path: str | Path) -> Manifest`. Dataclasses: `Tool(name, lane, home_repo, source, artifact_class, deploy_target="", mode="755")`; `Repo(name, path, cls, lane="", owns=[], consumers=[], uses_bws=False)`; `RuntimeDir(path, note="")`; `Manifest(tools: list[Tool], repos: list[Repo], runtime_dirs: list[RuntimeDir])`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_governance_loader.py`:
```python
from security_scan.governance.loader import load_map

SAMPLE = '''
[[tool]]
name = "security-scan.sh"
lane = "detect"
home_repo = "security-standards"
source = "scripts/security-scan.sh"
artifact_class = "deployed"
deploy_target = "~/.claude/bin/security-scan.sh"
mode = "755"

[[repo]]
name = "security-standards"
path = "~/Projects/security-standards"
class = "tool-home"
lane = "detect"
owns = ["security-scan.sh"]
consumers = ["infraops-mcp-server"]

[[repo]]
name = "FacelessTT"
path = "~/Projects/FacelessTT"
class = "consumer"
uses_bws = true

[[runtime_dir]]
path = "~/.claude/audit"
note = "weekly detector logs"
'''

def test_load_map_parses_all_sections(tmp_path):
    p = tmp_path / "governance-map.toml"
    p.write_text(SAMPLE)
    m = load_map(p)
    assert len(m.tools) == 1
    assert m.tools[0].name == "security-scan.sh"
    assert m.tools[0].artifact_class == "deployed"
    assert m.tools[0].mode == "755"
    assert {r.name: r.cls for r in m.repos} == {
        "security-standards": "tool-home", "FacelessTT": "consumer"}
    fac = next(r for r in m.repos if r.name == "FacelessTT")
    assert fac.uses_bws is True
    assert m.repos[0].consumers == ["infraops-mcp-server"]
    assert m.runtime_dirs[0].path == "~/.claude/audit"

def test_repo_defaults(tmp_path):
    p = tmp_path / "g.toml"
    p.write_text('[[repo]]\nname="x"\npath="~/x"\nclass="consumer"\n')
    m = load_map(p)
    assert m.repos[0].uses_bws is False
    assert m.repos[0].owns == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'security_scan.governance'`

- [ ] **Step 3: Create the subpackage and loader**

Create `src/security_scan/governance/__init__.py` (empty file).

Create `src/security_scan/governance/loader.py`:
```python
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Tool:
    name: str
    lane: str
    home_repo: str
    source: str
    artifact_class: str          # "source" | "deployed" | "runtime"
    deploy_target: str = ""
    mode: str = "755"


@dataclass
class Repo:
    name: str
    path: str
    cls: str                     # "tool-home" | "consumer"
    lane: str = ""
    owns: list[str] = field(default_factory=list)
    consumers: list[str] = field(default_factory=list)
    uses_bws: bool = False


@dataclass
class RuntimeDir:
    path: str
    note: str = ""


@dataclass
class Manifest:
    tools: list[Tool]
    repos: list[Repo]
    runtime_dirs: list[RuntimeDir]


def load_map(path: str | Path) -> Manifest:
    data = tomllib.loads(Path(path).read_text())
    tools = [Tool(**t) for t in data.get("tool", [])]
    repos = [
        Repo(
            name=r["name"], path=r["path"], cls=r["class"],
            lane=r.get("lane", ""), owns=r.get("owns", []),
            consumers=r.get("consumers", []), uses_bws=r.get("uses_bws", False),
        )
        for r in data.get("repo", [])
    ]
    rdirs = [RuntimeDir(**d) for d in data.get("runtime_dir", [])]
    return Manifest(tools=tools, repos=repos, runtime_dirs=rdirs)
```

- [ ] **Step 4: Create the real `governance-map.toml`**

Create `~/Projects/security-standards/governance-map.toml`. Seed it with the three tool-home repos, the deployed detectors + hooks, and the runtime dirs. Consumer repos are added in Task 10.
```toml
# governance-map.toml — single source of truth for tool ownership + build-agent alignment.
# Lane rule: security-standards DETECTS, infraops-mcp-server MUTATES, change-manager APPROVES.
# Projected into: deploys (make install), CLAUDE.md stanzas (make sync), verification (make verify).
# Edit here; never hand-edit a generated <!-- governance --> stanza.

# ─────────────────────────── Deployed artifacts ───────────────────────────
[[tool]]
name = "security-scan.sh"
lane = "detect"
home_repo = "security-standards"
source = "scripts/security-scan.sh"
artifact_class = "deployed"
deploy_target = "~/.claude/bin/security-scan.sh"
mode = "755"

[[tool]]
name = "skills-security-scan.sh"
lane = "detect"
home_repo = "security-standards"
source = "scripts/skills-security-scan.sh"
artifact_class = "deployed"
deploy_target = "~/.claude/bin/skills-security-scan.sh"
mode = "755"

[[tool]]
name = "bws-write-guard.sh"
lane = "detect"
home_repo = "security-standards"
source = "hooks/bws-write-guard.sh"
artifact_class = "deployed"
deploy_target = "~/.claude/hooks/bws-write-guard.sh"
mode = "755"

[[tool]]
name = "bws-read-guard.sh"
lane = "detect"
home_repo = "security-standards"
source = "hooks/bws-read-guard.sh"
artifact_class = "deployed"
deploy_target = "~/.claude/hooks/bws-read-guard.sh"
mode = "755"

[[tool]]
name = "bws-scan-gate.sh"
lane = "detect"
home_repo = "security-standards"
source = "hooks/bws-scan-gate.sh"
artifact_class = "deployed"
deploy_target = "~/.claude/hooks/bws-scan-gate.sh"
mode = "755"

# ─────────────────────────────── Repos ────────────────────────────────────
[[repo]]
name = "security-standards"
path = "~/Projects/security-standards"
class = "tool-home"
lane = "detect"
owns = ["security_scan (python package)", "security-scan.sh", "skills-security-scan.sh", "bws-write-guard.sh", "bws-read-guard.sh", "bws-scan-gate.sh"]
consumers = ["security-standards", "infraops-mcp-server", "change-manager"]

[[repo]]
name = "infraops-mcp-server"
path = "~/Projects/infraops-mcp-server"
class = "tool-home"
lane = "mutate"
owns = ["infraops MCP server", "drift-audit.sh", "change-window.sh", "security-drift subsystem"]

[[repo]]
name = "change-manager"
path = "~/Projects/change-manager"
class = "tool-home"
lane = "approve"
owns = ["change-manager FastAPI service"]

# Consumer repos are appended in Task 10.

# ───────────────────── Runtime state (deliberately repo-less) ─────────────────────
[[runtime_dir]]
path = "~/.config/infra-drift"
note = "infra-drift env + security baselines; gitignored; machine-level."

[[runtime_dir]]
path = "~/infra-drift/reports"
note = "daily audit/remediation/security/change-window digests."

[[runtime_dir]]
path = "~/.claude/audit"
note = "weekly detector logs + high-power-action audit log."
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_loader.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
cd ~/Projects/security-standards
git add governance-map.toml src/security_scan/governance/__init__.py \
  src/security_scan/governance/loader.py tests/test_governance_loader.py
git commit -m "feat(governance): manifest schema + loader"
```

---

### Task 2: Repatriate the detectors into security-standards

Import the **deployed** `security-scan.sh` (canonical — 481 lines ahead of the infraops copy) and the identical `skills-security-scan.sh`, plus the launchd installer + plist template, then delete them from infraops.

**Files:**
- Create: `~/Projects/security-standards/scripts/security-scan.sh` (from `~/.claude/bin/security-scan.sh`)
- Create: `~/Projects/security-standards/scripts/skills-security-scan.sh`
- Create: `~/Projects/security-standards/scripts/com.devon.security-scan.plist.template`
- Create: `~/Projects/security-standards/scripts/install-security-scan-launchd.sh`
- Remove (infraops): the same four files under `~/Projects/infraops-mcp-server/scripts/`

- [ ] **Step 1: Copy canonical files into security-standards**

The deployed `security-scan.sh` is the source of truth (it has the PATH fix + control-plane logic). `skills-security-scan.sh` is byte-identical in either location.
```bash
cd ~/Projects/security-standards
mkdir -p scripts
cp ~/.claude/bin/security-scan.sh           scripts/security-scan.sh
cp ~/.claude/bin/skills-security-scan.sh    scripts/skills-security-scan.sh
cp ~/Projects/infraops-mcp-server/scripts/com.devon.security-scan.plist.template scripts/
cp ~/Projects/infraops-mcp-server/scripts/install-security-scan-launchd.sh       scripts/
chmod 755 scripts/security-scan.sh scripts/skills-security-scan.sh scripts/install-security-scan-launchd.sh
```

- [ ] **Step 2: Repoint the installer's deploy step at the governance module**

The installer currently `install -m 755`'s the two scripts itself. Replace that block so file deployment goes through the manifest (single deploy path), keeping only the launchd plist render/load here. Edit `scripts/install-security-scan-launchd.sh`: replace the two `install -m 755 ...` lines with:
```bash
# Deploy the manifest-declared artifacts (detectors + hooks) from their home repo.
( cd "$REPO" && PYTHONPATH=src python3 -m security_scan.governance deploy )
```
Leave the `sed ... > "$PLIST"`, `launchctl unload/load`, and echo lines unchanged. (`$REPO` now resolves to the security-standards root, since the installer lives at `scripts/` within it.)

- [ ] **Step 3: Verify the imported detector matches what is deployed**

Run: `diff ~/Projects/security-standards/scripts/security-scan.sh ~/.claude/bin/security-scan.sh && echo IDENTICAL`
Expected: `IDENTICAL` (byte-for-byte — we copied from the deployed file).

- [ ] **Step 4: Commit the import in security-standards**

```bash
cd ~/Projects/security-standards
git add scripts/
git commit -m "feat(governance): repatriate detectors + launchd installer from infraops"
```

- [ ] **Step 5: Remove the detectors from infraops and update references**

```bash
cd ~/Projects/infraops-mcp-server
git rm scripts/security-scan.sh scripts/skills-security-scan.sh \
  scripts/install-security-scan-launchd.sh scripts/com.devon.security-scan.plist.template
grep -rn "scripts/security-scan.sh\|install-security-scan-launchd" --include='*.md' --include='*.ts' . || echo "no stale references"
```
If `grep` finds references in infraops docs (e.g. `scripts/README.md`), edit them to point at `security-standards/scripts/...`. The `src/security-drift/` code binds to the **deployed** path (`~/.claude/bin/security-scan.sh` via `paths.ts`), so it needs **no change**.

- [ ] **Step 6: Commit the removal in infraops**

```bash
cd ~/Projects/infraops-mcp-server
git add -A
git commit -m "refactor: move security detectors to security-standards (detect lane)"
```

---

### Task 3: Repatriate the 3 BWS hooks as source

The hooks currently exist **only** as deployed files in `~/.claude/hooks/`. Import them into security-standards as their home.

**Files:**
- Create: `~/Projects/security-standards/hooks/bws-write-guard.sh`
- Create: `~/Projects/security-standards/hooks/bws-read-guard.sh`
- Create: `~/Projects/security-standards/hooks/bws-scan-gate.sh`

- [ ] **Step 1: Copy the deployed hooks into the repo**

```bash
cd ~/Projects/security-standards
mkdir -p hooks
cp ~/.claude/hooks/bws-write-guard.sh hooks/
cp ~/.claude/hooks/bws-read-guard.sh  hooks/
cp ~/.claude/hooks/bws-scan-gate.sh   hooks/
chmod 755 hooks/*.sh
```

- [ ] **Step 2: Verify imported hooks match what is deployed**

Run:
```bash
for h in bws-write-guard bws-read-guard bws-scan-gate; do
  diff ~/Projects/security-standards/hooks/$h.sh ~/.claude/hooks/$h.sh >/dev/null \
    && echo "$h IDENTICAL" || echo "$h DIFFERS"
done
```
Expected: all three `IDENTICAL`.

- [ ] **Step 3: Confirm no BWS token leaked into the imported files**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m security_scan.cli . --category security | python3 -c "import sys,json; r=json.load(sys.stdin); print('BLOCK findings:', sum(1 for f in r['findings'] if f['severity']=='BLOCK'))"`
Expected: `BLOCK findings: 0` (hooks reference token *shapes*, not literal tokens). If non-zero, stop — a real token is present and must be handled per the security rules, not committed.

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/security-standards
git add hooks/
git commit -m "feat(governance): repatriate BWS hooks as source (were deployed-only)"
```

---

### Task 4: Deploy module + `make install`

**Files:**
- Create: `~/Projects/security-standards/src/security_scan/governance/deploy.py`
- Create: `~/Projects/security-standards/Makefile`
- Test: `~/Projects/security-standards/tests/test_governance_deploy.py`

**Interfaces:**
- Consumes: `Manifest`, `Tool`, `Repo` from `loader`.
- Produces: `deploy_artifacts(manifest: Manifest) -> list[tuple[str, str]]` (returns `(tool_name, "deployed")` per deployed tool); `verify_artifacts(manifest: Manifest) -> list[tuple[str, str]]` (returns `(tool_name, "missing"|"drift")` for each problem; empty list = all in sync). Both resolve a tool's source under its home repo's `path` and expand `~` in paths.

- [ ] **Step 1: Write the failing test**

Create `tests/test_governance_deploy.py`:
```python
import os
from security_scan.governance.loader import Manifest, Tool, Repo
from security_scan.governance.deploy import deploy_artifacts, verify_artifacts


def _manifest(tmp_path):
    repo_root = tmp_path / "home"
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "scripts" / "tool.sh").write_text("echo hi\n")
    target = tmp_path / "deployed" / "tool.sh"
    tool = Tool(name="tool.sh", lane="detect", home_repo="home",
                source="scripts/tool.sh", artifact_class="deployed",
                deploy_target=str(target), mode="755")
    repo = Repo(name="home", path=str(repo_root), cls="tool-home")
    return Manifest(tools=[tool], repos=[repo], runtime_dirs=[]), target


def test_deploy_copies_with_mode(tmp_path):
    m, target = _manifest(tmp_path)
    actions = deploy_artifacts(m)
    assert actions == [("tool.sh", "deployed")]
    assert target.read_text() == "echo hi\n"
    assert oct(target.stat().st_mode)[-3:] == "755"


def test_verify_clean_after_deploy(tmp_path):
    m, _ = _manifest(tmp_path)
    deploy_artifacts(m)
    assert verify_artifacts(m) == []


def test_verify_detects_drift_and_missing(tmp_path):
    m, target = _manifest(tmp_path)
    assert verify_artifacts(m) == [("tool.sh", "missing")]
    deploy_artifacts(m)
    target.write_text("tampered\n")
    assert verify_artifacts(m) == [("tool.sh", "drift")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_deploy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'security_scan.governance.deploy'`

- [ ] **Step 3: Write the deploy module**

Create `src/security_scan/governance/deploy.py`:
```python
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .loader import Manifest, Tool


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def _source_path(tool: Tool, manifest: Manifest) -> Path:
    for r in manifest.repos:
        if r.name == tool.home_repo:
            return _expand(r.path) / tool.source
    raise KeyError(f"home_repo {tool.home_repo!r} for tool {tool.name!r} not in manifest")


def deploy_artifacts(manifest: Manifest) -> list[tuple[str, str]]:
    actions: list[tuple[str, str]] = []
    for t in manifest.tools:
        if t.artifact_class != "deployed":
            continue
        src = _source_path(t, manifest)
        dst = _expand(t.deploy_target)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        os.chmod(dst, int(t.mode, 8))
        actions.append((t.name, "deployed"))
    return actions


def verify_artifacts(manifest: Manifest) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    for t in manifest.tools:
        if t.artifact_class != "deployed":
            continue
        src = _source_path(t, manifest)
        dst = _expand(t.deploy_target)
        if not dst.exists():
            problems.append((t.name, "missing"))
        elif src.read_bytes() != dst.read_bytes():
            problems.append((t.name, "drift"))
    return problems
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_deploy.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Create the Makefile**

Create `~/Projects/security-standards/Makefile`:
```makefile
PY := PYTHONPATH=src python3

.PHONY: install sync verify test

install:  ## deploy manifest artifacts to ~/.claude/{bin,hooks}
	$(PY) -m security_scan.governance deploy

sync:     ## write governance stanzas into each repo's CLAUDE.md
	$(PY) -m security_scan.governance sync

verify:   ## assert deployed artifacts + stanzas match the manifest
	$(PY) -m security_scan.governance verify

test:
	$(PY) -m pytest -q
```
(`__main__.py` arrives in Task 5/9; `make install`/`sync`/`verify` will work after those.)

- [ ] **Step 6: Commit**

```bash
cd ~/Projects/security-standards
git add src/security_scan/governance/deploy.py tests/test_governance_deploy.py Makefile
git commit -m "feat(governance): artifact deploy/verify + Makefile"
```

---

### Task 5: CLI entrypoint (`deploy` / `verify`) and a real deploy

**Files:**
- Create: `~/Projects/security-standards/src/security_scan/governance/__main__.py`

**Interfaces:**
- Consumes: `load_map`, `deploy_artifacts`, `verify_artifacts`. (Stanza functions are wired in Task 9.)
- Produces: `main(argv=None) -> int`. Commands: `deploy`, `verify` (with `--artifacts-only`), `sync`. `--map` defaults to `governance-map.toml` at the repo root (`parents[3]` of this file). Returns non-zero when `verify` finds problems.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_governance_deploy.py`:
```python
from security_scan.governance.__main__ import main


def test_cli_deploy_then_verify(tmp_path, capsys):
    repo_root = tmp_path / "home"
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "scripts" / "t.sh").write_text("x\n")
    target = tmp_path / "out" / "t.sh"
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
path = "{repo_root}"
class = "tool-home"
''')
    assert main(["deploy", "--map", str(toml)]) == 0
    assert main(["verify", "--artifacts-only", "--map", str(toml)]) == 0
    target.write_text("tampered\n")
    assert main(["verify", "--artifacts-only", "--map", str(toml)]) == 1
    assert "drift" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_deploy.py::test_cli_deploy_then_verify -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'security_scan.governance.__main__'`

- [ ] **Step 3: Write the CLI**

Create `src/security_scan/governance/__main__.py`:
```python
from __future__ import annotations

import argparse
from pathlib import Path

from .loader import load_map
from .deploy import deploy_artifacts, verify_artifacts

DEFAULT_MAP = Path(__file__).resolve().parents[3] / "governance-map.toml"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="security_scan.governance")
    ap.add_argument("command", choices=["deploy", "sync", "verify"])
    ap.add_argument("--map", default=str(DEFAULT_MAP))
    ap.add_argument("--artifacts-only", action="store_true",
                    help="verify: check deployed artifacts only, skip CLAUDE.md stanzas")
    args = ap.parse_args(argv)
    manifest = load_map(args.map)

    if args.command == "deploy":
        for name, act in deploy_artifacts(manifest):
            print(f"{act}: {name}")
        return 0

    if args.command == "verify":
        problems = [f"artifact {kind}: {name}" for name, kind in verify_artifacts(manifest)]
        # Stanza verification is added in Task 9; --artifacts-only is the Phase-1 behavior.
        if problems:
            print("\n".join(problems))
            return 1
        print("governance verify: artifacts in sync")
        return 0

    if args.command == "sync":
        print("sync not yet implemented (Task 9)")
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_deploy.py -v`
Expected: PASS (all deploy tests + the CLI test)

- [ ] **Step 5: Deploy for real and verify against the live machine**

```bash
cd ~/Projects/security-standards
make install
make verify
```
Expected: `make install` prints `deployed: ...` for all 5 artifacts; `make verify` prints `governance verify: artifacts in sync` (exit 0). Because the imported files are byte-identical to the already-deployed ones, this overwrites them with identical content — the `security-drift` 3am self-check hash does **not** change.

- [ ] **Step 6: Commit**

```bash
cd ~/Projects/security-standards
git add src/security_scan/governance/__main__.py tests/test_governance_deploy.py
git commit -m "feat(governance): deploy/verify CLI; deploy artifacts from home repo"
```

---

### Task 6: Artifact-sync check inside `security-scan.sh`

Add one check so the weekly machine scan flags any deployed artifact that has drifted from its home repo. Uses `--artifacts-only` (stanza freshness is a repo-dev concern, checked by `make verify`, not the machine scan).

**Files:**
- Modify: `~/Projects/security-standards/scripts/security-scan.sh`

- [ ] **Step 1: Add the check**

In `scripts/security-scan.sh`, after the existing checks and before the final summary/exit, add:
```bash
# ── Check: deployed artifacts match their home repos (governance-map) ──
SECSTD="$HOME/Projects/security-standards"
if [ -f "$SECSTD/governance-map.toml" ] && have python3; then
  if gv_out="$(cd "$SECSTD" && PYTHONPATH=src python3 -m security_scan.governance verify --artifacts-only 2>&1)"; then
    emit PASS governance.artifacts_in_sync "deployed artifacts match home repos"
  else
    emit FAIL governance.artifacts_in_sync "$(printf '%s' "$gv_out" | tr '\n' ';')"
  fi
fi
```
(`have` and `emit` are existing helpers in the script.)

- [ ] **Step 2: Run the scanner locally and confirm the new check passes**

Run: `bash ~/Projects/security-standards/scripts/security-scan.sh | grep governance.artifacts_in_sync`
Expected: a `PASS governance.artifacts_in_sync ...` line (artifacts were deployed in Task 5).

- [ ] **Step 3: Redeploy the edited detector and commit**

The detector's bytes changed, so redeploy it to `~/.claude/bin` and commit. This is the **one expected** `security-drift` "scanner hash changed — verify intentional" URGENT on the next 3am run (by design, per the installer's header note); it self-clears once the new hash is recorded.
```bash
cd ~/Projects/security-standards
make install
make verify
git add scripts/security-scan.sh
git commit -m "feat(governance): security-scan.sh flags deployed-artifact drift"
```

**✅ Phase 1 checkpoint (shippable):** every tool has one home repo; `~/.claude/{bin,hooks}` are verifiable deploy targets; the weekly scan catches future drift; runtime dirs are documented as repo-less.

---

# PHASE 2 — Build-Agent Alignment

### Task 7: Governance stanza renderer

**Files:**
- Create: `~/Projects/security-standards/src/security_scan/governance/stanza.py`
- Test: `~/Projects/security-standards/tests/test_governance_stanza.py`

**Interfaces:**
- Consumes: `Manifest`, `Repo` from `loader`.
- Produces: `render_stanza(repo: Repo, manifest: Manifest) -> str` (markdown body, no markers); `block(repo, manifest) -> str` (body wrapped in start/end markers); module constants `START`, `END`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_governance_stanza.py`:
```python
from security_scan.governance.loader import Manifest, Repo
from security_scan.governance.stanza import render_stanza, block, START, END

TOOLHOME = Repo(name="infraops-mcp-server", path="~/Projects/infraops-mcp-server",
                cls="tool-home", lane="mutate",
                owns=["drift-audit.sh", "change-window.sh"],
                consumers=["FacelessTT"])
CONSUMER = Repo(name="FacelessTT", path="~/Projects/FacelessTT",
                cls="consumer", uses_bws=True)
M = Manifest(tools=[], repos=[TOOLHOME, CONSUMER], runtime_dirs=[])


def test_toolhome_stanza_mentions_ownership_and_lane():
    s = render_stanza(TOOLHOME, M)
    assert "tool-home" in s
    assert "mutate" in s
    assert "`drift-audit.sh`" in s
    assert "make install" in s and "make verify" in s
    assert "FacelessTT" in s


def test_consumer_stanza_mentions_enforcement_and_bws():
    s = render_stanza(CONSUMER, M)
    assert "consumer" in s
    assert "security-standards" in s
    assert "bws-write-guard" in s
    assert ".bws-secrets.toml" in s


def test_consumer_without_bws_omits_manifest_line():
    nobws = Repo(name="X", path="~/X", cls="consumer", uses_bws=False)
    s = render_stanza(nobws, M)
    assert ".bws-secrets.toml" not in s


def test_block_is_wrapped_in_markers():
    b = block(CONSUMER, M)
    assert b.startswith(START)
    assert b.rstrip().endswith(END)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_stanza.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'security_scan.governance.stanza'`

- [ ] **Step 3: Write the renderer**

Create `src/security_scan/governance/stanza.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_stanza.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/security-standards
git add src/security_scan/governance/stanza.py tests/test_governance_stanza.py
git commit -m "feat(governance): CLAUDE.md stanza renderer"
```

---

### Task 8: Stanza sync, verify, and `.bws-secrets.toml` stamper

**Files:**
- Modify: `~/Projects/security-standards/src/security_scan/governance/stanza.py`
- Test: `~/Projects/security-standards/tests/test_governance_stanza.py`

**Interfaces:**
- Produces: `sync_stanza(repo, manifest) -> str` (returns `"created"|"written"|"unchanged"`); `verify_stanza(repo, manifest) -> str` (returns `"ok"|"drift"|"missing"`); `ensure_bws_manifest(repo) -> str` (returns `"created"|"exists"|"skip"`). All operate on `{repo.path}/CLAUDE.md` (and `/.bws-secrets.toml`) with `~` expanded.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_governance_stanza.py`:
```python
from security_scan.governance.stanza import (
    sync_stanza, verify_stanza, ensure_bws_manifest, block,
)


def _repo_at(tmp_path, uses_bws=True):
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(name="FacelessTT", path=str(d), cls="consumer", uses_bws=uses_bws), d


def test_sync_creates_then_is_idempotent(tmp_path):
    repo, d = _repo_at(tmp_path)
    m = Manifest(tools=[], repos=[repo], runtime_dirs=[])
    (d / "CLAUDE.md").write_text("# FacelessTT\n\nExisting notes.\n")
    assert sync_stanza(repo, m) == "created"
    assert START in (d / "CLAUDE.md").read_text()
    assert "Existing notes." in (d / "CLAUDE.md").read_text()
    assert sync_stanza(repo, m) == "unchanged"


def test_sync_updates_stale_block_in_place(tmp_path):
    repo, d = _repo_at(tmp_path)
    m = Manifest(tools=[], repos=[repo], runtime_dirs=[])
    (d / "CLAUDE.md").write_text(f"# T\n\n{START}\nOLD\n{END}\n\nTail.\n")
    assert sync_stanza(repo, m) == "written"
    text = (d / "CLAUDE.md").read_text()
    assert "OLD" not in text
    assert "Tail." in text
    assert verify_stanza(repo, m) == "ok"


def test_verify_reports_missing_and_drift(tmp_path):
    repo, d = _repo_at(tmp_path)
    m = Manifest(tools=[], repos=[repo], runtime_dirs=[])
    assert verify_stanza(repo, m) == "missing"
    sync_stanza(repo, m)
    assert verify_stanza(repo, m) == "ok"
    cur = (d / "CLAUDE.md").read_text().replace("consumer", "TAMPERED")
    (d / "CLAUDE.md").write_text(cur)
    assert verify_stanza(repo, m) == "drift"


def test_ensure_bws_manifest(tmp_path):
    repo, d = _repo_at(tmp_path, uses_bws=True)
    assert ensure_bws_manifest(repo) == "created"
    assert (d / ".bws-secrets.toml").exists()
    assert ensure_bws_manifest(repo) == "exists"
    nob_dir = tmp_path / "n"
    nob_dir.mkdir()
    nob = Repo(name="N", path=str(nob_dir), cls="consumer", uses_bws=False)
    assert ensure_bws_manifest(nob) == "skip"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_stanza.py -v`
Expected: FAIL — `ImportError: cannot import name 'sync_stanza'`

- [ ] **Step 3: Implement sync/verify/stamper**

Append to `src/security_scan/governance/stanza.py`:
```python
import os
from pathlib import Path

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_stanza.py -v`
Expected: PASS (all stanza tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/security-standards
git add src/security_scan/governance/stanza.py tests/test_governance_stanza.py
git commit -m "feat(governance): stanza sync/verify + .bws-secrets.toml stamper"
```

---

### Task 9: Wire `sync` + full `verify` into the CLI

**Files:**
- Modify: `~/Projects/security-standards/src/security_scan/governance/__main__.py`

**Interfaces:**
- Consumes: `sync_stanza`, `verify_stanza`, `ensure_bws_manifest` from `stanza`.
- Produces: `sync` command (writes stanzas + stamps BWS skeletons for all repos); `verify` without `--artifacts-only` now also checks stanzas.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_governance_stanza.py`:
```python
from security_scan.governance.__main__ import main as gov_main


def test_cli_sync_then_full_verify(tmp_path, capsys):
    repo_root = tmp_path / "FacelessTT"
    repo_root.mkdir()
    (repo_root / "CLAUDE.md").write_text("# FacelessTT\n")
    toml = tmp_path / "g.toml"
    toml.write_text(f'''
[[repo]]
name = "FacelessTT"
path = "{repo_root}"
class = "consumer"
uses_bws = true
''')
    assert gov_main(["sync", "--map", str(toml)]) == 0
    assert START in (repo_root / "CLAUDE.md").read_text()
    assert (repo_root / ".bws-secrets.toml").exists()
    assert gov_main(["verify", "--map", str(toml)]) == 0
    # tamper → full verify fails
    (repo_root / "CLAUDE.md").write_text("# wiped\n")
    assert gov_main(["verify", "--map", str(toml)]) == 1
    assert "stanza" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_stanza.py::test_cli_sync_then_full_verify -v`
Expected: FAIL — `sync` currently prints "not yet implemented" and returns 2.

- [ ] **Step 3: Implement sync + extend verify**

In `src/security_scan/governance/__main__.py`, add the import:
```python
from .stanza import sync_stanza, verify_stanza, ensure_bws_manifest
```
Replace the `sync` branch with:
```python
    if args.command == "sync":
        for r in manifest.repos:
            print(f"{sync_stanza(r, manifest)}: {r.name}/CLAUDE.md")
            print(f"{ensure_bws_manifest(r)}: {r.name}/.bws-secrets.toml")
        return 0
```
Replace the `verify` branch with:
```python
    if args.command == "verify":
        problems = [f"artifact {kind}: {name}" for name, kind in verify_artifacts(manifest)]
        if not args.artifacts_only:
            for r in manifest.repos:
                v = verify_stanza(r, manifest)
                if v != "ok":
                    problems.append(f"stanza {v}: {r.name}")
        if problems:
            print("\n".join(problems))
            return 1
        scope = "artifacts" if args.artifacts_only else "artifacts + stanzas"
        print(f"governance verify: {scope} in sync")
        return 0
```

- [ ] **Step 4: Run the full governance test suite**

Run: `cd ~/Projects/security-standards && PYTHONPATH=src python3 -m pytest tests/test_governance_loader.py tests/test_governance_deploy.py tests/test_governance_stanza.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/security-standards
git add src/security_scan/governance/__main__.py tests/test_governance_stanza.py
git commit -m "feat(governance): wire sync + full stanza verify into CLI"
```

---

### Task 10: Populate consumers and run sync for real

**Files:**
- Modify: `~/Projects/security-standards/governance-map.toml`

- [ ] **Step 1: Enumerate candidate consumer repos**

```bash
for d in ~/Projects/*/; do
  name="$(basename "$d")"
  [ -d "$d/.git" ] || continue
  case "$name" in security-standards|infraops-mcp-server|change-manager) continue;; esac
  bws="false"; { [ -f "$d/.bws-secrets.toml" ] || grep -rqlI "BWS_ACCESS_TOKEN" "$d" 2>/dev/null; } && bws="true"
  printf '%s\tuses_bws=%s\n' "$name" "$bws"
done
```
This lists each non-tool-home git repo under `~/Projects` and whether it appears to consume BWS (has a `.bws-secrets.toml` or references `BWS_ACCESS_TOKEN`).

- [ ] **Step 2: Append a `[[repo]]` consumer entry per listed repo**

For each repo from Step 1, append to `governance-map.toml` (replace `NAME` and the `uses_bws` value with the Step 1 output; FacelessTT shown as the worked example):
```toml
[[repo]]
name = "FacelessTT"
path = "~/Projects/FacelessTT"
class = "consumer"
uses_bws = true
```

- [ ] **Step 3: Preview the sync (dry inspection), then apply**

```bash
cd ~/Projects/security-standards
make sync
```
Expected output: one `created`/`written`/`unchanged` line per repo for CLAUDE.md, and `created`/`exists`/`skip` for `.bws-secrets.toml`. Inspect one consumer to confirm the stanza is correct:
```bash
sed -n '/governance:start/,/governance:end/p' ~/Projects/FacelessTT/CLAUDE.md
```

- [ ] **Step 4: Full verify**

Run: `cd ~/Projects/security-standards && make verify`
Expected: `governance verify: artifacts + stanzas in sync` (exit 0).

- [ ] **Step 5: Commit the manifest; commit generated stanzas in each consumer repo**

```bash
cd ~/Projects/security-standards
git add governance-map.toml
git commit -m "feat(governance): register consumer build agents"
```
Then in each consumer repo whose CLAUDE.md / `.bws-secrets.toml` changed:
```bash
cd ~/Projects/FacelessTT   # repeat per consumer
git add CLAUDE.md .bws-secrets.toml
git commit -m "docs: add generated security governance stanza"
```

**✅ Phase 2 complete:** every build agent's CLAUDE.md declares its class, lane, and governance, all projected from one manifest and verifiable with `make verify`. Onboarding a new build agent = add a `[[repo]]` entry + `make sync`.

---

## Notes for the Executor

- **Two repos, separate commits.** Detector files leave infraops (Task 2) and land in security-standards. Don't squash across repos.
- **Expected one-time URGENT:** editing `security-scan.sh` (Task 6) changes the deployed hash, so the next 3am `security-drift` run emits one "scanner hash changed — verify intentional" alert by design; it self-clears after recording the new hash. Don't treat it as a regression.
- **`security-drift` needs no code change** — it binds to the deployed path `~/.claude/bin/security-scan.sh` (via `paths.ts`, overridable by `SECURITY_SCAN_PATH`), not a repo path.
- **Never commit a literal BWS token.** The `bws-write-guard` hook will block it; `.bws-secrets.toml` carries UUIDs only.
