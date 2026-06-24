# Build-Agent Secrets Quickstart

*One page. Audience: a build/deploy agent working in any repo in this environment. Read this
before you touch a secret, an env file, or anything you'd deploy.*

## The one rule

**Secrets are sourced at runtime from Bitwarden Secrets Manager (BWS) by UUID. They are never
written into the repo, never pasted into the conversation, never echoed.** Everything below is
that rule, made concrete.

## Rules of the road

1. **Never hardcode or commit a secret.** No tokens, passwords, API keys, or connection strings
   in tracked files — not in code, configs, compose files, Dockerfiles, or docs.
2. **Source secrets at runtime from BWS:** `bws secret get <uuid>`. The bootstrap token
   `BWS_ACCESS_TOKEN` itself comes from a **gitignored env file or the macOS Keychain** — never
   assigned inline in a tracked file.
3. **Reference secrets by stable UUID, not by name.** A UUID is immutable and non-secret (useless
   without `BWS_ACCESS_TOKEN`), so hardcoding the UUID is fine. Names are mutable labels that will
   be renamed and silently break a by-name lookup.
4. **Declare what you consume** in a `.bws-secrets.toml` manifest at the repo root — the list of
   secret UUIDs this repo uses. Keep it matching reality (no missing entries, no stale ones).
5. **gitignore secret files** before creating them: `*.env`, `*.key`, `*.password`, migration
   dirs, and any local credential file.
6. **A surfaced committed token is LEAKED → tell the human to ROTATE it.** Deleting it from the
   file is not enough; assume it is compromised the moment it appears.

## How to actually fetch a secret (copy these patterns)

- **Keychain → `BWS_ACCESS_TOKEN` helper:** `~/Projects/vps-backup/bws-token.sh` (the canonical
  template — source it, don't reinvent it).
- **Fetch-all-at-startup, by UUID, with safe defaults:** `~/Projects/infraops-mcp-server/start.sh`.
- **Manifest shape:** any repo's `.bws-secrets.toml`.

Source your access token from the Keychain via that helper (each workload has its own Keychain
entry + scoped token — model yours on `bws-token.sh`; don't hand-write the `security
find-generic-password` call), then fetch any secret by UUID — never the literal value:

```bash
source ~/Projects/vps-backup/bws-token.sh   # sets BWS_ACCESS_TOKEN from the Keychain (template)
DB_PASSWORD="$(bws secret get <uuid> | jq -r .value)"   # python3 -c '...json...["value"]' also works
```

**Setting CI/repo secrets — fetch and pipe in one step.** Don't stage the value in a variable,
don't paste it:

```bash
bws secret get <uuid> | jq -r .value | gh secret set NAME -R <repo>
```

The value flows BWS → `gh` over the pipe and never lands in a shell variable, so it can't leak via
`set -x`, shell history, or the transcript. (`printf %s "$value" | gh secret set …` is fine when the
value is already in hand, but prefer the direct pipe.)

**Never paste a token into a command.** Deploy/registry/API tokens routinely contain shell-special
characters (`$`, `!`, `&`, quotes, backticks…); pasting one into a `curl -H "Authorization: Bearer …"`
or `gh` call silently mangles it and you'll chase a phantom auth failure. Always fetch from BWS into a
quoted variable or straight through a pipe.

## If you're deploying

Storage isn't the only failure mode — **scope is.** A registry or deploy token that exists and
authenticates can still be read-only, and it fails closed: GHCR push → `denied: permission_denied`,
Coolify deploy → `403`. That reads like a bug but it's a missing **write** permission. When wiring a
deploy, give the CI/registry token write scope (for GHCR, grant the package's Actions access
**write**, not just read) and verify with a real push/deploy call before calling it done.

## What is enforced on you regardless of whether you read this

Three hooks fire at the tool layer — they block you even if you never opened this doc:

- **`bws-write-guard.sh`** (PreToolUse) — **denies** any Write/Edit whose content carries a live
  BWS token (the `0.<uuid>.<secret>` shape, or an inline bootstrap-token assignment). When you
  *document* the token, describe its shape — don't paste a literal, or this guard blocks the edit.
- **`bws-read-guard.sh`** (PreToolUse on `Read`) — **denies** reading a file that contains a token,
  so it never enters the transcript.
- **`bws-scan-gate.sh`** (Stop) — **blocks the session from finishing** while the repo has any
  BLOCK-level scanner finding.

## Before you call the work done

Run the deterministic scanner against the repo (read-only; offline cache works headless):

```bash
PYTHONPATH="$HOME/Projects/security-standards/src" python3 -m security_scan.cli . --category security
```

Fix every BLOCK; fix the cheap WARN/INFO (gitignore an entry, add a manifest line); for judgment
findings, state your assessment to the human. Or just invoke the **`security-standards` skill**,
which runs this and guides the fixes.

## Go deeper

- **Rules (source of truth):** infra-brain, `category: security` (`get_rules(category="security")`).
- **Why it matters (threat model + 5-layer defense):** `docs/security-environment-overview.md`.
- **Repo overview / scanner + read-guard:** `README.md`.
