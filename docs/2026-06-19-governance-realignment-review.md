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

### [ ] 1. 🔴 FATAL (cheap) — make `make install` reconcile the Check-13 tamper baseline
**Problem:** every legit `make install` mutates `~/.claude/{bin,hooks}` → Check 13 fires "control-plane drift → URGENT" → operator learns to reflex-dismiss it → a *real* tamper looks identical and gets dismissed. The deploy process trains you to ignore the signal tamper-evidence relies on. (The 4am executor has a plan-hash "expected-state" gate; Check 13 has no equivalent.)
**Fix:** make the **last step of `make install` reconcile the control-plane baseline** — auto-commit the deploy diff in the `~/.claude` repo (and/or record the new expected hash, mirroring the existing `self-check.ts` runner-integrity pattern) — so a legitimate deploy is **silent** and only an *out-of-band* change alerts. This also removes the "must remember to commit after install" procedural gap.
**Where:** `security_scan/governance/deploy.py` (make install) + the Check-13/self-check baseline. Possibly a small touch in infraops `src/security-drift/self-check.ts`.
**Leverage:** highest on the board — the difference between real and theatrical tamper-evidence.

### [ ] 2. 🟠 Honesty — "approve" gates the autonomous path, NOT live sessions
**Problem:** the "approve" lane creates the impression that mutations are gated. change-manager gates the **autonomous 4am executor only**. A live interactive Claude session still has un-gated access to ~213 infraops mutation tools (controlled only by `permissions.deny` + the high-power-gate hook + response redaction). The lane name oversells the interactive-session threat model.
**Fix:** state this explicitly in the governance doc / `governance-map.toml` comments — autonomous mutations are *approval-gated*; interactive mutations are *guardrail-gated*. Don't let the model create false confidence. (No code change required — this is a correctness-of-belief fix.)
**Where:** `governance-map.toml` header / the governance stanza copy.

### [ ] 3. 🟠 Scanner↔parser version skew = silent 3am failure
**Problem:** infraops `scan-parser.ts` parses `security-scan.sh`'s output by **implicit contract**. A `make install` that changes the scanner's output format silently breaks the parser at **runtime** — the 3am drift job quietly produces zero findings and nothing tells you.
**Fix:** add a `# SCANNER_OUTPUT_VERSION=N` line to `security-scan.sh` and a matching assertion in infraops `paths.ts` (or the runner) so a mismatch fails loud immediately.
**Where:** `scripts/security-scan.sh` (here) + infraops `src/security-drift/paths.ts` (tail).

### [ ] 4. 🟡 Slim the stanza projection — keep the goal, drop the mechanism
**Problem:** generating a `<!-- governance:start/end -->` section into ~10 repos' CLAUDE.md has no enforcement that stanza == reality (only stanza == TOML). It will drift: a hand-edited stanza, a `make sync` not re-run, a forgotten new repo. Stale generated governance docs have *false authority* and will mislead build-agents. It's enterprise coordination machinery on a solo codebase.
**Important:** the *goal* — agent-legible ownership so a fresh session doesn't re-litigate "where does this live" — is **good** (it's the exact pain that motivated the realignment). Keep the goal; replace the mechanism.
**Fix:**
- One **`~/.claude/OWNERSHIP.md`** (or a section in `~/.claude/CLAUDE.md` — already a universal injection point every session reads): every deployed artifact → source file → owner repo, in one place.
- A **2-line source header in each deployed script/hook:** `# Source: ~/Projects/security-standards/...  • edit there, then: cd ~/Projects/security-standards && make install`. Self-documenting at the exact point of temptation (the 11pm in-place edit).
- Keep `make verify`, but trigger it automatically (e.g. run it at the end of `make install`, or a session-start check) so it doesn't silently stop being run.
- Then retire `make sync` + the per-repo stanza generation.
**Where:** `security_scan/governance/stanza.py`, `governance-map.toml`, the Makefile; plus removing stanzas from consumer CLAUDE.md files.

### [ ] 5. 🟡 Lower priority (note, don't over-build)
- **BWS guard denials bypass the approve ledger:** the blocking guards (`bws-write/read-guard`, `bws-scan-gate`) make deny decisions invisible to change-manager — no "how many blocks this month." If you ever care, pipe denials to the existing `~/.claude/audit/high-power-actions.jsonl`. (Backend-architect: this means the lane model is strictly true only for the security-drift pathway, not BWS enforcement.)
- **No content-verification in the deploy chain:** `make install` + Check 13 detect *that* files changed, not that deployed == reviewed. A compromised security-standards could ship a backdoored hook that reads as "expected deploy drift." Signed commits / artifact-hash would close it — but for a solo operator, GitHub access control is the practical boundary. Note the gap; don't build it yet.

## Reviewer note (where I diverge from the panel)

The security lens called the posture "relocated more than improved." That's slightly too harsh. The fail-open guards and un-gated interactive mutations are **pre-existing** — the realignment didn't worsen them, it just didn't fix them. What it *did* improve: provenance + single patch-propagation for the guards, and agent-legibility of ownership. Fair statement: **it improves the detect lane's auditability + legibility; it doesn't touch the pre-existing runtime gaps; it adds one self-inflicted wound (alert fatigue) that's cheap to remove.** Net: a good move **if** #1 is fixed.

## Bottom line

Right structure, right instinct (you were solving the ownership-ambiguity pain that repeatedly slowed the sessions that built this). Keep the lanes + tamper-evidence. Do **#1** now (real vs theatrical tamper-evidence), be honest about **#2**, add **#3**'s one-liner, slim the projection per **#4**. That turns a good-but-baroque WIP into a lean version that holds.
