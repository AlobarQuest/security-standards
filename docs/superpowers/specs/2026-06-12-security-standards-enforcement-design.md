# Security Standards Enforcement — Design Spec

**Date:** 2026-06-12 · **Status:** design approved (brainstorming) → next: implementation plan

## Context
In this environment the developers are AI agents; Devon is the only human. The goal is a
capability that checks whether a repo/project follows agreed security standards and points the
**fixing agent** at the remediation. This is the **first entry** in a broader security-standards
system; the first standard captured is **BWS (Bitwarden Secrets Manager) proper usage**, distilled
from a token-leak incident remediated 2026-06-12 (a machine-account access token committed to a
launchd plist in git, compounded by broad/global token deployment via `~/.zshenv`).

The design reuses the proven pattern from `coolify_audit_standards`: **declarative rules in
infra-brain → an evaluation engine → findings paired with concrete remediation.**

## Locked decisions (from brainstorming)
- **Surfaces:** one shared checker, surfaced as **(A, priority)** an agent-invoked Claude Code
  **skill**, and **(B)** an automated/CI **scan**.
- **Mechanism:** **hybrid** — a deterministic rule core + an agent-judgment layer.
- **Standards storage:** **infra-brain**, a new `security` rule category (rules as data, fetched
  live; rules are non-secret, so they are also cacheable/bundleable).
- **Consumers:** **machine agents.** The infra-brain rules *are* the captured standard (no human
  manifesto); findings orient a fixing agent.
- **Output:** structured finding **+** remediation hint **+** rule reference.
- **Packaging:** **skill-first** (a skill bundling a deterministic scanner script that is also
  CI-runnable); graduate the scanner into a standalone tool later if the rule set outgrows BWS.

## Architecture
```
infra-brain ──(category: security)──► rules as data (repo-oriented `check` + remediation)
     │
     ▼
scanner script ── reads rules, inspects a target repo (files/git/.gitignore) ──► findings JSON
     │                                                                               │
     ├──► surface A (priority): the SKILL — runs scanner, adds judgment-layer checks, │
     │     presents findings + remediations, fixes mechanical / guides judgment ones  │
     └──► surface B: CI/scan — runs the scanner standalone, fails on BLOCK findings ◄──┘
```

## infra-brain `security` rule schema
Each rule is data the scanner evaluates generically — adding a standard is `add_rule`, not a code
change.

| Field | Purpose |
|---|---|
| `category` | `security` (sub-tag e.g. `security.bws`) |
| `rule` / `reason` | the captured standard + why (machine-read by fixing agents) |
| `severity` | `BLOCK` / `WARN` / `INFO` |
| `check` | a **repo predicate** the scanner runs deterministically, **or** `kind:"judgment"` |
| `remediation` | the fix hint handed to the agent |

### Repo predicate types (the deterministic `check` vocabulary — small, extensible)
- **`forbidden_pattern`** — a regex must NOT appear in a fileset. Params: `pattern`, `scope`
  (`tracked` | `history` | `working-tree`), optional `paths`/`globs`. *Catches committed tokens.*
- **`gitignore_covers`** — given path(s)/glob(s) must be git-ignored (`git check-ignore`). Also:
  any working-tree file whose contents match a secret pattern must be ignored. *Catches unignored
  secret files.*
- **`path_absent` / `path_present`** — a path must not / must exist (or be tracked).
- **`required_pattern`** — a regex must be present where expected.
- **`judgment`** — no deterministic check; the skill reasons from `rule` + `reason`.

## The scanner (`security-scan`)
- **Language:** Python (regex/git/file ergonomics; runs anywhere with `python3`, incl. CI).
- **Input:** target repo path (default cwd), optional `--category security.bws`, `--json`.
- **Rules source:** fetch `security` rules from infra-brain live (reuse `x-brain-key` auth);
  **degrade to a bundled rule cache** if infra-brain is unreachable. Rules are non-secret, so the
  cache ships with the skill — the scanner works offline and in CI without infra-brain creds.
- **Evaluation:** per rule with a deterministic `check`, run the predicate against repo state
  (`git ls-files` = tracked; `git log`/`git grep` = history; `git check-ignore` = gitignore).
  It also parses `.bws-secrets.toml` and cross-references declared UUIDs against the UUIDs found in
  code (for `manifest-matches-usage`). Judgment rules are emitted as placeholders for the skill.
- **Output (JSON):**
  `{ meta:{rules_source, evaluated}, summary:{by_severity}, findings:[{rule_id, severity,
  file, line, evidence, remediation, reason, kind}] }`.
- **Safety:** read-only; **redacts** matched secret values in `evidence` (location + masked
  snippet only — a scanner that prints the secret it found would itself be the leak).
- **Exit code:** non-zero if any `BLOCK` finding → enables CI gating.

## The skill (surface A)
A Claude Code skill an agent invokes while working a repo (during review, before declaring done,
or on request):
1. Run the bundled scanner → deterministic findings.
2. **Judgment layer:** for `judgment` rules, read the repo + rule/reason and assess (e.g. "is this
   token the *minimal* scope?").
3. Present combined findings (severity, remediation, rule ref); **fix mechanical ones** / guide the
   working agent on judgment ones. Respect existing norms (confirm before outward-facing or
   irreversible actions; rotate any exposed credential it surfaces).

## CI (surface B)
A workflow step runs the same `security-scan` against the repo and fails on `BLOCK`. Uses the
bundled rule cache (hermetic) or live infra-brain when creds are present.

## v1 BWS rule set (the first captured standards)
| Rule id | Sev | Deterministic check | Remediation |
|---|---|---|---|
| `bws.no-token-in-tracked-files` | BLOCK | `forbidden_pattern` `0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}`, scope=tracked | Remove the token; move it to a gitignored env file sourced at runtime; **rotate** the exposed token. |
| `bws.no-token-in-git-history` | BLOCK | same regex, scope=history | Rotate/revoke the token (history retains it); optionally scrub with `git filter-repo`. |
| `bws.secret-files-gitignored` | WARN | `gitignore_covers` for secret-bearing paths (`*.env`, `**/env`, `*-migration/`, `*.password`, `*.key`, token-bearing `*.plist`); only evaluated when the repo actually consumes BWS secrets | Add the path/pattern to `.gitignore`. (WARN not BLOCK: preventive pattern-coverage, not actual-file exposure — a committed secret file is still caught by the no-token rules.) |
| `bws.reference-by-stable-uuid` | WARN | `forbidden_pattern` for by-name fetch (`fetch_bws_secret_by_name "…"`, or `bws secret list` piped to a `.key ==` filter) + judgment | Reference BWS secrets by their **stable UUID** (`bws secret get <uuid>`), not by name. The UUID is immutable; the name is human-readable and **will** be renamed. The UUID is non-secret, so hardcoding it in a launcher is fine. |
| `bws.bootstrap-token-not-inline` | BLOCK | `forbidden_pattern` `BWS_ACCESS_TOKEN\s*=\s*0\.` literal in any tracked file (plist/compose/script/env-template) | The bootstrap token must come from a gitignored env file, never inline in committed config (the `vps-backup` plist mistake). |
| `bws.secret-manifest-present` | WARN | `path_present`: if the repo references any BWS secret UUID, a `.bws-secrets.toml` must exist | Add a `.bws-secrets.toml` declaring the secret UUIDs this repo consumes (see Secret manifest below). |
| `bws.manifest-matches-usage` | WARN | deterministic: `set(UUIDs referenced in code) == set(UUIDs in manifest)` | Add **undeclared** UUIDs to the manifest; remove **stale** entries the code no longer uses. |
| `bws.least-privilege-scope` | INFO | `judgment` — uses the manifest as input (which projects the declared UUIDs live in = the projects this workload needs) | Confirm the workload's machine-account is scoped to only the projects its manifest's UUIDs require. |

## Secret manifest (`.bws-secrets.toml`)
A co-located, repo-root file declaring the BWS secrets a repo consumes. It is the human-readable
layer over the stable UUIDs the code references (resolving the opacity of `reference-by-stable-uuid`)
**and** the data foundation for least-privilege scope management.

Schema (minimal, extensible):
```toml
[meta]
workload = "infraops MCP / drift audit"          # what runs this code (optional; aids aggregation)

[[secret]]
uuid    = "45eb083f-4b05-4251-924d-b46700e5a643"  # stable key — matches what the code references
name    = "INFRABRAIN_ACCESS_KEY"                 # current human label (informational; may change)
purpose = "Auth to the infra-brain REST API"
```

Enforcement is the two rules above: `bws.secret-manifest-present` (a BWS-using repo must have one)
and `bws.manifest-matches-usage` (the manifest's UUID set must equal the UUIDs referenced in code —
no undeclared, no stale). These keep the manifest from rotting into fiction. The `name`/`purpose`
fields are documentation (not accuracy-enforced, since names are mutable); the **UUID** is the
enforced key.

## Output (finding) shape
`{ rule_id, severity, file:line, evidence (redacted), remediation, reason, kind }` — same spirit as
the Coolify audit's `planned_action` + `reasoning`, repo-oriented.

## Testing / verification
- **Predicate unit tests** against fixture repos: a repo with a committed token → BLOCK; clean
  repo → pass; unignored `.env` → BLOCK; token in history but not working tree → history BLOCK.
- **Redaction test:** assert no full secret value appears in output.
- **Rule-source degrade:** live infra-brain → `rules_source: live`; unreachable → `cache`.
- **Dogfood:** run against `vps-backup` (its history contains a once-committed token →
  `bws.no-token-in-git-history` should fire) and `infraops-mcp-server` (should be clean).
- **Skill end-to-end:** an agent invokes the skill, receives findings, and fixes a mechanical one.

## Out of scope (v1)
- **Host-level** BWS hygiene (`~/.zshenv` global token, launchd plists *outside* a repo) — the
  scanner is repo-scoped; a host audit is a future surface.
- **General secret scanning** beyond BWS (gitleaks territory) — the predicate types generalize,
  but v1 captures BWS only.
- **Manifest aggregation / auto-scope derivation** across repos (union manifests → minimal
  per-account scope, flag vault drift, surface orphan secrets) — a future tool; v1 only **produces
  and enforces** the per-repo manifest that tool will consume.
- **Auto-remediation of judgment findings.**

## Capability home
`~/Projects/security-standards/` — skill + bundled scanner + docs. The skill installs from here;
the scanner is the CI-runnable core.
