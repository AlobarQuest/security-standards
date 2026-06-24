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
