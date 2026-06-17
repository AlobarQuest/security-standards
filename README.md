# security-standards

Deterministic + judgment-based enforcement of security standards (v1: BWS secret handling).
Rules live in infra-brain (`category: security`); the scanner evaluates a repo and emits findings
with remediation. Surfaces: a Claude Code skill (`skill/SKILL.md`) and CI (`security-scan`).

## Use
- One-off: `python -m security_scan.cli <repo> --category security`
- CI: see `.github/workflows/security-scan.yml`
- Agent: invoke the `security-standards` skill.

Design: `docs/superpowers/specs/2026-06-12-security-standards-enforcement-design.md`.

## Read-guard (SHELVED — redact-on-read is infeasible on Claude Code)

> **Status: shelved / not wired.** The `security_scan.read_guard` package was built to
> redact a BWS token out of `Read`/`Bash` output via a PostToolUse hook *before it reaches
> the transcript*. Live validation proved this is **impossible on the installed Claude Code**:
> a PostToolUse hook cannot modify or suppress tool output (`updatedToolOutput` /
> `updatedToolResponse` are ignored; `decision:"block"` still delivers the output) — it can
> only annotate. The token enters the transcript the instant a tool returns. The package is
> retained, **inert and unwired**, as a reference (and its pure primitives — `scan_for_bws`,
> `redact`, `token_shapes.BWS_TOKEN_RX` — are reusable). The active read-side protection is
> **prevention-by-absence**: the BWS tokens were migrated out of plaintext files into the
> macOS Keychain, so there is little left on disk to read. To keep a secret out of the
> transcript via hooks you would need a PreToolUse path-deny (coarse, path-based).

Design (now superseded by the feasibility finding): `docs/superpowers/specs/2026-06-17-bws-read-guard-design.md`.
