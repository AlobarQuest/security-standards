import argparse
import json
import sys
from pathlib import Path
from security_scan import predicates, manifest, repo, allowlist as allowlist_mod
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
    if not repo.is_git_repo(repo_path):
        # Fail closed: a scan that cannot read the repo via git must not report "clean".
        err = Finding(rule_id="scan.not-a-git-repo", severity=Severity.BLOCK,
                      file=None, line=None,
                      evidence=f"not a git repository (or git unavailable): {repo_path}",
                      remediation="Run the scanner from inside a git repository; the scan relies on "
                                  "git to enumerate tracked files and history.",
                      reason="A security scan that cannot read the repo must fail closed, not pass.",
                      kind="deterministic")
        by_sev = {s.value: 0 for s in Severity}
        by_sev["BLOCK"] = 1
        report = {"meta": {"rules_source": "none", "rules_evaluated": 0, "allowlisted": 0},
                  "summary": {"by_severity": by_sev, "total": 1},
                  "findings": [err.to_dict()], "allowlisted": []}
        return report, 1
    rules, source = load_rules(category=category, cache_path=cache_path)
    uses_bws = bool(manifest.referenced_uuids(repo_path))
    findings: list[Finding] = []
    for rule in rules:
        kind = rule["check"]["kind"]
        if kind in ("manifest_present", "manifest_matches_usage"):
            findings += _manifest_findings(rule, repo_path)
        elif kind == "judgment":
            findings.append(_judgment_finding(rule))
        elif kind == "gitignore_covers":
            # Defense-in-depth, scoped to v1 (BWS): only require secret-file gitignore coverage
            # in repos that actually consume BWS secrets. A repo handling no BWS secrets is not
            # BLOCKed for lacking *.env/*.key patterns it has no use for (avoids false-positive gates).
            if uses_bws:
                findings += predicates.evaluate(rule, repo_path)
        else:
            findings += predicates.evaluate(rule, repo_path)

    entries = allowlist_mod.load(repo_path)
    active, suppressed = [], []
    for f in findings:
        (suppressed if allowlist_mod.is_allowed(f, entries) else active).append(f)

    by_sev = {s.value: 0 for s in Severity}
    for f in active:
        by_sev[f.severity.value] += 1
    report = {
        "meta": {"rules_source": source, "rules_evaluated": len(rules),
                 "allowlisted": len(suppressed)},
        "summary": {"by_severity": by_sev, "total": len(active)},
        "findings": [f.to_dict() for f in active],
        "allowlisted": [f.to_dict() for f in suppressed],
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
