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
  Judgment rules are emitted as placeholders for the skill.
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
| `bws.secret-files-gitignored` | BLOCK | `gitignore_covers` for secret-bearing paths (`*.env`, `**/env`, `*-migration/`, `*.password`, `*.key`, token-bearing `*.plist`); any working-tree file matching a token/secret pattern must be ignored | Add the path/pattern to `.gitignore`. |
| `bws.fetch-by-name-not-uuid` | WARN | `forbidden_pattern` inline literal `BWS_*_SECRET_ID=<uuid>` in launchers + judgment on `fetch_bws_secret_by_name` usage | Fetch by secret **name** via `BWS_ACCESS_TOKEN`; keep non-secret IDs out of source (infra-brain lesson #273). |
| `bws.bootstrap-token-not-inline` | BLOCK | `forbidden_pattern` `BWS_ACCESS_TOKEN\s*=\s*0\.` literal in any tracked file (plist/compose/script/env-template) | The bootstrap token must come from a gitignored env file, never inline in committed config (the `vps-backup` plist mistake). |
| `bws.least-privilege-scope` | INFO | `judgment` (not repo-verifiable alone) | Flag for the human: confirm the token's machine-account is scoped to the minimum projects the workload needs. |

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
- **Auto-remediation of judgment findings.**

## Capability home
`~/Projects/security-standards/` — skill + bundled scanner + docs. The skill installs from here;
the scanner is the CI-runnable core.
