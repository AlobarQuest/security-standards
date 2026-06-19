# Governance realignment — architecture review + action backlog

**Date:** 2026-06-19
**Subject:** the 3-lane governance model (security-standards DETECTS · infraops MUTATES · change-manager APPROVES), `governance-map.toml` + `make sync/install/verify`, and the `~/.claude` control-plane tamper-evidence repo.
**Method:** 3 independent review lenses (backend-architect = boundaries/coupling, security-auditor = posture, maintainability = governance-as-code rot) + synthesis. WIP review — Devon will address items in this repo.

## Headline

The **repo split (detect/mutate/approve) is sound and worth keeping.** The **`governance-map → make sync → CLAUDE.md stanza` projection is the over-built part.** There is **one fatal-but-cheap-to-fix wound** (alert fatigue). All three lenses independently reached the first two conclusions — strong signal.

## Keep (validated)

- The 3-repo lane separation — real separation-of-duties: a prompt-injected session can produce a *finding*, not directly trigger an action. Right structure for the threat model.
- `~/.claude` as a tamper-evidence git repo — cheapest possible "did something change?" mechanism.
- Source-scoped `/api/sync` reconcile; plan-hash gate on the 4am executor; `SECURITY_SCAN_PATH` testing seam.

## Action backlog (priority order)

### [x] 1. 🔴 FATAL (cheap) — make `make install` reconcile the Check-13 tamper baseline
**Status (2026-06-19):** Prong 1 DONE — `make install` now auto-commits the deployed control-plane
hooks into the `~/.claude` repo (`deploy.py:reconcile_control_plane`), so a legit deploy is silent to
Check 13 and out-of-band edits still alert. Verified end-to-end (Check 13 `controlplane.clean`,
idempotent no-op on unchanged deploy, commits only the exact deployed paths). Prong 2 (the bin/
scanner's `selfcheck.runner_integrity`, which is infraops-owned and self-healing/one-shot) is handed
off in `docs/2026-06-19-prong2-selfcheck-runner-integrity-handoff.md`.
**Prong 2 update (2026-06-19): MERGED on infraops main (`6ec32a7`)** — implemented as source-verified
runner integrity (deployed scanner compared to its blessed source). Activates on the next batched
`make install` deploy. Item #1 fully closed once that deploy lands.
**Problem:** every legit `make install` mutates `~/.claude/{bin,hooks}` → Check 13 fires "control-plane drift → URGENT" → operator learns to reflex-dismiss it → a *real* tamper looks identical and gets dismissed. The deploy process trains you to ignore the signal tamper-evidence relies on. (The 4am executor has a plan-hash "expected-state" gate; Check 13 has no equivalent.)
**Fix:** make the **last step of `make install` reconcile the control-plane baseline** — auto-commit the deploy diff in the `~/.claude` repo (and/or record the new expected hash, mirroring the existing `self-check.ts` runner-integrity pattern) — so a legitimate deploy is **silent** and only an *out-of-band* change alerts. This also removes the "must remember to commit after install" procedural gap.
**Where:** `security_scan/governance/deploy.py` (make install) + the Check-13/self-check baseline. Possibly a small touch in infraops `src/security-drift/self-check.ts`.
**Leverage:** highest on the board — the difference between real and theatrical tamper-evidence.

### [x] 2. 🟠 Honesty — "approve" gates the autonomous path, NOT live sessions
**Status (2026-06-19):** DONE. The honest gating model is now stated at the source of truth
(`governance-map.toml` header: autonomous = approval-gated; interactive = guardrail-gated via
`permissions.deny` + high-power-gate hook + audit log) and projected into every tool-home stanza
(`stanza.py` "**Gating scope:**" line). `make sync` regenerated the 3 tool-home stanzas;
`make verify` green. (infraops + change-manager CLAUDE.md now have uncommitted stanza updates.)
**Problem:** the "approve" lane creates the impression that mutations are gated. change-manager gates the **autonomous 4am executor only**. A live interactive Claude session still has un-gated access to ~213 infraops mutation tools (controlled only by `permissions.deny` + the high-power-gate hook + response redaction). The lane name oversells the interactive-session threat model.
**Fix:** state this explicitly in the governance doc / `governance-map.toml` comments — autonomous mutations are *approval-gated*; interactive mutations are *guardrail-gated*. Don't let the model create false confidence. (No code change required — this is a correctness-of-belief fix.)
**Where:** `governance-map.toml` header / the governance stanza copy.

### [x] 3. 🟠 Scanner↔parser version skew = silent 3am failure
**Status (2026-06-19):** PARTIAL. security-standards half DONE — `scripts/security-scan.sh` now
carries a machine-readable `# SCANNER_OUTPUT_VERSION=1` marker inside a documented `OUTPUT CONTRACT`
block (a bash comment; not emitted to stdout, so it's inert until read — verified scanner output
unchanged). The fail-loud assertion is the infraops half and is captured as a **deferred** handoff
in `docs/2026-06-19-item3-scanner-output-version-infraops-handoff.md` (do AFTER prong 2 of #1 —
both read the deployed scanner). Item #3 is not protective until that assertion ships.
**Update (2026-06-19): infraops assertion MERGED on infraops main (`4d99951`)** — a CLI preflight gate
reads the deployed scanner's `SCANNER_OUTPUT_VERSION`; on mismatch/absence it sends URGENT and exits
**before** `postSync` (reconcile-safe — a handoff-stage fix prevented a false-resolve of open items).
Both halves merged AND the marker is now deployed (the 2026-06-19 batched `make install`), so the
assertion is **live and protective** — a future scanner-format change without a version bump fails
loud (reconcile-safely) instead of silently parsing zero at 3am.
**Problem:** infraops `scan-parser.ts` parses `security-scan.sh`'s output by **implicit contract**. A `make install` that changes the scanner's output format silently breaks the parser at **runtime** — the 3am drift job quietly produces zero findings and nothing tells you.
**Fix:** add a `# SCANNER_OUTPUT_VERSION=N` line to `security-scan.sh` and a matching assertion in infraops `paths.ts` (or the runner) so a mismatch fails loud immediately.
**Where:** `scripts/security-scan.sh` (here) + infraops `src/security-drift/paths.ts` (tail).

### [x] 4. 🟡 Slim the stanza projection — keep the goal, drop the mechanism
**Status (2026-06-19):** CODE COMPLETE + merge-ready on branch `feat/governance-slim-stanza`
(6 tasks, subagent-driven, each reviewed; final opus whole-branch review = ready-to-merge-with-fixes,
fixes applied; 105 tests green). Per-repo stanzas retired → generated `~/.claude/OWNERSHIP.md`
(`ownership.py:render/write/verify_ownership`) + `# Source of truth:` headers on the 5 deployed
artifacts (verified by `make verify`); `make sync` removed; CLI gains `ownership` + `strip-stanzas`;
`make install` now ends with `verify`. The honest-gating language (item #2) migrated into OWNERSHIP.md.
**Task 7 migration DONE (2026-06-19):** `make install` deployed the marker + source headers (prong-1
auto-committed the hooks in `~/.claude`) and generated `~/.claude/OWNERSHIP.md`; an OWNERSHIP ref was
added to `~/.claude/CLAUDE.md`; `make strip-stanzas` cleaned all 10 repos (4 retained-content stanza
removals committed; 6 stanza-only `CLAUDE.md` deleted — ownership now lives only in the global
OWNERSHIP.md). This same deploy **closed the item-#1-prong-2 / item-#3 skew window** (deployed scanner
now carries the marker). Verified: `make verify` in sync; Check 13 `controlplane.clean`; Check 14
`governance.artifacts_in_sync`. Spec:
`docs/superpowers/specs/2026-06-19-slim-stanza-projection-design.md`.
Plan: docs/superpowers/plans/2026-06-19-slim-stanza-projection.md
**Problem:** generating a `<!-- governance:start/end -->` section into ~10 repos' CLAUDE.md has no enforcement that stanza == reality (only stanza == TOML). It will drift: a hand-edited stanza, a `make sync` not re-run, a forgotten new repo. Stale generated governance docs have *false authority* and will mislead build-agents. It's enterprise coordination machinery on a solo codebase.
**Important:** the *goal* — agent-legible ownership so a fresh session doesn't re-litigate "where does this live" — is **good** (it's the exact pain that motivated the realignment). Keep the goal; replace the mechanism.
**Fix:**
- One **`~/.claude/OWNERSHIP.md`** (or a section in `~/.claude/CLAUDE.md` — already a universal injection point every session reads): every deployed artifact → source file → owner repo, in one place.
- A **2-line source header in each deployed script/hook:** `# Source: ~/Projects/security-standards/...  • edit there, then: cd ~/Projects/security-standards && make install`. Self-documenting at the exact point of temptation (the 11pm in-place edit).
- Keep `make verify`, but trigger it automatically (e.g. run it at the end of `make install`, or a session-start check) so it doesn't silently stop being run.
- Then retire `make sync` + the per-repo stanza generation.
**Where:** `security_scan/governance/stanza.py`, `governance-map.toml`, the Makefile; plus removing stanzas from consumer CLAUDE.md files.

### [x] 5. 🟡 Lower priority (note, don't over-build)
**Status (2026-06-19):** DONE as a decision record — both gaps captured as *accepted risks* (with
rationale + revisit-triggers) in `docs/decisions/0001-accepted-governance-gaps.md`. No code built
(by design). Verified live: the BWS guards write no denial log (gap 1 holds); item #4 + prong 2
narrowed gap 2 to "source == reviewed" (GitHub access control is the accepted boundary).
- **BWS guard denials bypass the approve ledger:** the blocking guards (`bws-write/read-guard`, `bws-scan-gate`) make deny decisions invisible to change-manager — no "how many blocks this month." If you ever care, pipe denials to the existing `~/.claude/audit/high-power-actions.jsonl`. (Backend-architect: this means the lane model is strictly true only for the security-drift pathway, not BWS enforcement.)
- **No content-verification in the deploy chain:** `make install` + Check 13 detect *that* files changed, not that deployed == reviewed. A compromised security-standards could ship a backdoored hook that reads as "expected deploy drift." Signed commits / artifact-hash would close it — but for a solo operator, GitHub access control is the practical boundary. Note the gap; don't build it yet.

## Reviewer note (where I diverge from the panel)

The security lens called the posture "relocated more than improved." That's slightly too harsh. The fail-open guards and un-gated interactive mutations are **pre-existing** — the realignment didn't worsen them, it just didn't fix them. What it *did* improve: provenance + single patch-propagation for the guards, and agent-legibility of ownership. Fair statement: **it improves the detect lane's auditability + legibility; it doesn't touch the pre-existing runtime gaps; it adds one self-inflicted wound (alert fatigue) that's cheap to remove.** Net: a good move **if** #1 is fixed.

## Bottom line

Right structure, right instinct (you were solving the ownership-ambiguity pain that repeatedly slowed the sessions that built this). Keep the lanes + tamper-evidence. Do **#1** now (real vs theatrical tamper-evidence), be honest about **#2**, add **#3**'s one-liner, slim the projection per **#4**. That turns a good-but-baroque WIP into a lean version that holds.
