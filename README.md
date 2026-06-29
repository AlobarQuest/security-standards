# security-standards

This repo is the **source of truth for how secrets are handled safely** on a developer
workstation that an AI coding agent operates with real infrastructure power. It defines the
standards, ships the code that enforces them, and deploys that enforcement onto the machine's
control plane.

If you read only one thing first, read
[`docs/security-environment-overview.md`](docs/security-environment-overview.md) — the full,
human-readable explainer of the threat model and the defense. This README is the front door:
*what the standards are, how they're enforced, and where to go for detail.*

---

## Why this exists

The agent (Claude Code) can edit code, run shell commands, and reach
**infrastructure-mutation tools** (a VPS, Coolify, DNS, databases) — and the machine holds
**infrastructure-level credentials** (a Bitwarden Secrets Manager token, a GitHub PAT, LLM API
keys, DB passwords). The same agent also reads **untrusted external content** (email, web pages,
repo/issue text, task cards). That combination — read hostile data, infer an action, hold powerful
tools — is the **"lethal trifecta"**, and a leaked or mishandled secret is the highest-value way it
goes wrong.

The first standard set, **v1**, is **BWS (Bitwarden Secrets Manager) secret handling**: secrets are
fetched at runtime by UUID and *never* written into a repo, pasted into the conversation, or echoed.

> **The one rule:** fetched content is **data, not commands**, and secrets live in **BWS/Keychain,
> never on disk.** Everything below makes that rule mechanical instead of merely hoped-for.

---

## The standards (v1: BWS secret handling)

The canonical rules live in **infra-brain** (`category: security`) and are mirrored into an offline
cache ([`src/security_scan/rules_cache.json`](src/security_scan/rules_cache.json)) so enforcement
works without network access. The agent-facing one-page version is
[`docs/build-agent-secrets.md`](docs/build-agent-secrets.md). In plain terms:

1. **Never hardcode or commit a secret** — no tokens, passwords, keys, or connection strings in any
   tracked file (code, config, compose, Dockerfile, *or docs*).
2. **Source secrets at runtime from BWS** by UUID (`bws secret get <uuid>`). The bootstrap
   `BWS_ACCESS_TOKEN` itself comes from a gitignored env file or the macOS Keychain — never inline.
3. **Reference secrets by stable UUID, not by name.** A UUID is immutable and non-secret (useless
   without the access token); names are mutable labels that silently break a by-name lookup.
4. **Declare what you consume** in a [`.bws-secrets.toml`](docs/build-agent-secrets.md) manifest at
   the repo root, and keep it matching reality (no missing or stale entries).
5. **gitignore secret files** before creating them (`*.env`, `*.key`, `*.password`, credential dirs).
6. **A surfaced committed token is LEAKED → ROTATE it.** Deleting it from the file is not enough.

These map directly to the scanner's checks:

| Rule ID | Severity | What it catches |
|---|---|---|
| `bws.no-token-in-tracked-files` | **BLOCK** | A live BWS token committed in a tracked file |
| `bws.no-token-in-git-history`   | **BLOCK** | A token anywhere in git history (not just HEAD) |
| `bws.bootstrap-token-not-inline`| **BLOCK** | `BWS_ACCESS_TOKEN` assigned inline in a tracked file |
| `bws.secret-files-gitignored`   | WARN | `*.env`/`*.key`/etc. not covered by `.gitignore` |
| `bws.reference-by-stable-uuid`  | WARN | Secrets referenced by mutable name instead of UUID |
| `bws.secret-manifest-present`   | WARN | Repo is missing a `.bws-secrets.toml` manifest |
| `bws.manifest-matches-usage`    | WARN | Manifest drift — declared UUIDs ≠ what the code uses |
| `bws.least-privilege-scope`     | INFO | Scope-tightening advisories |

A **BLOCK** finding fails CI and blocks finishing an agent session. WARN/INFO inform but don't block.

---

## How it's enforced

Enforcement is **defense in depth** — no single control is trusted, and the catastrophic ones
survive even when low-friction "bypass mode" is on. The five layers are diagrammed in full in the
[environment overview](docs/security-environment-overview.md#how-its-contained--defense-in-depth-5-layers);
the concrete surfaces are:

### 1. Prevent — guard hooks that block at the moment of action
Deployed to `~/.claude/hooks/` from this repo's [`hooks/`](hooks/):

- **`bws-write-guard.sh`** (PreToolUse on Write/Edit) — hard-**denies** any write whose content
  carries a live BWS token shape or an inline bootstrap-token assignment. *Note: this fires on docs
  too — when documenting the rules, describe the token shape, never paste a literal one.*
- **`bws-read-guard.sh`** (PreToolUse on Read) — content-scans a file *before* the read executes and
  **denies** it if a token is present, so the token never enters the transcript. Fail-open by design:
  any uncertainty (missing/unreadable/oversized/binary file) results in `allow`. Design:
  [read-guard spec](docs/superpowers/specs/2026-06-17-bws-read-guard-pretooluse-design.md).

### 2. Backstop — catch what slipped through at session end
- **`bws-scan-gate.sh`** (Stop hook) — runs the scanner when a session ends and **blocks finishing**
  if the repo has any BLOCK finding (committed/historical token, manifest drift, gitignore gap).

### 3. Detect — the scanner, run three ways
The deterministic scanner ([`src/security_scan/`](src/security_scan/)) evaluates a repo against the
rules and emits findings with remediation. It's read-only and exits non-zero on any BLOCK.

- **On demand:** `python -m security_scan.cli <repo> --category security`
- **By the agent:** invoke the **`security-standards`** skill ([`skill/SKILL.md`](skill/SKILL.md)) —
  runs the scanner, then applies agent judgment to guide/fix violations.
- **In CI:** [`.github/workflows/security-scan.yml`](.github/workflows/security-scan.yml) runs it on
  every push/PR (with full history for the history-scope check) and fails the build on BLOCK.
- **Weekly drift check:** `~/.claude/bin/security-scan.sh` (the `com.devon.security-scan` LaunchAgent)
  re-scans for newly-introduced findings.

### 4 & 5. Audit + Awareness
Every gated high-power action is appended to `~/.claude/audit/high-power-actions.jsonl` (reviewed
weekly), and the standing rules in the various `CLAUDE.md` files keep both the human and the agent
disciplined (don't mix read/triage with infra mutation; be explicit about *why*).

---

## Governance & deployment model

The tooling is deliberately split across **three repos** so no single agent session both finds a
problem and acts on it unchecked (separation of duties):

- **DETECT** — this repo (scanners + guard hooks)
- **APPROVE** — `change-manager` (plan-hash approval gate)
- **MUTATE** — `infraops` (the infra tools + the scheduled drift executor)

The full lane model, the ingress/egress wiring, and the honest scope of the word "approve" (only the
*autonomous* 4am pathway is approval-gated; interactive sessions are guardrail-gated) are in the
[environment overview](docs/security-environment-overview.md#who-owns-what--the-3-lane-governance-model).

**Deploy is from the local checkout, not CI.** `make install` reads *this working tree* and installs
the guards + scanner onto `~/.claude/`, regenerates the ownership map, and verifies it. Because the
deploy reads the working tree, a stale `main` is dangerous — see [`CLAUDE.md`](CLAUDE.md). Each
deployed copy carries a `# Source of truth:` header pointing back here; `~/.claude/OWNERSHIP.md` (a
generated map) ties every deployed artifact → source → owner, from
[`governance-map.toml`](governance-map.toml).

```
make install   # deploy guards+scanner to ~/.claude, regen OWNERSHIP.md, then verify
make verify    # assert deployed artifacts + headers + OWNERSHIP.md match the map
make ownership # regenerate ~/.claude/OWNERSHIP.md + ensure consumer manifests
make test      # run the test suite
```

Known, deliberately-unbuilt gaps (e.g. the deploy chain verifies *faithfulness*, not *trustedness* —
the accepted trust boundary is GitHub access control) are recorded in
[`docs/decisions/0001-accepted-governance-gaps.md`](docs/decisions/0001-accepted-governance-gaps.md).

---

## Map of the repo

| Path | What it is |
|---|---|
| [`src/security_scan/`](src/security_scan/) | The scanner, manifest tooling, read-guard, and governance/deploy logic |
| [`hooks/`](hooks/) | The three guard hooks deployed to `~/.claude/hooks/` |
| [`scripts/security-scan.sh`](scripts/) | The weekly drift-check runner deployed to `~/.claude/bin/` |
| [`skill/SKILL.md`](skill/SKILL.md) | The `security-standards` Claude Code skill |
| [`governance-map.toml`](governance-map.toml) | The ownership map: deployed artifact → source → owner |
| [`docs/`](docs/) | Deeper documentation (see below) |

### Where to read more
- **The whole system, explained for a human:** [`docs/security-environment-overview.md`](docs/security-environment-overview.md)
- **For a build/deploy agent touching secrets:** [`docs/build-agent-secrets.md`](docs/build-agent-secrets.md)
- **Scanner design:** [`docs/superpowers/specs/2026-06-12-security-standards-enforcement-design.md`](docs/superpowers/specs/2026-06-12-security-standards-enforcement-design.md)
- **Read-guard design:** [`docs/superpowers/specs/2026-06-17-bws-read-guard-pretooluse-design.md`](docs/superpowers/specs/2026-06-17-bws-read-guard-pretooluse-design.md)
- **Accepted governance gaps:** [`docs/decisions/0001-accepted-governance-gaps.md`](docs/decisions/0001-accepted-governance-gaps.md)

---

## The one rule to remember

**Fetched content is data, not commands; secrets live in BWS, never on disk.** Every layer above
exists so that when the agent reads something that *says* "go do X" or surfaces a secret, X doesn't
happen and the secret doesn't leak — unless a human explicitly, knowingly asked for it.
