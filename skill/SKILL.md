---
name: security-standards
description: Use when checking whether a repo follows security standards (BWS secret-handling) — e.g. before declaring work done, during review, or on request. Runs a deterministic scanner against infra-brain security rules, then applies agent judgment, and guides/fixes violations.
---

# Security Standards Enforcement

You enforce the security standards captured in infra-brain (`category: security`) against the
current repo. The first standard set is BWS (Bitwarden Secrets Manager) proper usage.

## Steps

1. **Run the deterministic scanner** against the repo you're in (no install needed — run it off
   the source tree via `PYTHONPATH`):
   `PYTHONPATH="$HOME/Projects/security-standards/src" python3 -m security_scan.cli . --category security`
   (Scan another repo by passing its path instead of `.`. It reads rules live from infra-brain if
   `INFRABRAIN_BASE_URL`/`INFRABRAIN_ACCESS_KEY` are set, else the bundled offline cache — both give
   identical findings. The scanner is read-only and exits non-zero if any BLOCK finding is present.)

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
