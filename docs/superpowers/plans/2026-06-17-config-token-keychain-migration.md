# Handoff: migrate `~/.config/*/env` BWS tokens to Keychain (infra-drift, videocreator)

**Date:** 2026-06-17 · **Owner:** Devon · **For:** the next agent (fresh session)
**Contains:** paths, secret UUIDs (non-secret), Keychain account names, commit SHAs — **no secret values.**

## Why this exists
The threat: an AI agent can read a plaintext secret file into a persistent transcript (exfil).
A live BWS access token sitting in a plaintext `~/.config/<workload>/env` is exactly that risk.
The fix is to stop storing the token in a readable file and fetch it from the macOS **login
Keychain** at runtime — the same pattern `infraops-mcp-server` already uses
(`BWS_ACCESS_TOKEN_INFRAOPS`).

This session already did this for **vps-backup** (the template — see "Reference" below) and added
a nightly content-scan (`security-scan.sh` Check 11) that **found the two remaining instances**:

- `~/.config/infra-drift/env`
- `~/.config/videocreator/env`

Your job: remediate those two the same way vps-backup was done.

## Ground rules (non-negotiable)
1. **Never print a token value into the transcript.** Validate/migrate by sourcing the file in a
   subshell and passing the *variable* (`"$BWS_ACCESS_TOKEN"`), never the literal. Transcripts persist.
2. **Order matters:** add the Keychain helper + create the Keychain item + VERIFY first; only
   **delete the plaintext env file last**, after the Keychain path is proven.
3. This is **infrastructure mutation** (live LaunchAgents). Be deliberate; verify at each gate.
4. When editing files, the `bws-write-guard.sh` hook blocks any content containing a literal token
   or the `BWS_ACCESS_TOKEN`-equals-`0.` string — describe the shape, never paste an example token.

## Decisions already made (don't re-litigate)
- **Separate Keychain account per workload:** `BWS_ACCESS_TOKEN_INFRA_DRIFT`,
  `BWS_ACCESS_TOKEN_VIDEOCREATOR`. (infra-drift's token value is likely the same Shared-Infra token
  as vps-backup's, but separate entries keep workloads independently rotatable.)
- **Update the repo-tracked scripts + plist templates**, not just the live copies, so the fix is durable.
- **Keychain service is `Claude`** (matches existing items), `-T /usr/bin/security` on the ACL so the
  LaunchAgent can read non-interactively.

## The proven playbook (per workload)
This is exactly what worked for vps-backup. Repeat per target.

1. **Add the Keychain helper.** Copy `~/Projects/vps-backup/bws-token.sh` as the template. It fetches
   `BWS_ACCESS_TOKEN` from Keychain (service `Claude`, the workload's account), is idempotent
   (respects an already-set token), and fails fast with guidance if the item is absent. Put a copy in
   the consuming repo and change the account name.
2. **Wire it into every consuming script** — add near the top, after `set -euo pipefail`, before the
   first `bws` call:  `source "$(dirname "${BASH_SOURCE[0]}")/bws-token.sh"`
3. **Remove env-file sourcing** from the plist/script that currently does it.
4. **Commit** the repo changes (code first).
5. **Migrate the token → Keychain** (transcript-safe):
   `( set -a; . ~/.config/<workload>/env; set +a; /usr/bin/security add-generic-password -U -s Claude -a <ACCOUNT> -T /usr/bin/security -w "$BWS_ACCESS_TOKEN" )`
6. **Verify** the new path with the env var unset:
   `( unset BWS_ACCESS_TOKEN; source <repo>/bws-token.sh && bws secret get <a-known-uuid> >/dev/null 2>&1 && echo OK )`
7. **Reload the LaunchAgent(s):** copy the updated plist to `~/Library/LaunchAgents/`, then
   `launchctl unload` + `launchctl load`. Confirm with `launchctl list | grep <label>`.
8. **Delete the plaintext file:** `rm ~/.config/<workload>/env` — only after 6–7 pass. Re-verify the
   Keychain path still works with the file gone.
9. **Re-run** `~/.claude/bin/security-scan.sh` and confirm the `secret.bws_token_plaintext` FAIL for
   that path is gone.

## Target 1 — infra-drift (the trickier one: ONE env file, TWO consumers)
- **Token file:** `~/.config/infra-drift/env`  → Keychain account `BWS_ACCESS_TOKEN_INFRA_DRIFT`
- **Consumers (both `source` the env file):**
  - `~/Projects/infraops-mcp-server/scripts/drift-audit.sh`  (LaunchAgent `com.devon.infra-drift`)
  - `~/Projects/infraops-mcp-server/scripts/change-window.sh` (LaunchAgent `com.devon.change-window`)
- **Repo:** `infraops-mcp-server` (has an `origin`; pushing is fine — confirm with Devon).
- **Also update for durability** (they reference the env file): in `infraops-mcp-server/scripts/`:
  `com.devon.infra-drift.plist.template`, `com.devon.change-window.plist.template`,
  `install-drift-launchd.sh`, `install-change-window-launchd.sh`, and `README.md`.
- **Both LaunchAgents** run their script directly (no env-sourcing in the plist ProgramArguments);
  the scripts source the env file internally. So the helper goes into both scripts; the plists likely
  need no change beyond what's already there — verify.
- **Do NOT delete `~/.config/infra-drift/env` until BOTH scripts are migrated and verified** (shared file).

## Target 2 — videocreator
- **Token file:** `~/.config/videocreator/env`  → Keychain account `BWS_ACCESS_TOKEN_VIDEOCREATOR`
- **Consumer:** `~/Projects/VideoCreator/start.sh` (line ~3: `source "$HOME/.config/videocreator/env"`),
  run by LaunchAgent `com.devon.videocreator` (ProgramArguments: `/bin/bash .../VideoCreator/start.sh`).
- **Repo:** `VideoCreator`.
- **CAUTION:** VideoCreator is also a *deployed* app (videogen.devonwatkins.com). Confirm what the
  LOCAL `com.devon.videocreator` LaunchAgent + `start.sh` actually do before changing — this is a local
  job, separate from the deployed instance. Don't touch the Coolify deployment.
- This token is a *different* value than infra-drift's (content/creator scope), so use its own account.

## What's already done this session (state)
- **vps-backup:** fully migrated to Keychain (`BWS_ACCESS_TOKEN_VPS_BACKUP`), env file deleted,
  verified. Committed + pushed: `vps-backup@61b4261`. **This is your working template.**
- **security-standards:** `genmanifest` + `referenced_uuids` code-scope change committed
  (`security-standards@1492db2`); pushed to new PRIVATE `AlobarQuest/security-standards`.
- **infraops-mcp-server / vps-backup:** `.bws-secrets.toml` manifests committed.
- **`~/.claude/bin/security-scan.sh`:** Check 11 (content scan of `~/.config` + LaunchAgents for the
  BWS token shape, path-only output) is LIVE. NOTE: this file lives in `~/.claude/bin` — confirm whether
  that change needs to be persisted/backed up anywhere (it runs in place via the `com.devon.security-scan`
  LaunchAgent). It currently reports FAIL for the two `~/.config/*/env` files you're about to fix.
- **`~/Projects` sweep:** clean except known security-standards fixtures and a benign placeholder in
  `workflow-scripts/adas-packet-gen-tool/BITWARDEN_SETUP.md` (not a git repo, not a live token — a
  doc example matching the `BWS_ACCESS_TOKEN=`-`0.` form; ignore or fix the doc).

## Definition of done
- Both `~/.config/infra-drift/env` and `~/.config/videocreator/env` deleted.
- All consuming scripts fetch from Keychain; repo scripts + plist templates updated and committed.
- `~/.claude/bin/security-scan.sh` shows **no** `secret.bws_token_plaintext` FAIL.
- Each migrated job verified to still authenticate to BWS via Keychain.

## Reference
- Template commit (vps-backup): `git -C ~/Projects/vps-backup show 61b4261`
- Helper template: `~/Projects/vps-backup/bws-token.sh`
- Defense-in-depth model + lineage: security-standards memory (`security-defense-layers.md`,
  `project-lineage.md`) and infra-brain lesson #343.
- Still-open follow-ups after this: the **read-guard** (machine-wide deny of reading secret files —
  the prevention layer that backstops all of this) and **least-privilege re-scoping** of the
  Shared-Infra token (it can read ~76 secrets across 3 projects — broad for these workloads).
