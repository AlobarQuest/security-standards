import argparse
import json
import sys
from pathlib import Path
from security_scan import predicates, manifest, allowlist as allowlist_mod
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
