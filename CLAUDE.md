# security-standards — Claude context

Deterministic + judgment-based enforcement of security standards (v1: BWS secret
handling). See `README.md` for the scanner/skill/CI surfaces and
`docs/security-environment-overview.md` for the full defense model.

## Deploy reality — why `main` must be current

This repo is the **source of truth for deployed control-plane artifacts**, installed
**from the local checkout** by `make install` (`security_scan.governance deploy`), not by CI:

- `~/.claude/bin/security-scan.sh` — the weekly drift-check runner (also run by the
  `com.devon.security-scan` LaunchAgent).
- The BWS enforcement hooks in `~/.claude/hooks/` (`bws-write-guard.sh`,
  `bws-scan-gate.sh`, `bws-read-guard.sh`).

Because the deploy reads **this working tree**, a stale `main` is dangerous: running
`make install` would push **stale enforcement code** onto the control plane, and
`make verify` would then disagree with `governance-map.toml`. (CI's `security-scan`
workflow only *runs* the scanner; it does not deploy.) Keep `main` current before any
`make install`.

## SessionStart auto-sync hook

`.claude/hooks/session-sync.sh` (wired via `.claude/settings.json`) keeps `main` current
at session start. It fetches and, **only when on `main` + clean + behind origin**,
fast-forwards `main`; in every other state (feature branch, dirty tree, diverged) it just
injects a "run `git sync`" notice. It never switches branches, deletes anything, or blocks
startup. The `git sync` alias and `fetch.prune` are configured globally on this machine.

<!-- code-standards:start -->
# Code Quality (code-standards layer)

Standards reference: `~/Developer/code-standards/STANDARDS.md`

## Before writing a cross-cutting pattern — query Code Brain

Before implementing a recurring cross-cutting concern (logging, error handling,
auth, notifications, API conventions, secrets, …), query **Code Brain** — the
machine source of record for our paved roads — and follow its rules:

- `get_road("<slug>")` → the decided approach + rules + exemplars, or
- `get_rules(severity="BLOCK")` → the must-follow rules.

Do **not** infer the standard from existing code; it may predate the standard.
When you decide a new cross-cutting pattern, write it back (`add_road` / `add_rule`).

## Before declaring a non-trivial change done

1. Run `make check` — full-repo lint, type-check, and tests must be green.
2. Run `/code-review` — review the diff for correctness bugs and simplification opportunities.

Both gates apply to any change that touches logic, interfaces, or configuration.
Trivial fixes (typos, comment edits) may skip `/code-review` at your discretion.

## Enforcement

A diff-scoped Stop hook enforces this automatically: it runs the linters over your
changed files when the session ends and blocks completion if new violations are
introduced. Existing baseline violations are tracked and do not block.

## Canonical example module

The authoritative pattern for this repo's style is:

the cleanest, most idiomatic existing module in this repo

When writing new code, mirror the structure, naming conventions, and documentation
style of that module.

<!-- code-standards:end -->
