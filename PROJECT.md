---
name: security-standards
tier: active
status: active
purpose: 'Deterministic + judgment-based enforcement of security standards (v1: BWS
  secret handling).'
version: 0.1.0
version_source: pyproject
updated: '2026-06-26'
foundation: true
applicable_standards: [project, security, code]
---

## Backlog

- [ ] (P1) Rotate 5 LIVE creds leaked in ~/.codex logs (2 GitHub classic PATs, 1 GitHub fine-grained PAT, 1 OpenRouter=generic key in BWS 9661da8f+.zshrc, 1 OpenAI project key) — targets+identities in ~/docs/security-audit/2026-07-02-codex-leak-rotation-targets.md; first WS-0.7 rotation cases — added 2026-07-02

- [ ] (P2) Scanner: add a manifest consumption-mode (e.g. consumption = "coolify-env") so bws.manifest-matches-usage can model env-injection repos (brain allowlists it today with a revisit trigger) — added 2026-07-02

- [x] (P2) Scan ~/.codex for live secrets — open follow-up from the 2026-06-14 machine security-audit cutover. Codex's transcript store was never audited (only ~/.claude/projects was); known to have held credential transcript exposure. Run in a separate focused session. — added 2026-06-26
- [x] (P2) make install deploys bws-write-guard.sh into ~/.claude/hooks/ but doesn't give ~/.claude its own .security-scan-allow.toml, so the deployed hook's self-match (bws.bootstrap-token-not-inline, line 33 = the detection regex) BLOCKs whenever ~/.claude is self-scanned by the Stop gate. Fixed ad-hoc 2026-06-26 by hand-creating ~/.claude/.security-scan-allow.toml (gitignored, local-only). Durable fix: have the deploy install/maintain that allowlist. — added 2026-06-26; done 2026-06-28 (deploy/claude-home.security-scan-allow.toml now a governed deployed artifact → ~/.claude/.security-scan-allow.toml via make install)
- [ ] (P2) Build tooling to make Coolify/GitHub deploy-key (and credential) rotations bearable — the enabler Devon wants before clearing deferred key-rotation items. Should make 'rotate a deploy key + swap on Coolify + GitHub + redeploy + verify' a one-command, transcript-safe flow (no reading deploy logs, which leak the key). Unblocks the deferred veritok deploy-key rotation. — added 2026-06-26
- [x] (P2) Onboard to code-standards (foundation matrix red: code.not-onboarded) — added 2026-07-02

## Future plans
