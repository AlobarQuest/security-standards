# Handoff → infraops build agent (DEFERRED): assert `SCANNER_OUTPUT_VERSION` to kill silent parser skew

**Date:** 2026-06-19
**Status:** **DEFERRED — do NOT start yet.** Hand this off only *after* prong 2 of item #1 lands
(both touch the deployed scanner; sequence them, don't run concurrently).
**From:** security-standards (detect lane)
**To:** infraops-mcp-server (mutate lane) — owner of `scan-parser.ts`
**Parent:** action item #3 in `docs/2026-06-19-governance-realignment-review.md`. Adjacent to the
prong-2 handoff (`docs/2026-06-19-prong2-selfcheck-runner-integrity-handoff.md`).

---

## TL;DR

infraops `scan-parser.ts` parses `security-scan.sh`'s stdout by an **implicit contract**. If a
`make install` ships a scanner whose output shape changed, the parser silently matches nothing →
the 3am drift job produces **zero findings** and nothing tells you. This makes that contract
**explicit and fail-loud**.

**security-standards half — DONE.** `scripts/security-scan.sh` now carries a machine-readable
marker (a bash comment, *not* emitted to stdout):

```
# SCANNER_OUTPUT_VERSION=1
```

…inside an `OUTPUT CONTRACT` block that documents exactly what version 1 means (see below).

**infraops half — THIS HANDOFF.** Read that marker from the deployed scanner file and assert it
equals the version the parser was written against; on mismatch, **fail loud** (don't parse).

---

## What version 1 means (the contract the parser depends on)

Copied from the `OUTPUT CONTRACT` block now in `scripts/security-scan.sh`:

- One finding per line: `printf '%-4s %-32s %s\n'  SEV  CHECK  detail`
  - `SEV ∈ {FAIL,WARN,PASS}`
  - `CHECK` — dotted key, no spaces (e.g. `credfile.over_permissive`)
  - `detail` — free text; the path-bearing forms `extractTarget()` keys on are
    `"<path> (mode NNN) ..."`, `"<file>: <rest>"`, leading `"<path>"`.
- Non-matching lines (the banner, `=== summary ===`) are ignored.

This is exactly today's `scan-parser.ts` behavior (`LINE` regex + `extractTarget`). So **version 1
== the current parser.** Bump the marker (and the infraops expected constant, same PR) only when
that line shape or a detail form changes.

---

## The infraops task

1. Add an expected-version constant, e.g. in `paths.ts` or `scan-parser.ts`:
   ```ts
   export const EXPECTED_SCANNER_OUTPUT_VERSION = 1;
   ```
2. Before parsing, read the **deployed scanner file** at `p.scanPath`
   (`~/.claude/bin/security-scan.sh`), extract the marker with a regex like
   `/^#\s*SCANNER_OUTPUT_VERSION=(\d+)\s*$/m`, and compare.
3. **Fail loud on skew or absence — but RECONCILE-SAFELY.** Make the version check a **preflight
   gate that runs BEFORE the parse/classify/sync pipeline**, and on skew **do NOT call the normal
   `postSync` path at all**:
   - On skew: send the urgent notification **directly** (the `sendUrgent`/email path) AND **skip
     `runSecurityDrift` / `postSync` entirely**, then exit non-zero. This is both reconcile-safe
     *and* observable.
   - A bare `throw` before `postSync` is also reconcile-safe but loses observability (just a crash
     in the 3am log, no urgent email) — prefer the direct-email-then-abort above.
   - **Do not** silently continue, and **do not** route the skew finding through `extraFindings`
     into `runSecurityDrift` (see the WARNING below — it false-resolves every real open item).

   > ⚠️ **Reconcile-safety hole (corrects an earlier draft of this handoff; found by the infraops
   > agent, 2026-06-19).** `runSecurityDrift` (`runner.ts:91-98`) POSTs the **full** current finding
   > set every run, and change-manager reconcile **resolves anything absent from that sync**. On a
   > real skew, `parseScan` yields empty/garbage → a sync would post only the skew finding → CM
   > would **falsely resolve every real open security item**. Therefore the skew path must short-
   > circuit *before* `postSync`. Injecting the skew via `extraFindings` (the original suggestion
   > here) is unsafe — do not do it.
4. Where to wire it: `src/cli/security-drift-cli.ts` already reads `p.scanPath` and calls
   `captureScan(p.scanPath)`. Do the version read+compare right there, before `runSecurityDrift`;
   on skew, branch to the direct-email-then-exit path instead of calling `runSecurityDrift`.

### Why read the file, not the output
The marker is a comment, so it is intentionally **not** in stdout (keeps the parser input
unchanged — zero risk to the running job from shipping the marker ahead of this assertion). The
infraops side already knows the file path (`p.scanPath`), so reading the file is trivial and
robust.

> Optional alternative (only if you'd rather not read the file): have the scanner *emit*
> `emit PASS scanner.output_version "1"` as a finding line. A `PASS` line is dropped by the runner
> (`parseScan(...).filter(f => f.severity !== "PASS")`), so it would be safe in-stream. This needs
> a one-line change back in `security-scan.sh` — ask security-standards if you want this instead of
> the file-read. The file-comment approach above needs no further security-standards change.

---

## Acceptance criteria

1. With the deployed scanner at `SCANNER_OUTPUT_VERSION=1` and `EXPECTED_…=1`, a run behaves
   exactly as today (no new finding, normal `postSync`).
2. If the deployed marker ≠ expected (or is missing), the run sends an urgent notification and
   **does NOT call `postSync`** (reconcile-safe), and exits non-zero. It must NOT report a normal
   "0 findings" success, and must NOT post a finding set that could false-resolve open items.
3. Unit-tested in the infraops suite: a wrong/absent marker (a) triggers the urgent path and
   (b) asserts `postSync` was **not** called (the reconcile-safety regression guard).

---

## Sequencing & pointers

- **Do prong 2 first**, then this. Both read the deployed scanner; landing them together in one
  infraops pass is fine, but prong 2 is the higher-severity item.
- **DEPLOY STATE (2026-06-19): the marker is in the SOURCE but NOT yet deployed** —
  `~/.claude/bin/security-scan.sh` lacks it (`cmp` differs). This is **intentionally deferred**:
  item #4 will also edit `scripts/security-scan.sh` (a source-provenance header), so the deploy is
  batched — Devon runs a single `make install` after item #4's scanner edit lands (ideally after
  prong 2 stabilizes). Until then, both prong 2's deployed-vs-source check and this marker
  assertion will report the deployed scanner as out-of-date — expected, clears on that deploy.
- security-standards marker lives in `scripts/security-scan.sh` (the `OUTPUT CONTRACT` block).
- governance-map authoritative source path for the scanner: tool `security-scan.sh`
  (`home_repo` security-standards, `source` `scripts/security-scan.sh`,
  `deploy_target` `~/.claude/bin/security-scan.sh`).
- Keep this a code-edit session for infraops, distinct from any live-infra mutation.
