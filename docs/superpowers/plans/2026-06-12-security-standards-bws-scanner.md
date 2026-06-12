# Security Standards Enforcement (v1: BWS) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic security scanner (+ a Claude Code skill wrapper) that checks any repo against BWS-usage security rules sourced from infra-brain, emitting findings with concrete remediation.

**Architecture:** A dependency-free Python package (`security_scan`) is the shared core: it loads `security` rules from infra-brain (with a bundled cache fallback), evaluates *repo predicates* (regex over tracked files / git history, `.gitignore` coverage, path presence) plus a `.bws-secrets.toml` manifest cross-check, and prints findings JSON (non-zero exit on any BLOCK). A Claude Code skill runs that scanner, then layers agent judgment. A CI workflow runs the same scanner.

**Tech Stack:** Python 3.12+ (stdlib only: `argparse`, `urllib`, `tomllib`, `subprocess`, `re`, `dataclasses`); `pytest` for tests; `git` CLI; infra-brain REST API.

Spec: `docs/superpowers/specs/2026-06-12-security-standards-enforcement-design.md`.

---

## File Structure

```
security-standards/
  pyproject.toml                     # package + pytest config
  src/security_scan/
    __init__.py
    findings.py                      # Severity, Finding, redact()
    repo.py                          # git helpers (tracked/history grep, check-ignore)
    predicates.py                    # predicate evaluators (forbidden_pattern, gitignore_covers, ...)
    rules.py                         # Rule model + load_rules (infra-brain live + cache)
    manifest.py                      # parse .bws-secrets.toml + referenced-UUID diff
    cli.py                           # orchestration + JSON output + exit code
    rules_cache.json                 # bundled v1 BWS rules (fallback + seed source)
  tests/
    conftest.py                      # git-repo fixture builder
    test_findings.py
    test_repo.py
    test_predicates.py
    test_rules.py
    test_manifest.py
    test_cli.py
  skill/SKILL.md                     # the Claude Code skill (surface A)
  scripts/seed_infrabrain_rules.py   # push rules_cache.json into infra-brain via add_rule
  .github/workflows/security-scan.yml
  README.md
```

**Predicate `check` schema** (the JSON shape stored in each infra-brain rule's `check`, and in `rules_cache.json`):
```json
{ "kind": "forbidden_pattern", "pattern": "0\\.[0-9a-f-]{36}\\.[A-Za-z0-9+/=:_-]{20,}", "scope": "tracked" }
{ "kind": "gitignore_covers", "globs": ["*.env", "**/env", "*-migration/"] }
{ "kind": "path_absent", "glob": ".env" }
{ "kind": "required_pattern", "pattern": "...", "globs": ["..."] }
{ "kind": "manifest_present" }
{ "kind": "manifest_matches_usage" }
{ "kind": "judgment" }
```

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/security_scan/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

`tests/test_smoke.py`:
```python
def test_package_imports():
    import security_scan
    assert security_scan.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: FAIL (ModuleNotFoundError: security_scan)

- [ ] **Step 3: Create the package + config**

`pyproject.toml`:
```toml
[project]
name = "security-scan"
version = "0.1.0"
requires-python = ">=3.12"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

`src/security_scan/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/conftest.py`:
```python
import subprocess
import pytest


def _run(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path):
    """A real, empty, committed git repo. Returns a helper to add/commit files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q")
    _run(repo, "git", "config", "user.email", "t@t.t")
    _run(repo, "git", "config", "user.name", "t")

    class Helper:
        path = repo

        def write(self, rel, content):
            f = repo / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content)
            return f

        def commit(self, msg="c"):
            _run(repo, "git", "add", "-A")
            _run(repo, "git", "commit", "-q", "-m", msg)

    return Helper()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "chore: scaffold security_scan package + pytest"
```

---

## Task 2: Findings model + redaction

**Files:**
- Create: `src/security_scan/findings.py`
- Test: `tests/test_findings.py`

- [ ] **Step 1: Write the failing test**

`tests/test_findings.py`:
```python
from security_scan.findings import Severity, Finding, redact


def test_redact_masks_secret_tail_but_keeps_short_prefix():
    secret = "0.45eb083f-4b05-4251-924d-b46700e5a643.SECRETKEYPART:MOREMORE=="
    out = redact(secret)
    assert "SECRETKEYPART" not in out
    assert out.startswith("0.45eb08")
    assert "len" in out


def test_redact_fully_masks_short_values():
    assert redact("abcd") == "***"


def test_finding_to_dict_roundtrips():
    f = Finding(rule_id="r", severity=Severity.BLOCK, file="a.py", line=3,
                evidence="0.45eb08…", remediation="fix", reason="why", kind="deterministic")
    d = f.to_dict()
    assert d["severity"] == "BLOCK"
    assert d["file"] == "a.py" and d["line"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_findings.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

`src/security_scan/findings.py`:
```python
from dataclasses import dataclass, asdict
from enum import Enum


class Severity(str, Enum):
    BLOCK = "BLOCK"
    WARN = "WARN"
    INFO = "INFO"


@dataclass
class Finding:
    rule_id: str
    severity: Severity
    file: str | None
    line: int | None
    evidence: str          # MUST already be redacted
    remediation: str
    reason: str
    kind: str              # "deterministic" | "judgment"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


def redact(value: str) -> str:
    """Mask a matched secret: keep a short non-secret prefix, hide the rest.
    A scanner that printed the secret it found would itself be the leak."""
    if len(value) <= 12:
        return "***"
    return f"{value[:8]}…(len {len(value)})"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_findings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/findings.py tests/test_findings.py
git commit -m "feat: findings model + secret redaction"
```

---

## Task 3: Git helpers (repo.py)

**Files:**
- Create: `src/security_scan/repo.py`
- Test: `tests/test_repo.py`

- [ ] **Step 1: Write the failing test**

`tests/test_repo.py`:
```python
from security_scan import repo


def test_grep_tracked_finds_pattern_with_location(git_repo):
    git_repo.write("a.txt", "hello\nTOKEN=0.45eb083f-4b05-4251-924d-b46700e5a643.K:V==\n")
    git_repo.commit()
    hits = repo.grep_tracked(git_repo.path, r"0\.[0-9a-f-]{36}\.")
    assert len(hits) == 1
    assert hits[0].file == "a.txt" and hits[0].line == 2
    assert "0.45eb083f" in hits[0].match


def test_grep_tracked_ignores_untracked(git_repo):
    git_repo.write("tracked.txt", "clean\n")
    git_repo.commit()
    git_repo.write("untracked.txt", "0.45eb083f-4b05-4251-924d-b46700e5a643.K:V==\n")
    assert repo.grep_tracked(git_repo.path, r"0\.[0-9a-f-]{36}\.") == []


def test_grep_history_finds_removed_secret(git_repo):
    git_repo.write("a.txt", "0.45eb083f-4b05-4251-924d-b46700e5a643.K:V==\n")
    git_repo.commit("add secret")
    git_repo.write("a.txt", "clean\n")
    git_repo.commit("remove secret")
    assert repo.grep_tracked(git_repo.path, r"0\.[0-9a-f-]{36}\.") == []      # gone from worktree
    assert repo.grep_history(git_repo.path, r"0\.[0-9a-f-]{36}\.") is True     # still in history


def test_is_ignored(git_repo):
    git_repo.write(".gitignore", "*.env\n")
    git_repo.commit()
    assert repo.is_ignored(git_repo.path, "secrets.env") is True
    assert repo.is_ignored(git_repo.path, "main.py") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_repo.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

`src/security_scan/repo.py`:
```python
import re
import subprocess
from dataclasses import dataclass


@dataclass
class Hit:
    file: str
    line: int
    match: str


def _git(repo_path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo_path,
                          capture_output=True, text=True)


def tracked_files(repo_path) -> list[str]:
    out = _git(repo_path, "ls-files").stdout
    return [p for p in out.splitlines() if p]


def grep_tracked(repo_path, pattern: str) -> list[Hit]:
    """Regex search across git-tracked files in the working tree."""
    rx = re.compile(pattern)
    hits: list[Hit] = []
    for rel in tracked_files(repo_path):
        try:
            text = (repo_path / rel).read_text(errors="ignore") if hasattr(repo_path, "__truediv__") \
                else open(f"{repo_path}/{rel}", errors="ignore").read()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            m = rx.search(line)
            if m:
                hits.append(Hit(file=rel, line=i, match=m.group(0)))
    return hits


def grep_history(repo_path, pattern: str) -> bool:
    """True if the pattern appears anywhere in commit history (added or removed).
    Uses `git log -G<pattern>` which lists commits whose diff matches."""
    res = _git(repo_path, "log", "--all", "-G", pattern, "--oneline")
    return bool(res.stdout.strip())


def is_ignored(repo_path, path: str) -> bool:
    """True if `path` is covered by .gitignore (git check-ignore exits 0)."""
    res = _git(repo_path, "check-ignore", "-q", path)
    return res.returncode == 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_repo.py -v`
Expected: PASS

- [ ] **Step 5: Refactor note + commit**

The `grep_tracked` path handling is awkward (Path vs str). Normalize: at the top of `grep_tracked`, add `from pathlib import Path` and `repo_path = Path(repo_path)`, then `text = (repo_path / rel).read_text(errors="ignore")`. Re-run tests (PASS), then:

```bash
git add src/security_scan/repo.py tests/test_repo.py
git commit -m "feat: git helpers (tracked/history grep, check-ignore)"
```

---

## Task 4: Predicates — forbidden_pattern

**Files:**
- Create: `src/security_scan/predicates.py`
- Test: `tests/test_predicates.py`

- [ ] **Step 1: Write the failing test**

`tests/test_predicates.py`:
```python
from security_scan import predicates
from security_scan.findings import Severity


def _rule(check, severity=Severity.BLOCK, rid="bws.test"):
    return {"id": rid, "severity": severity, "check": check,
            "remediation": "fix it", "reason": "because"}


def test_forbidden_pattern_tracked_redacts_and_locates(git_repo):
    git_repo.write("a.sh", "TOK=0.45eb083f-4b05-4251-924d-b46700e5a643.SECRETPART:MOREMORE==\n")
    git_repo.commit()
    rule = _rule({"kind": "forbidden_pattern",
                  "pattern": r"0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}", "scope": "tracked"})
    findings = predicates.evaluate(rule, git_repo.path)
    assert len(findings) == 1
    f = findings[0]
    assert f.file == "a.sh" and f.line == 1
    assert "SECRETPART" not in f.evidence       # redacted
    assert f.rule_id == "bws.test" and f.severity == Severity.BLOCK


def test_forbidden_pattern_history_scope(git_repo):
    git_repo.write("a.txt", "0.45eb083f-4b05-4251-924d-b46700e5a643.K:V==\n")
    git_repo.commit()
    git_repo.write("a.txt", "clean\n")
    git_repo.commit()
    rule = _rule({"kind": "forbidden_pattern",
                  "pattern": r"0\.[0-9a-f-]{36}\.", "scope": "history"})
    findings = predicates.evaluate(rule, git_repo.path)
    assert len(findings) == 1
    assert "history" in findings[0].evidence.lower()


def test_clean_repo_yields_nothing(git_repo):
    git_repo.write("a.py", "print('hi')\n")
    git_repo.commit()
    rule = _rule({"kind": "forbidden_pattern", "pattern": r"0\.[0-9a-f-]{36}\.", "scope": "tracked"})
    assert predicates.evaluate(rule, git_repo.path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predicates.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

`src/security_scan/predicates.py`:
```python
from pathlib import Path
from security_scan import repo
from security_scan.findings import Finding, redact


def _finding(rule, file, line, evidence, kind="deterministic") -> Finding:
    return Finding(rule_id=rule["id"], severity=rule["severity"], file=file, line=line,
                   evidence=evidence, remediation=rule["remediation"],
                   reason=rule["reason"], kind=kind)


def _forbidden_pattern(rule, repo_path) -> list[Finding]:
    check = rule["check"]
    scope = check.get("scope", "tracked")
    pattern = check["pattern"]
    if scope == "history":
        if repo.grep_history(repo_path, pattern):
            return [_finding(rule, file=None, line=None,
                             evidence="pattern present in git history")]
        return []
    # tracked (default)
    return [_finding(rule, file=h.file, line=h.line, evidence=redact(h.match))
            for h in repo.grep_tracked(repo_path, pattern)]


_DISPATCH = {
    "forbidden_pattern": _forbidden_pattern,
}


def evaluate(rule, repo_path) -> list[Finding]:
    """Evaluate one rule against a repo; returns findings (possibly empty)."""
    repo_path = Path(repo_path)
    kind = rule["check"]["kind"]
    handler = _DISPATCH.get(kind)
    if handler is None:
        return []   # unknown/judgment kinds handled elsewhere
    return handler(rule, repo_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predicates.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/predicates.py tests/test_predicates.py
git commit -m "feat: forbidden_pattern predicate (tracked + history)"
```

---

## Task 5: Predicates — gitignore_covers, path_absent, required_pattern

**Files:**
- Modify: `src/security_scan/predicates.py`
- Test: `tests/test_predicates.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_predicates.py`)

```python
def test_gitignore_covers_flags_uncovered_secret_file(git_repo):
    git_repo.write(".gitignore", "*.key\n")          # covers *.key but NOT *.env
    git_repo.commit()
    rule = _rule({"kind": "gitignore_covers", "globs": ["*.env", "*.key"]})
    findings = predicates.evaluate(rule, git_repo.path)
    assert len(findings) == 1
    assert "*.env" in findings[0].evidence


def test_path_absent_flags_committed_dotenv(git_repo):
    git_repo.write(".env", "X=1\n")
    git_repo.commit()
    rule = _rule({"kind": "path_absent", "glob": ".env"})
    findings = predicates.evaluate(rule, git_repo.path)
    assert len(findings) == 1
    assert findings[0].file == ".env"


def test_required_pattern_passes_when_present(git_repo):
    git_repo.write("start.sh", "fetch_bws_secret 45eb083f\n")
    git_repo.commit()
    rule = _rule({"kind": "required_pattern", "pattern": "fetch_bws_secret",
                  "globs": ["*.sh"]}, severity=Severity.WARN)
    assert predicates.evaluate(rule, git_repo.path) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_predicates.py -v`
Expected: FAIL (new tests error — handlers missing)

- [ ] **Step 3: Add the handlers** (append to `predicates.py`, and register in `_DISPATCH`)

```python
import fnmatch


def _gitignore_covers(rule, repo_path) -> list[Finding]:
    findings = []
    for glob in rule["check"]["globs"]:
        # synthesize a representative path the glob should match, then ask git if it's ignored.
        # directory globs ("foo/") need a path *inside* the dir to trigger check-ignore.
        if glob.endswith("/"):
            probe = glob[:-1].replace("*", "x") + "/probe"
        else:
            probe = glob.replace("*", "x")
        if not repo.is_ignored(repo_path, probe):
            findings.append(_finding(rule, file=".gitignore", line=None,
                                     evidence=f"glob not covered: {glob}"))
    return findings


def _path_absent(rule, repo_path) -> list[Finding]:
    glob = rule["check"]["glob"]
    matches = [p for p in repo.tracked_files(repo_path) if fnmatch.fnmatch(p, glob)]
    return [_finding(rule, file=m, line=None, evidence=f"tracked path matches {glob}")
            for m in matches]


def _required_pattern(rule, repo_path) -> list[Finding]:
    import re
    rx = re.compile(rule["check"]["pattern"])
    globs = rule["check"].get("globs", ["*"])
    relevant = [p for p in repo.tracked_files(repo_path)
                if any(fnmatch.fnmatch(p, g) for g in globs)]
    if not relevant:
        return []
    for rel in relevant:
        try:
            if rx.search((repo_path / rel).read_text(errors="ignore")):
                return []   # found somewhere → satisfied
        except OSError:
            continue
    return [_finding(rule, file=None, line=None,
                     evidence=f"required pattern absent in {globs}")]
```

Register them:
```python
_DISPATCH.update({
    "gitignore_covers": _gitignore_covers,
    "path_absent": _path_absent,
    "required_pattern": _required_pattern,
})
```

- [ ] **Step 4: Run to verify all pass**

Run: `python -m pytest tests/test_predicates.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/predicates.py tests/test_predicates.py
git commit -m "feat: gitignore_covers, path_absent, required_pattern predicates"
```

---

## Task 6: Rules source (infra-brain live + cache fallback)

**Files:**
- Create: `src/security_scan/rules.py`
- Create: `src/security_scan/rules_cache.json` (minimal stub now; full rules in Task 9)
- Test: `tests/test_rules.py`

- [ ] **Step 1: Write the failing test**

`tests/test_rules.py`:
```python
import json
from security_scan import rules


def test_load_from_cache_when_no_infrabrain(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps([
        {"id": "bws.x", "severity": "BLOCK",
         "check": {"kind": "forbidden_pattern", "pattern": "p", "scope": "tracked"},
         "remediation": "r", "reason": "y"}
    ]))
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    loaded, source = rules.load_rules(category="security", cache_path=cache)
    assert source == "cache"
    assert loaded[0]["id"] == "bws.x"
    assert loaded[0]["severity"].value == "BLOCK"   # coerced to Severity


def test_live_fetch_filters_to_rules_with_checks(monkeypatch, tmp_path):
    def fake_get(url, headers, timeout):
        return {"rules": [
            {"id": 1, "rule": "no token", "reason": "leak", "severity": "BLOCK",
             "check": {"kind": "forbidden_pattern", "pattern": "p", "scope": "tracked"},
             "remediation": "r"},
            {"id": 2, "rule": "prose only", "reason": "x", "severity": "INFO", "check": None},
        ]}
    monkeypatch.setattr(rules, "_http_get_json", fake_get)
    monkeypatch.setenv("INFRABRAIN_BASE_URL", "https://ib.example")
    monkeypatch.setenv("INFRABRAIN_ACCESS_KEY", "k")
    loaded, source = rules.load_rules(category="security", cache_path=tmp_path / "nope.json")
    assert source == "live"
    assert len(loaded) == 1 and loaded[0]["id"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_rules.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

`src/security_scan/rules.py`:
```python
import json
import os
import urllib.request
from pathlib import Path
from security_scan.findings import Severity


def _http_get_json(url: str, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _coerce(rule: dict) -> dict:
    rule = dict(rule)
    sev = rule.get("severity", "INFO")
    rule["severity"] = sev if isinstance(sev, Severity) else Severity(sev)
    # infra-brain's add_rule has no `remediation` field, so live rules carry it folded into
    # `reason` (see seed script). Default it so downstream rule["remediation"] is always safe.
    rule.setdefault("remediation", rule.get("reason", ""))
    return rule


def _fetch_live(category: str) -> list[dict] | None:
    base = os.environ.get("INFRABRAIN_BASE_URL")
    key = os.environ.get("INFRABRAIN_ACCESS_KEY")
    if not base or not key:
        return None
    try:
        data = _http_get_json(f"{base.rstrip('/')}/api/rules?category={category}",
                              headers={"x-brain-key": key}, timeout=10)
    except Exception:
        return None
    return [r for r in data.get("rules", []) if r.get("check")]


def load_rules(category: str, cache_path: Path) -> tuple[list[dict], str]:
    """Returns (rules, source) where source is 'live' or 'cache'.
    Rules are filtered to those carrying a `check`, with severity coerced to Severity."""
    live = _fetch_live(category)
    if live is not None:
        return [_coerce(r) for r in live], "live"
    cached = json.loads(Path(cache_path).read_text())
    return [_coerce(r) for r in cached], "cache"
```

`src/security_scan/rules_cache.json` (stub — full set in Task 9):
```json
[]
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_rules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/rules.py src/security_scan/rules_cache.json tests/test_rules.py
git commit -m "feat: rule loading (infra-brain live + cache fallback)"
```

---

## Task 7: Manifest (parse + referenced-UUID diff)

**Files:**
- Create: `src/security_scan/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

`tests/test_manifest.py`:
```python
from security_scan import manifest


def test_referenced_uuids_only_in_bws_context(git_repo):
    git_repo.write("start.sh",
        'fetch_bws_secret "45eb083f-4b05-4251-924d-b46700e5a643"\n'
        'UNRELATED_UUID = "11111111-2222-3333-4444-555555555555"\n')   # not a bws line
    git_repo.commit()
    found = manifest.referenced_uuids(git_repo.path)
    assert "45eb083f-4b05-4251-924d-b46700e5a643" in found
    assert "11111111-2222-3333-4444-555555555555" not in found


def test_parse_declared_uuids(git_repo):
    git_repo.write(".bws-secrets.toml",
        '[[secret]]\nuuid = "45eb083f-4b05-4251-924d-b46700e5a643"\nname = "X"\npurpose = "p"\n')
    git_repo.commit()
    assert manifest.declared_uuids(git_repo.path) == {"45eb083f-4b05-4251-924d-b46700e5a643"}


def test_diff_reports_undeclared_and_stale(git_repo):
    git_repo.write("start.sh", 'bws secret get 45eb083f-4b05-4251-924d-b46700e5a643\n')
    git_repo.write(".bws-secrets.toml",
        '[[secret]]\nuuid = "99999999-0000-0000-0000-000000000000"\nname="Y"\npurpose="p"\n')
    git_repo.commit()
    d = manifest.diff(git_repo.path)
    assert d.undeclared == {"45eb083f-4b05-4251-924d-b46700e5a643"}
    assert d.stale == {"99999999-0000-0000-0000-000000000000"}
    assert d.manifest_exists is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_manifest.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

`src/security_scan/manifest.py`:
```python
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from security_scan import repo

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_UUID_RX = re.compile(_UUID)
# A UUID "referenced as a BWS secret" = a UUID on a line mentioning bws / a secret-id var.
_BWS_LINE_RX = re.compile(r"(?i)(bws\s+secret|fetch_bws_secret|BWS_\w*SECRET_ID|BWS_ACCESS)")

MANIFEST = ".bws-secrets.toml"


def referenced_uuids(repo_path) -> set[str]:
    repo_path = Path(repo_path)
    found: set[str] = set()
    for rel in repo.tracked_files(repo_path):
        if rel == MANIFEST:
            continue
        try:
            text = (repo_path / rel).read_text(errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if _BWS_LINE_RX.search(line):
                found.update(_UUID_RX.findall(line))
    return found


def declared_uuids(repo_path) -> set[str]:
    p = Path(repo_path) / MANIFEST
    if not p.exists():
        return set()
    data = tomllib.loads(p.read_text())
    return {s["uuid"] for s in data.get("secret", []) if "uuid" in s}


@dataclass
class ManifestDiff:
    manifest_exists: bool
    undeclared: set[str]   # referenced in code, not in manifest
    stale: set[str]        # in manifest, not referenced


def diff(repo_path) -> ManifestDiff:
    refd = referenced_uuids(repo_path)
    decl = declared_uuids(repo_path)
    exists = (Path(repo_path) / MANIFEST).exists()
    return ManifestDiff(manifest_exists=exists,
                        undeclared=refd - decl,
                        stale=decl - refd)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_manifest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/manifest.py tests/test_manifest.py
git commit -m "feat: secret manifest parsing + usage diff"
```

---

## Task 8: CLI orchestration

**Files:**
- Create: `src/security_scan/cli.py`
- Modify: `pyproject.toml` (add console entry point)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
import json
from security_scan import cli


def _cache(tmp_path, rules):
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(rules))
    return p


def test_scan_reports_block_and_exit_nonzero(git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    git_repo.write("a.sh", "T=0.45eb083f-4b05-4251-924d-b46700e5a643.SECRET:MOREMORE==\n")
    git_repo.commit()
    cache = _cache(tmp_path, [{
        "id": "bws.no-token-in-tracked-files", "severity": "BLOCK",
        "check": {"kind": "forbidden_pattern",
                  "pattern": r"0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}", "scope": "tracked"},
        "remediation": "remove it", "reason": "leak"}])
    report, exit_code = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    assert exit_code == 1
    assert report["summary"]["by_severity"]["BLOCK"] == 1
    assert report["meta"]["rules_source"] == "cache"
    assert "SECRET" not in json.dumps(report)        # redacted end-to-end


def test_judgment_rule_emitted_as_placeholder(git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    git_repo.write("a.py", "ok\n"); git_repo.commit()
    cache = _cache(tmp_path, [{
        "id": "bws.least-privilege-scope", "severity": "INFO",
        "check": {"kind": "judgment"}, "remediation": "review scope", "reason": "least privilege"}])
    report, exit_code = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    assert exit_code == 0
    assert report["findings"][0]["kind"] == "judgment"


def test_manifest_rules(git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    git_repo.write("start.sh", "bws secret get 45eb083f-4b05-4251-924d-b46700e5a643\n")
    git_repo.commit()
    cache = _cache(tmp_path, [
        {"id": "bws.secret-manifest-present", "severity": "WARN",
         "check": {"kind": "manifest_present"}, "remediation": "add manifest", "reason": "declare"},
        {"id": "bws.manifest-matches-usage", "severity": "WARN",
         "check": {"kind": "manifest_matches_usage"}, "remediation": "sync", "reason": "honest"}])
    report, _ = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    ids = {f["rule_id"] for f in report["findings"]}
    assert "bws.secret-manifest-present" in ids        # no manifest, but BWS used
    assert "bws.manifest-matches-usage" in ids          # undeclared uuid
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

`src/security_scan/cli.py`:
```python
import argparse
import json
import sys
from pathlib import Path
from security_scan import predicates, manifest
from security_scan.findings import Finding, Severity
from security_scan.rules import load_rules

_DEFAULT_CACHE = Path(__file__).with_name("rules_cache.json")


def _manifest_findings(rule, repo_path) -> list[Finding]:
    kind = rule["check"]["kind"]
    d = manifest.diff(repo_path)
    uses_bws = bool(manifest.referenced_uuids(repo_path))
    out: list[Finding] = []

    def mk(evidence):
        return Finding(rule_id=rule["id"], severity=rule["severity"], file=manifest.MANIFEST,
                       line=None, evidence=evidence, remediation=rule["remediation"],
                       reason=rule["reason"], kind="deterministic")

    if kind == "manifest_present":
        if uses_bws and not d.manifest_exists:
            out.append(mk("repo references BWS secrets but has no .bws-secrets.toml"))
    elif kind == "manifest_matches_usage":
        if d.undeclared:
            out.append(mk(f"undeclared UUIDs in code: {sorted(d.undeclared)}"))
        if d.stale:
            out.append(mk(f"stale manifest entries (unused): {sorted(d.stale)}"))
    return out


def _judgment_finding(rule) -> Finding:
    return Finding(rule_id=rule["id"], severity=rule["severity"], file=None, line=None,
                   evidence="requires agent judgment", remediation=rule["remediation"],
                   reason=rule["reason"], kind="judgment")


def scan(repo_path, cache_path=_DEFAULT_CACHE, category="security") -> tuple[dict, int]:
    repo_path = Path(repo_path)
    rules, source = load_rules(category=category, cache_path=cache_path)
    findings: list[Finding] = []
    for rule in rules:
        kind = rule["check"]["kind"]
        if kind in ("manifest_present", "manifest_matches_usage"):
            findings += _manifest_findings(rule, repo_path)
        elif kind == "judgment":
            findings.append(_judgment_finding(rule))
        else:
            findings += predicates.evaluate(rule, repo_path)

    by_sev = {s.value: 0 for s in Severity}
    for f in findings:
        by_sev[f.severity.value] += 1
    report = {
        "meta": {"rules_source": source, "rules_evaluated": len(rules)},
        "summary": {"by_severity": by_sev, "total": len(findings)},
        "findings": [f.to_dict() for f in findings],
    }
    exit_code = 1 if by_sev["BLOCK"] > 0 else 0
    return report, exit_code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Scan a repo against security standards (infra-brain).")
    ap.add_argument("repo", nargs="?", default=".", help="repo path (default: cwd)")
    ap.add_argument("--category", default="security")
    ap.add_argument("--cache", default=str(_DEFAULT_CACHE))
    args = ap.parse_args(argv)
    report, code = scan(repo_path=args.repo, cache_path=args.cache, category=args.category)
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
```

Add to `pyproject.toml` under `[project]`:
```toml
[project.scripts]
security-scan = "security_scan.cli:main"
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite + commit**

Run: `python -m pytest -q`
Expected: all PASS

```bash
git add src/security_scan/cli.py pyproject.toml tests/test_cli.py
git commit -m "feat: scan orchestration + CLI + exit codes"
```

---

## Task 9: v1 BWS rule set (cache + infra-brain seed)

**Files:**
- Modify: `src/security_scan/rules_cache.json` (the 8 v1 rules)
- Create: `scripts/seed_infrabrain_rules.py`
- Test: `tests/test_cli.py` (append a dogfood-style integration test)

- [ ] **Step 1: Write the failing test** (append to `tests/test_cli.py`)

```python
def test_bundled_cache_has_v1_bws_rules():
    from security_scan.cli import _DEFAULT_CACHE
    import json as _json
    rules = _json.loads(_DEFAULT_CACHE.read_text())
    ids = {r["id"] for r in rules}
    assert {
        "bws.no-token-in-tracked-files", "bws.no-token-in-git-history",
        "bws.secret-files-gitignored", "bws.bootstrap-token-not-inline",
        "bws.reference-by-stable-uuid", "bws.secret-manifest-present",
        "bws.manifest-matches-usage", "bws.least-privilege-scope",
    } <= ids
    for r in rules:
        assert r["severity"] in ("BLOCK", "WARN", "INFO")
        assert "check" in r and "remediation" in r and "reason" in r
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cli.py::test_bundled_cache_has_v1_bws_rules -v`
Expected: FAIL (cache is `[]`)

- [ ] **Step 3: Fill `src/security_scan/rules_cache.json`** with the 8 v1 rules

```json
[
  {"id": "bws.no-token-in-tracked-files", "severity": "BLOCK",
   "reason": "A committed BWS machine-account token is a credential leak.",
   "check": {"kind": "forbidden_pattern", "pattern": "0\\.[0-9a-f-]{36}\\.[A-Za-z0-9+/=:_-]{20,}", "scope": "tracked"},
   "remediation": "Remove the token; move it to a gitignored env file sourced at runtime; ROTATE the exposed token."},

  {"id": "bws.no-token-in-git-history", "severity": "BLOCK",
   "reason": "Git history retains a token even after it is removed from the working tree.",
   "check": {"kind": "forbidden_pattern", "pattern": "0\\.[0-9a-f-]{36}\\.[A-Za-z0-9+/=:_-]{20,}", "scope": "history"},
   "remediation": "Rotate/revoke the token; optionally scrub history with git filter-repo."},

  {"id": "bws.bootstrap-token-not-inline", "severity": "BLOCK",
   "reason": "The bootstrap BWS_ACCESS_TOKEN must never be inline in committed config.",
   "check": {"kind": "forbidden_pattern", "pattern": "BWS_ACCESS_TOKEN\\s*[=:]\\s*['\"]?0\\.", "scope": "tracked"},
   "remediation": "Source BWS_ACCESS_TOKEN from a gitignored env file; never inline it in a plist/compose/script."},

  {"id": "bws.secret-files-gitignored", "severity": "BLOCK",
   "reason": "Files that hold BWS secrets must be gitignored so the next commit can't leak them.",
   "check": {"kind": "gitignore_covers", "globs": ["*.env", "*-migration/", "*.password", "*.key"]},
   "remediation": "Add the secret-bearing path/pattern to .gitignore."},

  {"id": "bws.reference-by-stable-uuid", "severity": "WARN",
   "reason": "The secret UUID is immutable; the name is a mutable label that will be renamed and break by-name fetches.",
   "check": {"kind": "forbidden_pattern", "pattern": "fetch_bws_secret_by_name", "scope": "tracked"},
   "remediation": "Reference secrets by stable UUID (bws secret get <uuid>), not by name. The UUID is non-secret, so hardcoding it is fine."},

  {"id": "bws.secret-manifest-present", "severity": "WARN",
   "reason": "Repos that consume BWS secrets must declare which UUIDs they use.",
   "check": {"kind": "manifest_present"},
   "remediation": "Add a .bws-secrets.toml declaring the secret UUIDs this repo consumes."},

  {"id": "bws.manifest-matches-usage", "severity": "WARN",
   "reason": "The manifest must match reality or it rots into fiction.",
   "check": {"kind": "manifest_matches_usage"},
   "remediation": "Add undeclared UUIDs to the manifest; remove stale entries."},

  {"id": "bws.least-privilege-scope", "severity": "INFO",
   "reason": "A workload's machine-account should be scoped to only the projects its secrets need.",
   "check": {"kind": "judgment"},
   "remediation": "Using the manifest's UUIDs, confirm the workload's machine-account is scoped to only the projects those secrets live in."}
]
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_cli.py::test_bundled_cache_has_v1_bws_rules -v`
Expected: PASS

- [ ] **Step 5: Write the infra-brain seed script** (`scripts/seed_infrabrain_rules.py`)

```python
"""Seed/refresh the v1 BWS security rules into infra-brain.
Run by a human/agent with infra-brain MCP access OR direct REST add_rule.
This script PRINTS the add_rule payloads; it does not call the API itself
(keeps it credential-free and reviewable). Pipe into your infra-brain client."""
import json
from pathlib import Path

cache = Path(__file__).resolve().parents[1] / "src/security_scan/rules_cache.json"
for r in json.loads(cache.read_text()):
    # infra-brain's add_rule takes (severity, category, rule, reason, check) — no remediation
    # field — so fold the remediation into `reason`. The scanner's _coerce defaults
    # rule["remediation"] from reason, so a live-loaded rule still surfaces a usable remediation.
    print(json.dumps({
        "category": "security",
        "severity": r["severity"],
        "rule": r["id"],
        "reason": f'{r["reason"]} — FIX: {r["remediation"]}',
        "check": r["check"],
    }))
```

> The cache file (`rules_cache.json`) remains the authoritative source for the split
> `reason`/`remediation` fields and powers offline/CI runs; this script just mirrors them into
> infra-brain for live runs.

- [ ] **Step 6: Commit**

```bash
git add src/security_scan/rules_cache.json scripts/seed_infrabrain_rules.py tests/test_cli.py
git commit -m "feat: v1 BWS rule set (bundled cache + infra-brain seed script)"
```

---

## Task 10: The Claude Code skill (surface A)

**Files:**
- Create: `skill/SKILL.md`

- [ ] **Step 1: Write the skill**

`skill/SKILL.md`:
```markdown
---
name: security-standards
description: Use when checking whether a repo follows security standards (BWS secret-handling) — e.g. before declaring work done, during review, or on request. Runs a deterministic scanner against infra-brain security rules, then applies agent judgment, and guides/fixes violations.
---

# Security Standards Enforcement

You enforce the security standards captured in infra-brain (`category: security`) against the
current repo. The first standard set is BWS (Bitwarden Secrets Manager) proper usage.

## Steps

1. **Run the deterministic scanner** from the repo root:
   `python -m security_scan.cli . --category security`
   (Install once: `pip install -e <path-to>/security-standards`. It reads rules live from
   infra-brain if `INFRABRAIN_BASE_URL`/`INFRABRAIN_ACCESS_KEY` are set, else the bundled cache.)

2. **Read the findings JSON.** For each finding: `severity`, `file:line`, `evidence` (redacted),
   `remediation`, `reason`, `kind`.

3. **Judgment layer** — for findings with `kind: "judgment"` (e.g. `bws.least-privilege-scope`):
   read the repo's `.bws-secrets.toml`, determine which projects those UUIDs live in, and reason
   about whether the workload's machine-account is over-scoped. State your assessment.

4. **Fix or guide:**
   - **BLOCK** findings: fix mechanical ones (gitignore an entry, strip a literal token, relocate a
     token to a gitignored env file). **If you surface a real committed token, treat it as leaked —
     tell the human to ROTATE it; do not just delete it.**
   - **WARN/INFO**: fix the cheap ones (add a manifest entry); for judgment ones, present the
     finding + your assessment to the human.

5. **Never print a secret value** you discover. The scanner redacts; you do too.

## Guardrails
- Read-only by default; confirm before outward-facing or irreversible actions.
- The scanner is the source of truth for deterministic checks — don't re-implement them by eye.
```

- [ ] **Step 2: Verify the skill installs/loads** (manual)

Run: install the skill per the environment's skill mechanism (symlink `skill/` into the skills dir, or package it). Confirm it appears in the skill list. (No automated test — skills are markdown.)

- [ ] **Step 3: Commit**

```bash
git add skill/SKILL.md
git commit -m "feat: security-standards Claude Code skill (surface A)"
```

---

## Task 11: CI workflow + README + dogfood

**Files:**
- Create: `.github/workflows/security-scan.yml`
- Create: `README.md`

- [ ] **Step 1: CI workflow** (`.github/workflows/security-scan.yml`)

```yaml
name: Security Scan
on:
  push:
  pull_request:
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # full history for the history-scope check
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e .
      - name: Security scan (fails on BLOCK)
        run: python -m security_scan.cli . --category security
```

> The CI run uses the bundled `rules_cache.json` (hermetic). To use live infra-brain rules instead,
> add `INFRABRAIN_BASE_URL` + `INFRABRAIN_ACCESS_KEY` as repo secrets and `env:` them onto the step.

- [ ] **Step 2: README** (`README.md`)

```markdown
# security-standards

Deterministic + judgment-based enforcement of security standards (v1: BWS secret handling).
Rules live in infra-brain (`category: security`); the scanner evaluates a repo and emits findings
with remediation. Surfaces: a Claude Code skill (`skill/SKILL.md`) and CI (`security-scan`).

## Use
- One-off: `python -m security_scan.cli <repo> --category security`
- CI: see `.github/workflows/security-scan.yml`
- Agent: invoke the `security-standards` skill.

Design: `docs/superpowers/specs/2026-06-12-security-standards-enforcement-design.md`.
```

- [ ] **Step 3: Dogfood the scanner against a known-dirty and known-clean repo** (manual verification)

Run against this repo (should be clean — its `.gitignore` blocks secrets):
`python -m security_scan.cli . --category security` → expect exit 0, no BLOCK.

Run against `~/Projects/vps-backup` (its history once contained a committed token):
`python -m security_scan.cli ~/Projects/vps-backup --category security`
→ expect `bws.no-token-in-git-history` to fire (BLOCK), confirming the history check works on a real case.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/security-scan.yml README.md
git commit -m "ci: security scan workflow + README"
```

---

## Done criteria
- `python -m pytest -q` all green.
- `python -m security_scan.cli .` on this repo → exit 0.
- `python -m security_scan.cli ~/Projects/vps-backup` → flags `bws.no-token-in-git-history`.
- The 8 v1 rules exist in `rules_cache.json` and are seeded into infra-brain (`category: security`).
- The `security-standards` skill is installed and runs the scanner end-to-end.
