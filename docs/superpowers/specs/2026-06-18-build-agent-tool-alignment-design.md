# Build-Agent Tool Alignment — Design

**Date:** 2026-06-18
**Status:** Approved (brainstorm), pending implementation plan
**Repo home for this work:** `security-standards` (the governance source of truth)

## Problem

A set of security / scanning / change-management tools has accumulated across three
repos and several global directories:

- `~/Projects/security-standards/` — the `security_scan` Python package + 3 BWS hooks
- `~/Projects/infraops-mcp-server/` — the MCP server, `drift-audit.sh`, `change-window.sh`,
  the `security-drift` TS subsystem, **and** `security-scan.sh` + `skills-security-scan.sh`
- `~/Projects/change-manager/` — the FastAPI approval service
- `~/.claude/bin/`, `~/.claude/hooks/` — **deployed copies** of scripts/hooks
- `~/.config/infra-drift/`, `~/infra-drift/reports/`, `~/.claude/audit/` — runtime state

The goal is a **build agent** model: when working inside a repo (e.g. FacelessTT), the
in-repo Claude session should have exactly the tooling and governance that belongs to
that repo — no more, no less.

Investigation showed ownership is **mostly already correct**. The felt "scatter" is two
real problems:

1. **Deployed artifacts have drifted from their home repos.** Sharpest case:
   `security-scan.sh`'s deployed copy in `~/.claude/bin/` is *ahead* of the repo source,
   and the installer overwrites the repo — so the source of truth is effectively inverted.
2. **One genuine boundary impurity:** the read-only machine *detectors*
   (`security-scan.sh`, `skills-security-scan.sh`) live in the *mutation* repo (infraops)
   instead of with the rest of the detection layer (security-standards).

## Mental Model — Three Axes

The word "tool" was conflating three independent classifications. Making them explicit
makes every ownership question answer itself.

### Axis A — The lane (what a tool *does*)

> **security-standards *detects*. infraops-mcp-server *mutates*. change-manager *approves*.**

Every executable belongs to exactly one lane, which fixes its home repo. This is why the
detectors move to security-standards (detection lane).

### Axis B — The artifact class (where a file physically lives)

| Class | Lives in | Rule |
|---|---|---|
| **Source** | a home repo | The only place it is edited. |
| **Deployed artifact** | `~/.claude/bin/`, `~/.claude/hooks/` | Repo is source; this is a *target*. Deploy is one-directional (repo → target) + verify. **Never edited in place.** |
| **Runtime state** | `~/.config/infra-drift/`, `~/infra-drift/reports/`, `~/.claude/audit/` | Machine-level. Gitignored. **Never repatriated into any repo.** |

This answers "align tools *and directories* into the proper repos": some directories
deliberately stay out. The `security-scan.sh` drift is a single instance of one rule
(deployed artifact edited in place) being violated.

### Axis C — The build-agent class (how a repo relates to the tools)

| Class | Repos / targets | Relationship |
|---|---|---|
| **Tool-home** | security-standards, infraops-mcp-server, change-manager | Opened to *develop* a tool. Owns source; deploys artifacts; declares its consumers. |
| **Infra/governance target** | the Mac itself + Coolify/VPS (**not repos**) | Governed by scheduled jobs + global hooks. No build agent — nothing to open. |
| **Product/consumer** | FacelessTT, etc. | Consumes security-standards only. Carries a thin governance stanza + `.bws-secrets.toml` when it uses BWS. |

A repo can wear two hats: security-standards is a *tool-home* (owns the scanner) **and** a
*consumer* (the scanner scans it too).

**On the infra/governance class:** `security-scan.sh` scans the Mac's own configuration and
`drift-audit.sh` scans live Coolify/VPS state — neither has a repository. Their *source*
lives in a home repo, but the thing they *act on* is headless, governed entirely by:

```
3:00 AM  launchd → drift-audit.sh     → scans Coolify, files findings → change-manager
9:00 Mon launchd → security-scan.sh   → scans the Mac, logs findings  → change-manager
4:00 AM  launchd → change-window.sh   → executes approved fixes
always   ~/.claude/hooks/*            → guard every session on the machine
```

The practical payoff: this stops over-distribution. Opening FacelessTT should **not** pull
in `security-scan.sh`/`drift-audit.sh` — they govern the laptop and the cloud, not the app.
The only build agent that touches those scripts is their tool-home, where you go to improve
the detector.

## Phase 1 — Repatriate Ownership

Four moves, in dependency order.

### 1. Create the ownership manifest (the single source of truth)

One declarative file, `governance-map.toml`, living in **security-standards**. It encodes
all three axes for every tool and repo. Each tool entry records: lane, home repo, artifact
class, deploy target, installer. Each repo entry records: build-agent class and (for
tool-homes) the tools it owns and its consumers.

Everything else in both phases is *projected from this file* — the Phase 2 CLAUDE.md
generator reads it, and the verify step checks reality against it. Nothing is governed by
memory. TOML matches the existing `.bws-secrets.toml` house style.

### 2. Move the detectors, reconciling drift in the same motion

Relocate `security-scan.sh` + `skills-security-scan.sh` + their launchd installer from
`infraops/scripts/` → `security-standards/`.

**Critical:** the deployed `~/.claude/bin/` copy is *ahead* of the repo (it has the PATH
fix). The canonical content is **the deployed version**, imported as the new source — not
the stale infraops copy. The `security-drift` subsystem in infraops keeps calling
`~/.claude/bin/security-scan.sh` by path and by the `security_scan.read_guard.selfcheck`
Python module, so it does not notice the move (runtime coupling is to the deployed path,
not the repo path).

### 3. Make deploy one-directional + verifiable (every deployed artifact)

Applied to both the `bin/` detectors and the 3 BWS hooks:

- Each home repo gets `make install` → copies source into `~/.claude/{bin,hooks}/` and
  records a checksum.
- Each home repo gets `make verify` → fails if a deployed artifact ≠ its repo source.
- `security-scan.sh` already detects control-plane git drift; it gains one check: *"is every
  deployed artifact in sync with its home repo per the manifest?"* — so future in-place
  edits are flagged automatically at the next scan. The loop closes itself.

### 4. Codify runtime-state directories as deliberately repo-less

Record in the manifest that `~/.config/infra-drift/`, `~/infra-drift/reports/`, and
`~/.claude/audit/` are runtime state — gitignored, never repatriated. This makes the "should
these go in a repo?" answer explicit and intentional.

**Phase 1 end state:** every executable has exactly one home repo; `~/.claude/{bin,hooks}`
are pure deploy targets that cannot silently drift; runtime dirs are explicitly out of
scope; a single manifest describes the whole picture.

## Phase 2 — Build-Agent Alignment

Everything here is *projected from the manifest*. No new source of truth.

### 1. Manifest carries each repo's class

Tool-home and consumer repos get a stanza; infra/governance targets are noted but get
nothing (no repo to write to). The manifest's `consumers` list doubles as a lightweight
registry — providing list/bulk-audit capability for free, as a seed for later per-repo
build-agent functionality.

### 2. The governance stanza

A generated `## Security & Governance` block in each build agent's CLAUDE.md, fenced by
`<!-- governance:start -->` / `<!-- governance:end -->` markers so it is idempotent and safe
to regenerate. Content depends on class:

- **Tool-home** (e.g. infraops): *"This repo owns: `drift-audit.sh`, `change-window.sh`, the
  infraops MCP. Lane: **mutate**. Deploy: `make install`. Verify: `make verify`. Consumers:
  [list]."* — a fresh session knows what it is responsible for deploying.
- **Consumer** (e.g. FacelessTT): *"Governed by security-standards (lane: detect).
  Enforcement is automatic via global hooks (write/read/scan-gate) — you run nothing. To
  audit on demand: the `security-standards` skill. BWS usage declared in
  `.bws-secrets.toml`."* — the agent knows it is governed even though enforcement is
  invisible.

### 3. The generator

`python -m security_scan.governance sync`, living in security-standards. Reads
`governance-map.toml`, writes/updates each repo's stanza between the markers, and stamps a
`.bws-secrets.toml` skeleton into any consumer that needs one but lacks it. Idempotent: if
the stanza is already correct, it skips the write entirely.

### 4. Verification closes the loop

Phase 1's `make verify` extends to: *"does each repo's CLAUDE.md stanza match what the
manifest would generate?"* A hand-edited or stale stanza fails verify, exactly like a
drifted binary. The manifest stays canonical; CLAUDE.md is a checkable projection.

### 5. Onboarding a new build agent

One operation: add an entry to `governance-map.toml`, run `sync`. This is the practical
payoff and the foundation the later per-repo build-agent functionality plugs into.

## Summary

The whole system reduces to:

- **One lane rule** — *detect / mutate / approve* — fixes every ownership question.
- **One manifest** (`governance-map.toml` in security-standards) — projected into deploys,
  CLAUDE.md stanzas, and verification.

## Decisions Made During Brainstorm

1. **Both phases, in order** — repatriate ownership first, then map to build agents.
2. **Tool home vs consumer are two distinct roles** — a repo can be both.
3. **Detectors move to security-standards** — adopt the clean detect/mutate/approve boundary.
   Runtime consumers bind to the deployed path, so the move is low-risk.
4. **Consumer alignment = thin generated CLAUDE.md stanza** (+ `.bws-secrets.toml`), not a
   separate registry — though the manifest's `consumers` list provides registry capability
   for free.

## Open Items for the Implementation Plan

- Exact schema of `governance-map.toml` (tool entries vs repo entries).
- Confirm the 3 BWS hooks have source in security-standards (vs only deployed) before wiring
  `make install`/`make verify` for them.
- Where `make`-style targets live for each repo (Makefile vs an install script the manifest
  points to).
- Whether the new "deployed-artifact-in-sync" check in `security-scan.sh` reads the manifest
  directly or a generated checksum list.
