# ADR 0001 — Accepted gaps in the 3-lane governance model

**Date:** 2026-06-19
**Status:** Accepted
**Closes:** item #5 of `docs/2026-06-19-governance-realignment-review.md` ("Lower priority — note, don't over-build").

## Context

The governance realignment — **security-standards DETECTS · infraops-mcp-server MUTATES ·
change-manager APPROVES** — was reviewed on 2026-06-19. Two real gaps surfaced that are
**deliberately not worth a fix at solo-operator scale.** This ADR records them as *accepted risks*
so a future session neither (a) rediscovers them as if novel, nor (b) over-builds a fix without
first re-opening this decision. Both were verified against the live code when this ADR was written.

## Gap 1 — BWS guard denials are invisible to the approve ledger

**What:** The BWS enforcement guards (`bws-write-guard`, `bws-read-guard`, `bws-scan-gate`) block at
the moment of action (PreToolUse / Stop). Verified 2026-06-19: none of the three write a denial or
audit record anywhere. So change-manager (the approve lane) has no visibility into them — there is
no "N blocks this month" metric.

**Implication (scope clarification):** the 3-lane model is strictly accurate only for the
**security-drift pathway** (detect → approve → mutate). BWS enforcement is *prevention* (block-at-
write-time), not approval-gated mutation, so it sits **outside** the lane model by design. The lanes
do not claim to cover it; this ADR just makes that explicit.

**Why accepted:** a denial ledger buys observability/metrics, not enforcement — the block has
already happened. Low value for a solo operator.

**Revisit if:** you want block-frequency metrics, or BWS-block frequency becomes a signal worth
trending. Cheapest path then: pipe denials to the **existing** `~/.claude/audit/high-power-actions.jsonl`
(append to the audit log already in place — do **not** build a new store).

## Gap 2 — the deploy chain verifies faithfulness, not trustedness

**What (as of this ADR — note item #4 + prong 2 have *narrowed* the original review wording):**
`make install` + Check 13 detect *that* control-plane files changed. Item #4 added `# Source of
truth:` headers and item-#1 prong 2 added a deployed-vs-source byte check — so the chain now
verifies **deployed == source-of-truth**. What it still does **not** verify is
**source == reviewed/trusted**: a compromised `security-standards` repo (e.g. a backdoored hook
committed to it) would deploy cleanly and pass every check, reading as "expected deploy drift."

**Why accepted:** for a solo operator, **GitHub access control** (only the operator can push to
`security-standards`) is the practical trust boundary. Signed commits / artifact-hash provenance is
enterprise machinery whose cost is not justified at this scale.

**Revisit if:** `security-standards` gains other committers, or the threat model expands to a
compromised GitHub account / supply-chain attacker. Then: verify signed commits on deploy, or gate
deploys on a reviewed-artifact-hash allowlist.

## Consequences

- These are **documented, accepted risks — not backlog items.** Do not implement a fix (denial
  ledger, signed commits, artifact-hash) without re-opening this ADR.
- The lane model's scope is now explicit: it governs the **security-drift mutation pathway**;
  **BWS prevention** and **source-trust** are out of its scope by design.
