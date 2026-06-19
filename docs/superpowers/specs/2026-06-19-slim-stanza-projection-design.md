# Spec — Slim the governance projection (retire per-repo stanzas → ownership map + source headers)

**Date:** 2026-06-19
**Parent:** action item #4 in `docs/2026-06-19-governance-realignment-review.md`.
**Status:** design approved; ready for implementation plan.

## Problem

`make sync` projects a `<!-- governance:start/end -->` stanza into ~10 repos' `CLAUDE.md`. Nothing
enforces that a stanza matches *reality* — only that it matches `governance-map.toml`. So the
stanzas drift (hand-edited block, a `make sync` not re-run, a forgotten new repo) and stale
generated governance docs carry **false authority** that misleads build-agents. It is enterprise
coordination machinery on a solo codebase.

The *goal* the stanzas served is good and must be kept: **agent-legible ownership** so a fresh
session doesn't re-litigate "where does this live." Keep the goal; replace the mechanism.

## Goal / non-goals

**Goal:** one place that answers "where does this artifact live / who owns it," plus
self-documenting provenance at the point of temptation (the in-place edit), with verification that
runs automatically — without per-repo generated blocks that can silently rot.

**Non-goals:** content-verification of deployed bytes (item #5); changing the lane split; touching
`.bws-secrets.toml` BWS manifests (separate mechanism, retained); any infraops change (prong 2 /
item #3 are handled separately).

## Design

`governance-map.toml` remains the single source of truth. The generation **engine** (loader +
generator module) stays; its **projection target** changes from "a stanza in every repo's
`CLAUDE.md`" to "one ownership map + source headers." This removes the 10-block drift surface.

### Component 1 — Ownership map: `~/.claude/OWNERSHIP.md`

- Generated from `governance-map.toml`. A clearly-marked "generated — do not hand-edit" file.
- **Contents:**
  - A table: *deployed artifact → source file (home_repo + source) → deploy_target → lane*.
  - The lane model + the **honest-gating note** migrated from the item-#2 stanzas
    (autonomous = approval-gated; interactive = guardrail-gated via `permissions.deny` +
    high-power-gate hook + audit log).
  - A one-line consumer-governance summary (consumers governed by security-standards; enforcement
    automatic via the global hooks; audit via the `security-standards` skill).
- **Home:** lives at the universal injection point (`~/.claude`) so a session in *any* repo can
  find it. Referenced by a single added line in `~/.claude/CLAUDE.md`.
- **Tamper-tracking:** OWNERSHIP.md is **gitignored** in the `~/.claude` repo (deny-by-default
  `.gitignore` does not un-ignore it). Deliberate trade-off: it is regenerable from
  `governance-map.toml` and **non-enforcing** (informational), so it is not worth tamper-tracking
  and not worth coupling to prong 1's auto-commit. Regenerated on every `make install`.
- **Idempotent write:** rewrite only when content changes (mirror the existing `sync_stanza`
  "unchanged/written" return contract).

### Component 2 — Source headers (anti-temptation provenance)

Each **deployed** artifact's *source* file (the 5 `artifact_class = "deployed"` tools in
`governance-map.toml`) carries a 2-line header immediately after its shebang/description block:

```
# Source of truth: ~/Projects/security-standards/<source> (deployed → <deploy_target>)
# Edit here, not in place; then: cd ~/Projects/security-standards && make install
```

- It propagates to the deployed copy via the normal `shutil.copyfile` deploy, so opening
  `~/.claude/hooks/bws-write-guard.sh` shows the instruction at the point of temptation.
- **Static text, guarded by `make verify`** — NOT auto-rewritten (YAGNI). `verify` asserts each
  deployed artifact's source carries a well-formed `# Source of truth:` line naming the correct
  `source` path. Missing/wrong → verify fails. (If a path ever changes — rare — the dev updates the
  header; verify enforces consistency.)
- The 5 sources: `scripts/security-scan.sh`, `scripts/skills-security-scan.sh`,
  `hooks/bws-write-guard.sh`, `hooks/bws-read-guard.sh`, `hooks/bws-scan-gate.sh`.
- `security-scan.sh` already has an `OUTPUT CONTRACT` block (item #3); the header is additive and
  placed consistently with the others.

### Component 3 — Code changes (`src/security_scan/governance/`)

Rename `stanza.py` → `ownership.py`. Remove the per-repo stanza projection; add the ownership map,
header verification, and the migration stripper.

- **Remove:** `render_stanza`, `block`, `sync_stanza`, `verify_stanza`, `_HEADER`.
- **Keep:** `START` / `END` constants (reused only by `strip_stanza` to find+remove old blocks);
  `ensure_bws_manifest` + `_BWS_SKELETON` (BWS manifests are a separate, retained mechanism);
  `_claude_md(repo)` helper.
- **Add:**
  - `render_ownership(manifest) -> str` — the OWNERSHIP.md body.
  - `write_ownership(manifest, path) -> "unchanged" | "written"` — idempotent.
  - `verify_ownership(manifest, path) -> "ok" | "drift" | "missing"`.
  - `verify_headers(manifest) -> list[(tool_name, "missing"|"wrong")]` — checks each deployed
    source file for the correct `# Source of truth:` line.
  - `strip_stanza(repo) -> "stripped" | "absent" | "missing"` — remove the
    `START..END` block (and its generated `## Security & Governance` header) from a repo's
    `CLAUDE.md`, preserving surrounding text; idempotent.

`__main__.py` commands:
- Drop `sync`.
- Keep `deploy` (now also regenerates OWNERSHIP.md as a final step) and `verify`.
- `verify` scope becomes: deployed artifacts in sync (existing `verify_artifacts`) **+**
  `verify_headers` **+** `verify_ownership`. Drop stanza verify.
- `--artifacts-only` is **redefined** to mean "deployed-faithfulness only" = `verify_artifacts` +
  `verify_headers` (everything about whether the deployed set faithfully matches source), while
  **excluding** `verify_ownership` (the repo-local, non-enforcing OWNERSHIP.md freshness check).
  This keeps the scanner's Check 14 invocation byte-identical (it already calls
  `verify --artifacts-only`) — no second edit to `security-scan.sh`'s Check-14 line, only the
  broadened meaning. Full `verify` (end of `make install`) includes ownership freshness too.
- Add `ownership` (regenerate `~/.claude/OWNERSHIP.md`; `--path` overridable for tests).
- Add `strip-stanzas` (iterate manifest repos, `strip_stanza` each; one-shot idempotent migration).

### Component 4 — Makefile

- `install`: deploy artifacts → `reconcile_control_plane` (prong 1) → regenerate OWNERSHIP.md →
  **run `verify`** as the last step (end-of-install self-check). A verify failure makes
  `make install` exit non-zero.
- `verify`: artifacts + headers + OWNERSHIP.md freshness.
- Remove `sync`. Add `ownership` and `strip-stanzas` targets (with `## help` comments matching the
  existing style).

### Component 5 — Scheduled-path coverage (Check 14)

Check 14 in `scripts/security-scan.sh` runs `governance verify --artifacts-only`. Because
`--artifacts-only` is redefined (Component 3) to mean artifacts **+** source headers, the scheduled
scan automatically gains header-drift coverage **with no change to the Check-14 invocation line** —
only the broadened meaning of the flag. It deliberately does NOT check OWNERSHIP.md freshness (a
repo-local, non-enforcing concern caught at `make install` / full `make verify`). Behavior stays
read-only and surfaces a `governance.*` FAIL on drift, exactly as today.

## Migration (one-time, ordered)

1. Add the 2-line source headers to the 5 source files.
2. Implement code + Makefile + tests; `make install` regenerates `~/.claude/OWNERSHIP.md`.
3. Add the one-line OWNERSHIP.md reference to `~/.claude/CLAUDE.md`; commit it in the `~/.claude`
   repo (CLAUDE.md is in Check 13's critical set, so this hand-edit must be committed to stay clean
   — prong 1 only auto-commits deployed *artifacts*, not CLAUDE.md).
4. Run `make strip-stanzas` to remove the generated blocks from all 10 repos
   (3 tool-home: security-standards, infraops-mcp-server, change-manager; 7 consumers: Contacts,
   FacelessTT, imap-mcp-server, InfraManager, rental-investment-calculator, VideoCreator,
   vps-backup). This **reverts the item-#2 stanza sync**; the gating language is preserved in
   OWNERSHIP.md. Cross-repo writes are reversible per-repo via git.
5. `make verify` green; full pytest green.

## Testing

Rewrite `tests/test_governance_stanza.py` → `tests/test_governance_ownership.py`:
- `render_ownership` includes every deployed artifact, its source, owner repo, lane, and the
  honest-gating note.
- `write_ownership` idempotency (`written` then `unchanged`); `verify_ownership` detects `missing`
  + `drift`.
- `verify_headers` passes when a source carries the correct line; flags `missing`/`wrong`.
- `strip_stanza` removes a `START..END` block, preserves surrounding text, idempotent (`absent` on
  second run); `missing` when no CLAUDE.md.
- CLI: `deploy` regenerates ownership; `verify` fails on a tampered header or stale ownership;
  `strip-stanzas` over a temp repo.
- Update `test_governance_deploy.py` only if the `deploy` command output lines change.

## Risks / coordination

- **Prong 2 in flight (infraops):** keep `governance-map.toml` `[[tool]]`/`[[repo]]` entries
  byte-stable; `security-scan.sh` gains a 2-line header (additive — flag to the prong-2 dev).
- **Deploy is batched + deferred.** The item-#3 marker is already in `security-scan.sh`'s source
  but NOT deployed (`~/.claude/bin/security-scan.sh` differs). Item #4 adds the source header to the
  same file, so do NOT `make install` mid-implementation — the implementation may run `make install`
  in a sandbox/test sense, but the **real control-plane deploy of the updated scanner is a single
  deliberate `make install` Devon runs after item #4's scanner edit lands (ideally post-prong-2).**
  Plan tasks must not assume the new scanner is live until that deploy. (The end-of-install `verify`
  added by this item still runs whenever `make install` is invoked.)
- **Cross-repo writes:** `strip-stanzas` edits 9 other repos' `CLAUDE.md` (same pattern approved
  for `make sync` in item #2); each reversible via git.
- **OWNERSHIP.md not tamper-tracked** (gitignored, regenerable) — accepted, documented above.
- **Item #5** (deny-ledger / content-verification) is explicitly out of scope.
