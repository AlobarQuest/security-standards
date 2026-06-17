# security-standards

Deterministic + judgment-based enforcement of security standards (v1: BWS secret handling).
Rules live in infra-brain (`category: security`); the scanner evaluates a repo and emits findings
with remediation. Surfaces: a Claude Code skill (`skill/SKILL.md`) and CI (`security-scan`).

## Use
- One-off: `python -m security_scan.cli <repo> --category security`
- CI: see `.github/workflows/security-scan.yml`
- Agent: invoke the `security-standards` skill.

Design: `docs/superpowers/specs/2026-06-12-security-standards-enforcement-design.md`.

## Read-guard (PREVENT — read side)

A PostToolUse hook (`~/.claude/hooks/bws-read-guard.sh`) runs after every `Read` and `Bash` tool call inside a Claude Code session. It pipes the tool output through `security_scan.read_guard`, which redacts any BWS token (canonical shape `0.<uuid>.<secret>`, defined in `security_scan.token_shapes`) before the output reaches the agent context. This closes the exfiltration path where a token written into a tracked file could be read back and surfaced in a transcript.

Detection uses two signals: content-shape matching (the canonical regex) and a path amplifier (if the file path suggests a `.env` or config file, sensitivity is raised). If the guard process itself fails for any reason, it applies an Option-3 fail-safe: pass the output through unchanged rather than blocking the agent, so a hook crash does not halt work.

Design: `docs/superpowers/specs/2026-06-17-bws-read-guard-design.md`.
