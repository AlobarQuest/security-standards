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
foundation_contract: 1
applicable_standards:
  project: '1.0'
  security: '1.0'
  code: '1.0'
required_checks:
- id: quality
  executor: github-actions:quality.yml
- id: security-scan
  executor: github-actions:security-scan.yml
- id: session-scan-gate
  executor: hook:bws-scan-gate.sh
- id: weekly-scan
  executor: launchagent:com.devon.security-scan
- id: factory-events-nightly
  executor: launchagent:com.devon.factory-events
---

## Backlog

- [x] (P1) Restore foundation self-hosting: add a real `make check` target, declare pinned ruff/pyright dev dependencies, remove lint/format/type debt, and retain Python 3.9 compatibility for the deployed read-guard hook. Full gate: ruff + format + pyright (zero errors) + 174 tests. — resolved 2026-07-04

- [ ] (P1) Rotate 5 LIVE creds leaked in ~/.codex logs (2 GitHub classic PATs, 1 GitHub fine-grained PAT, 1 OpenRouter=generic key in BWS 9661da8f+.zshrc, 1 OpenAI project key) — targets+identities in ~/docs/security-audit/2026-07-02-codex-leak-rotation-targets.md; first WS-0.7 rotation cases — added 2026-07-02

- [x] (P2) Scanner manifest consumption modes now model `coolify-env` and generic `environment-injection`; declared UUIDs in those modes are authoritative and no longer misreported as stale merely because runtime code receives environment variables. Adopted by brain and security-standards. — added 2026-07-02; resolved 2026-07-04

- [x] (P2) Scan ~/.codex for live secrets — open follow-up from the 2026-06-14 machine security-audit cutover. Codex's transcript store was never audited (only ~/.claude/projects was); known to have held credential transcript exposure. Run in a separate focused session. — added 2026-06-26
- [x] (P2) make install deploys bws-write-guard.sh into ~/.claude/hooks/ but doesn't give ~/.claude its own .security-scan-allow.toml, so the deployed hook's self-match (bws.bootstrap-token-not-inline, line 33 = the detection regex) BLOCKs whenever ~/.claude is self-scanned by the Stop gate. Fixed ad-hoc 2026-06-26 by hand-creating ~/.claude/.security-scan-allow.toml (gitignored, local-only). Durable fix: have the deploy install/maintain that allowlist. — added 2026-06-26; done 2026-06-28 (deploy/claude-home.security-scan-allow.toml now a governed deployed artifact → ~/.claude/.security-scan-allow.toml via make install)
- [ ] (P2) Build tooling to make Coolify/GitHub deploy-key (and credential) rotations bearable — the enabler Devon wants before clearing deferred key-rotation items. Should make 'rotate a deploy key + swap on Coolify + GitHub + redeploy + verify' a one-command, transcript-safe flow (no reading deploy logs, which leak the key). Unblocks the deferred veritok deploy-key rotation. — added 2026-06-26
- [x] (P2) Onboard to code-standards (foundation matrix red: code.not-onboarded) — added 2026-07-02

- [x] (P2) Scanner resolves the containing git worktree root before enumerating files, loading manifests, or applying `.security-scan-allow.toml`; subdirectory scans now use the root policy consistently. — added 2026-07-03; resolved 2026-07-04
- [ ] (P2) CI guard: STANDARD_VERSION must be bumped when the standard's rules change in a diff (WS-1.3 follow-up) — added 2026-07-03
- [ ] (P3) factory_events store: cached-head/seek-tail optimization — append_event re-reads the whole file per append and adapters full-scan event_ids() per run; O(n²) backfill, fine at ~600 events, hurts at ~1e5 — added 2026-07-10
- [ ] (P3) factory_events CLI error formatting: pagination RuntimeError and DB-unreachable psycopg errors bypass the ADAPT FAIL/VERIFY FAIL stderr formatting (fail-loud already, cosmetic); fold in malformed-response JSONDecodeError catch in change-manager _http_fetch and the resume-after-fix test assertion — added 2026-07-10
- [ ] (P3) Decide single write path for ~/.claude/bin/factory-events-nightly.sh: installer cp duplicates the governance make-install deploy; either drop the cp or register the plist template in governance-map — added 2026-07-10
- [ ] (P3) Nightly healthcheck curl: add --retry 3 to reduce false dead-man alerts on transient blips (factory-events-nightly.sh) — added 2026-07-10
- [ ] (P2) Split the shared BWS machine account into per-workload least-privilege accounts. The three pipeline Keychain tokens (BWS_ACCESS_TOKEN_INFRA_DRIFT, BWS_ACCESS_TOKEN_INFRAOPS, BWS_ACCESS_TOKEN_VPS_BACKUP) all hold the SAME broad machine account (fp da55db37ea81, uuid 8ba33ccd) — found 2026-07-02 (WS-0.7). Give each workload its own scoped machine account (50-token headroom), like the dedicated cred-rotation account in infraops PR #33. Ref: infra-brain lesson #451. — added 2026-07-10
## Future plans
