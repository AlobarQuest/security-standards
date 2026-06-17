# security-standards

Deterministic + judgment-based enforcement of security standards (v1: BWS secret handling).
Rules live in infra-brain (`category: security`); the scanner evaluates a repo and emits findings
with remediation. Surfaces: a Claude Code skill (`skill/SKILL.md`) and CI (`security-scan`).

## Use
- One-off: `python -m security_scan.cli <repo> --category security`
- CI: see `.github/workflows/security-scan.yml`
- Agent: invoke the `security-standards` skill.

Design: `docs/superpowers/specs/2026-06-12-security-standards-enforcement-design.md`.

## Read-guard (PreToolUse content-peek + deny)

**Status: shipped.** A **PreToolUse** hook on the `Read` tool intercepts every file-read
before the tool executes. It opens the target file itself, content-scans the bytes for a BWS
token (canonical shape `0.<uuid>.<secret>`, defined in `security_scan.token_shapes`), and
**denies** the read with a Keychain/BWS redirect message when a token is present — so the
token never enters the transcript.

**Fail-open by design:** any uncertainty (file missing, unreadable, oversized > 256 KB,
binary/undecodable, or any exception) results in `allow`. The guard blocks only confirmed
content matches; it never blocks a legitimate read.

**Scope (v1):** `Read` tool only. `Bash` is out of scope — its output is not knowable
pre-run, and the accidental vector is overwhelmingly the `Read` tool.

**Wired via:** `~/.claude/hooks/bws-read-guard.sh` → `security_scan.read_guard.hook`
(PreToolUse, `Read` tool entry in `~/.claude/settings.json`).

Design: `docs/superpowers/specs/2026-06-17-bws-read-guard-pretooluse-design.md`.
