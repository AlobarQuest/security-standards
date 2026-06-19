# Handoff → infraops build agent: silence `selfcheck.runner_integrity` on a legit scanner deploy

> ✅ **DONE — MERGED on infraops main (`6ec32a7`), 2026-06-19.** Implemented as source-verified runner
> integrity (deployed scanner compared to its blessed source). Activates on the next batched
> `make install`. This handoff is retained for the record.

**Date:** 2026-06-19
**From:** security-standards (detect lane)
**To:** infraops-mcp-server (mutate lane) — owner of the security-drift self-check
**Parent:** action item #1 ("make `make install` reconcile the Check-13 tamper baseline") in
`docs/2026-06-19-governance-realignment-review.md`. This is **prong 2** of that item.

---

## TL;DR

Prong 1 (done in security-standards) makes a legit `make install` **silent to Check 13**
(`controlplane.drift`) by auto-committing the deployed *hooks* into the `~/.claude` git repo.

Prong 2 (this handoff, **infraops-owned**) is the remaining self-inflicted alert: `make install`
also redeploys `~/.claude/bin/security-scan.sh`, which the security-drift **self-check** hashes
for tamper-evidence. A legit scanner deploy therefore raises a one-shot
`selfcheck.runner_integrity` URGENT. We want a legit deploy to be **silent** while an
**out-of-band** edit to the deployed scanner still alerts.

---

## Why this exists (the exact mechanism)

`make install` in security-standards deploys, among other things:

| Deployed artifact | Lands in | Tracked by |
|---|---|---|
| `bws-{write,read,scan}-guard/gate.sh` | `~/.claude/hooks/` (tracked in `~/.claude` git) | **Check 13** → handled by prong 1 |
| `security-scan.sh`, `skills-security-scan.sh` | `~/.claude/bin/` (**gitignored** in `~/.claude`) | **self-check integrity hash** → THIS handoff |

`~/.claude/bin/` is gitignored (`~/.claude/.gitignore` un-ignores `/hooks/` but **not** `/bin/`),
so the bin scanner never trips Check 13. Instead it trips the self-check's **runner-integrity**
check, which is a deliberately *separate trust root* ("the fixer protecting itself" — it does not
trust the `~/.claude` git repo; it keeps its own 0600 hash store).

Reference (infraops source, read at handoff time):

- `src/cli/security-drift-cli.ts:64-71` wires the self-check:
  ```ts
  const selfCheckFindings = runSelfCheck({
    stateFiles: [p.baselineFile, p.emitStateFile, p.rollbackLog],
    auditLog: p.auditLog,
    hwmFile: p.hwmFile,
    integrityFiles: [p.scanPath, p.autoFixAllowlistFile, p.fpAllowlistFile], // ← p.scanPath = ~/.claude/bin/security-scan.sh
    hashFile: p.hashFile,
    now,
  });
  ```
- `src/security-drift/self-check.ts:79-95` (check #3) — records a sha256 per `integrityFiles`
  entry in `hashFile`; on a changed hash it emits
  `fail("selfcheck.runner_integrity", file, "...hash changed since last run — verify this change was intentional")`,
  then **rewrites the recorded hash every run** (`next[file] = h; writeJson(hashFile, next)`).
- `src/security-drift/taxonomy.ts` — `selfcheck.runner_integrity` is in `URGENT_KEYS` → tier URGENT.
- `src/security-drift/paths.ts:31` — `scanPath = process.env.SECURITY_SCAN_PATH ?? ~/.claude/bin/security-scan.sh`;
  `hashFile = <stateDir>/security-runner-hashes.json` (line 39, 0600).

**Severity / behavior:** because the self-check self-heals (records the new hash each run), this
fires **once** per scanner deploy then clears on the next run. It is *less* severe than prong 1's
`controlplane.drift` (which stays FAIL on every scan until someone commits). But it still trains
the operator to dismiss a control-plane URGENT, which is exactly the alert-fatigue the review
calls fatal. Goal: zero alerts on a legit deploy.

---

## The requirement (acceptance criteria)

1. **A legit deploy is silent.** After security-standards `make install` updates
   `~/.claude/bin/security-scan.sh` to the blessed source-of-truth, the next security-drift run
   produces **no** `selfcheck.runner_integrity` finding for that file.
2. **An out-of-band change still alerts.** If `~/.claude/bin/security-scan.sh` is edited to
   content that is **not** the blessed source-of-truth, the next run **does** emit
   `selfcheck.runner_integrity` URGENT.
3. **The other `integrityFiles` are unaffected** (`security-autofix-allowlist.txt`,
   `security-fp-allowlist.txt` in `~/.config/infra-drift/`) — they have no source-of-truth repo
   and must keep their current "changed since last run → verify" semantics, OR get an explicit
   reconcile path of their own. Don't silently weaken them.
4. **Fail loud, not open.** Whatever the mechanism, an unreadable/missing reconcile signal must
   NOT silently suppress the finding (deny-by-default — same posture as the rest of the taxonomy).
5. Unit-tested in the infraops suite (the self-check is already unit-tested — extend it).

---

## Design options (infraops's call — recommendation below)

### Option A — infraops provides a reconcile command; `make install` calls it
infraops adds a tiny subcommand (e.g. `security-drift-cli reconcile-integrity`) that recomputes
and writes the recorded hashes for `integrityFiles`. security-standards' `make install` invokes it
as its last step **iff present**.
- **Pro:** the `hashFile` format stays private to infraops (the owner reads *and* writes it);
  security-standards never touches infraops state directly.
- **Con:** needs a small security-standards-side change to call it (a follow-up in this repo —
  flag it back and we'll add it), and `make install` must locate the infraops `dist/`.

### Option B — deploy receipt (published contract file)
`make install` writes a 0600 receipt (e.g. `~/.config/infra-drift/expected-runner-hashes.json`
= `{ "<scanPath>": "<sha256>", ts, source }`); the self-check treats a hash change as **expected**
(no finding, record new hash) when the new hash matches the receipt.
- **Pro:** decoupled via an explicit, documented contract — directly addresses review #3's
  "no implicit cross-repo contracts" concern.
- **Con:** defines a new file contract on both sides; the receipt is itself a 0600 attacker target
  (same threat model as the hash store — acceptable, but note it).

### Option C — compare deployed scanner to its source-of-truth (PURE infraops, no security-standards change) ⭐ recommended
Change the scanner's runner-integrity semantics from *"changed since last run"* to
*"deployed `~/.claude/bin/security-scan.sh` byte-matches its blessed source"*. The blessed source
is `~/Projects/security-standards/scripts/security-scan.sh` (authoritative path:
`governance-map.toml` → tool `security-scan.sh` → `home_repo` security-standards `+ source`).
- Silent exactly when `deployed == source` (the steady state right after `make install`).
- Emits URGENT when `deployed != source` — which is a *strictly more meaningful* signal than the
  current time-based one: "the deployed scanner is not the blessed artifact" (whether tampered or
  stale-and-never-redeployed).
- **Pro:** entirely within infraops — **the infraops agent can ship this with no security-standards
  change and no new cross-process contract.** No reconcile step to forget.
- **Con:** couples the self-check to the security-standards repo path (resolve via governance-map or
  an env override, fail-loud if unresolvable). Applies to the *scanner* entry only; the two
  allowlist `integrityFiles` keep the "changed since last run" model (they have no source repo) —
  so this becomes a per-file policy, which is fine but should be coded clearly.

**Recommendation: Option C** — it removes the alert at the source (no reconcile handshake to keep
in sync, nothing for `make install` to remember), it's pure-infraops so you can do it independently
while security-standards proceeds with the other backlog items, and it upgrades the check's meaning.
If you prefer to keep the trust root fully self-contained (no dependency on the security-standards
working tree), Option B is the next-best and pairs naturally with review item #3.

---

## Adjacency: do this alongside review item #3

Review item #3 ("scanner↔parser version skew = silent 3am failure") touches the **same
infraops↔security-standards seam** (`security-scan.sh` output ↔ infraops `scan-parser.ts`).
Both prong 2 and #3 are about making the contract across that boundary **explicit and fail-loud**.
Consider designing them together:
- #3 adds a `# SCANNER_OUTPUT_VERSION=N` line to `security-scan.sh` + an assertion in infraops.
- Option C here resolves the scanner's source path the same way you'd resolve it for #3.

---

## Pointers / state at handoff

- **Prong 1 (done):** `src/security_scan/governance/deploy.py` →
  `reconcile_control_plane(manifest)`, wired into the `deploy` command in
  `src/security_scan/governance/__main__.py`. Commits only the exact deployed, non-gitignored
  paths into each enclosing git work-tree; idempotent; never `git add -A`. Tests:
  `tests/test_governance_deploy.py` (the `reconcile_*` cases run against real throwaway git repos).
- `~/.claude` is a git repo; `/hooks/` tracked, `/bin/` gitignored.
- Check 13 lives in **security-standards** `scripts/security-scan.sh:240-262` (`controlplane.*`).
- governance-map: `~/Projects/security-standards/governance-map.toml` (tool `security-scan.sh`).
- This is a **separate session** for the infraops repo (mutate lane). Per the secure-way-of-working
  rules, keep this code-edit session distinct from any live-infra mutation.
