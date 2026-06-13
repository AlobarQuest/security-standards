# security-standards

Deterministic + judgment-based enforcement of security standards (v1: BWS secret handling).
Rules live in infra-brain (`category: security`); the scanner evaluates a repo and emits findings
with remediation. Surfaces: a Claude Code skill (`skill/SKILL.md`) and CI (`security-scan`).

## Use
- One-off: `python -m security_scan.cli <repo> --category security`
- CI: see `.github/workflows/security-scan.yml`
- Agent: invoke the `security-standards` skill.

Design: `docs/superpowers/specs/2026-06-12-security-standards-enforcement-design.md`.
