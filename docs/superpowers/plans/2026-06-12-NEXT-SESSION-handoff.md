# NEXT SESSION HANDOFF — Build & validate the security-standards tool (v1 BWS)

**Read this first.** It has the full state and the exact order of operations. Everything is
committed; nothing below has been started.

## Order of operations
1. **Build the tool** — execute the implementation plan.
2. **UUID cleanup in infraops** — revert `start.sh` to reference the stable secret UUID, and add a
   correcting infra-brain lesson.
3. **Validate the tool against infraops** (now UUID-based) — real-world dogfood; fix the tool
   and/or `start.sh` as needed using the context here.

---

## Current state (DONE — do not redo)
- **This capability:** `~/Projects/security-standards/` (git repo, ships a secrets-blocking
  `.gitignore`). Commits: design spec, implementation plan, this handoff.
  - **Spec (approved):** `docs/superpowers/specs/2026-06-12-security-standards-enforcement-design.md`
  - **Plan (approved, 11 TDD tasks):** `docs/superpowers/plans/2026-06-12-security-standards-bws-scanner.md`
- **The BWS leak incident is fully closed.** Machine accounts are renamed **Developer Machines**
  (mac mini), **Hetzner VPS**, **Dev Virtual** (OrbStack); the leaked token is revoked; every
  workload runs on a fresh token; the secret store was re-architected into Ops/Apps/Content projects.
- **Memory:** `~/.claude/projects/-Users-devon-Projects-InfraManager/memory/prefer-bws-uuid-over-name.md`
  — reference BWS secrets by **stable UUID**, not the mutable name. (This is *why* Phase 2 exists.)

## Phase 1 — Build the tool (execute the plan)
- **Plan:** `~/Projects/security-standards/docs/superpowers/plans/2026-06-12-security-standards-bws-scanner.md`
- Use **superpowers:subagent-driven-development** (recommended) or **superpowers:executing-plans**.
- It's a dependency-free Python package (`security_scan`) + a Claude Code skill + CI. The plan's
  "Done criteria" are at the bottom. Install for use with `pip install -e ~/Projects/security-standards`.

## Phase 2 — UUID cleanup in `infraops-mcp-server` (queued task)
Earlier today I changed `start.sh` to fetch the infra-brain key **by name** — which violates the
standard we just captured (reference by stable UUID; the name is mutable). Revert it (this was my
*original* approach before I over-corrected).

- **File:** `~/Projects/infraops-mcp-server/start.sh`
- **Current** (the `infra-brain` block):
  ```sh
  export INFRABRAIN_ACCESS_KEY=$(fetch_bws_secret_by_name "INFRABRAIN_ACCESS_KEY")
  ```
- **Change to** (default the stable, non-secret UUID; `fetch_bws_secret` takes a secret ID):
  ```sh
  export INFRABRAIN_ACCESS_KEY=$(fetch_bws_secret "${BWS_INFRABRAIN_SECRET_ID:-45eb083f-4b05-4251-924d-b46700e5a643}")
  ```
  Also update the nearby comment (currently mentions "by name") to reflect "by stable UUID". The
  env var `BWS_INFRABRAIN_SECRET_ID` is not set in the launch env, so the default UUID is what runs
  — which is the point (no fragile env propagation; the UUID is non-secret so it's fine in the
  public repo).
- **Process:** `infraops-mcp-server` default branch is `main` and triggers CI (npm ci + build +
  test). Do this on a **branch → PR → squash-merge** (the pattern used all day).
- **Verify the revert works:** after merge + `git pull`, `/mcp` reconnect **infraops**, then run
  `mcp__infraops__coolify_audit_standards` (scope one app) → expect `standards_source: "live"`
  (proves the by-UUID fetch loads the infra-brain key correctly).
- **Then add a correcting infra-brain lesson** via the Infra_Brain MCP `add_lesson` (tags:
  `bws`, `secrets`): reference BWS secrets by their **stable UUID**, not name — the name is a
  mutable human label that will be renamed and break by-name fetches; the UUID is immutable and
  non-secret, so default/hardcode it in launchers. **This supersedes lesson #273** (which wrongly
  endorsed by-name); say so in the new lesson.

## Phase 3 — Validate the tool against infraops (the real-world test)
With the tool built (Phase 1) and `start.sh` on UUID (Phase 2):

```
python -m security_scan.cli ~/Projects/infraops-mcp-server --category security
```

**Expected findings (this is the pass condition):**
- `bws.reference-by-stable-uuid` → **NO finding** (the by-name fetch is gone). ← validates both the
  revert and the rule.
- `bws.no-token-in-tracked-files` / `bws.no-token-in-git-history` / `bws.bootstrap-token-not-inline`
  → **clean** (infraops has no committed tokens; `start.sh` fetches at runtime).
- `bws.secret-manifest-present` → **FIRES** (infraops has no `.bws-secrets.toml`).
- `bws.manifest-matches-usage` → **FIRES** with undeclared UUIDs — `start.sh` references several
  secret IDs (`BWS_COOLIFY_SECRET_ID`, `BWS_HETZNER_SECRET_ID`, `BWS_CLOUDFLARE_SECRET_ID`,
  `BWS_INFRABRAIN_SECRET_ID` default `45eb083f-…`, etc.).

If the output matches → **the tool works.** To then demonstrate the payoff, create infraops's
`.bws-secrets.toml` declaring each secret UUID it consumes (map `BWS_*_SECRET_ID` defaults + the
infra-brain UUID → name/purpose) and re-run → the manifest findings clear.

**If the tool misbehaves** (false positives/negatives, crash), you have full context to fix it.
Most likely suspects:
- `manifest.referenced_uuids` heuristic — which lines count as "BWS context" (the `_BWS_LINE_RX`).
- `predicates._gitignore_covers` probe synthesis.
- The history scan (`repo.grep_history` via `git log -G`).
And `start.sh` itself — if the by-UUID fetch fails (e.g. the helper signature), fix it here too.

## Key facts / gotchas
- The scanner runs **offline by default** (bundled `rules_cache.json`); it reads live infra-brain
  rules only if `INFRABRAIN_BASE_URL` + `INFRABRAIN_ACCESS_KEY` are set. The **Infra_Brain MCP** is
  available for `add_lesson`.
- Stable infra-brain secret UUID: `45eb083f-4b05-4251-924d-b46700e5a643` (a non-secret identifier).
- **Never commit a token to git** — the tool exists to prevent exactly that; the security-standards
  repo's own `.gitignore` already blocks `*.env`/`*-migration/`/`*.key`/`*.password`.
- The infraops MCP fetches its tokens at launch; after editing `start.sh`, reconnect to test.

## Pointers
- Spec + plan (above). Memory `prefer-bws-uuid-over-name`. Infra-brain lessons **#273** (supersede),
  **#275**. The earlier BWS re-architecture write-up:
  `~/Projects/vps-backup/docs/2026-06-12-bws-rearchitecture.md`.
