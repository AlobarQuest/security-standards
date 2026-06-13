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
