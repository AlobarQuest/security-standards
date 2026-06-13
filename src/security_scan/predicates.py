import fnmatch
import re
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
        return [_finding(rule, file=None, line=None,
                         evidence=f"pattern present in git history (commit {sha[:12]})")
                for sha in repo.grep_history(repo_path, pattern)]
    # tracked (default)
    return [_finding(rule, file=h.file, line=h.line, evidence=redact(h.match))
            for h in repo.grep_tracked(repo_path, pattern)]


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


_DISPATCH = {
    "forbidden_pattern": _forbidden_pattern,
    "gitignore_covers": _gitignore_covers,
    "path_absent": _path_absent,
    "required_pattern": _required_pattern,
}


def evaluate(rule, repo_path) -> list[Finding]:
    """Evaluate one rule against a repo; returns findings (possibly empty)."""
    repo_path = Path(repo_path)
    kind = rule["check"]["kind"]
    handler = _DISPATCH.get(kind)
    if handler is None:
        return []   # unknown/judgment kinds handled elsewhere
    return handler(rule, repo_path)
