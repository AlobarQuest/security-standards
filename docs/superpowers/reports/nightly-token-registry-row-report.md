Outcome: done

# Report: a registry row for the factory-events nightly's BWS token

- **PR:** https://github.com/AlobarQuest/security-standards/pull/96 (not merged), branch
  `hq/nightly-token-registry-row`, base `main` at `e905304`.
- **Head:** `dde5a93` holds the registry file. The report commits follow it (the first was
  `679c87b`); the PR's final head is the last report commit, one past the head named in it.
- **CI on PR #96 (at `679c87b`):** all five checks passed: two lint, type-check, and test jobs,
  two `scan` jobs, and the factory-store integration tests.

## What I built

A `.cred-consumers.toml` at the repository root. Its header follows orchestrator's (lines 1-24):
what the file covers (credentials this repository's scripts read), that infraops-mcp-server's
security-drift run reads it once its path is in `~/.config/infra-drift/cred-consumers.list`, that
the schema lives in `infraops-mcp-server/.cred-consumers.toml`, and that values never appear here.
It holds `version = 1` and one row.

### The row as written

```toml
[[credential]]
id = "bws-factory-events-nightly-token"
class = "bws-machine-token"
provider = "bitwarden-sm"
provider_identity = "Bitwarden SM machine account factory-events-nightly (reads factory-events-append-password only)"
disposition = "reissue"
keeper_service = "Claude"
keeper_account = "BWS_ACCESS_TOKEN_FACTORY_EVENTS_NIGHTLY"
rotated_by_sds = false

  [[credential.consumer]]
  kind = "keychain"
  service = "Claude"
  account = "BWS_ACCESS_TOKEN_FACTORY_EVENTS_NIGHTLY"
  note = "the keeper; scripts/factory-events-nightly.sh (deployed copy in ~/.claude/bin) reads it on each run, launchd com.devon.factory-events 03:30"

  [[credential.consumer]]
  kind = "bws-secret"
  uuid = "4c1bcf0e-46f6-4ac3-9d3f-b50300d50015"
  note = "bws-factory-events-nightly-token (Rotation / Keepers; sds-operator's temporary direct grant removed 2026-11-15) — BWS keeper copy, from which FE-5 act step 0 wrote the Keychain item (D-54 A, 2026-11-15); no launcher reads it"
```

The fields match the two orchestrator siblings (`bws-bump-proposer-token`,
`bws-factory-events-session-token`) field for field. There's no `created` and no fingerprint. A
comment block before the row records the provenance (console-minted, hand-rotated, keeper copy in
Rotation / Keepers) and names where the siblings live.

I checked the facts in the keychain note against the system rather than taking them from the
handoff:

- `scripts/factory-events-nightly.sh` lines 174-176 read Keychain `Claude` /
  `BWS_ACCESS_TOKEN_FACTORY_EVENTS_NIGHTLY`. A grep of `scripts/` and `src/` finds no other
  reader; `src/factory_events/README.md` mentions the name but doesn't read it.
- `governance-map.toml` deploys the script to `~/.claude/bin/factory-events-nightly.sh`.
- `~/Library/LaunchAgents/com.devon.factory-events.plist` runs that deployed copy at 03:30.

## Parser check

The infraops parser is permissive. `parseCredConsumers` accepts any key and any consumer `kind`
string; it validates only string `id`/`class`, a boolean `rotated_by_sds`, a non-empty consumer
`kind`, and unique ids. So "it parses" doesn't show the kinds are right. What confirms them:

- The schema comment in infraops `.cred-consumers.toml` (lines 12-13) documents
  `bws-secret { uuid }` and `keychain { service, account }`. The row uses exactly those fields.
- `git grep` of infraops `src/` at `c3359bf` finds no code that reads a consumer's `kind` beyond
  the non-empty check (`cred-consumers.ts` line 214). Consumer kinds are documentation for the
  manual checklist, and both match the siblings.

All of the following checks passed:

1. **infraops parser.** I extracted infraops-mcp-server `origin/main` (`c3359bf`) with
   `git archive` into a scratch directory, linked its `node_modules`, and ran
   `loadCredConsumerFiles` from `src/security-drift/cred-consumers.ts` under `tsx`. The row
   parses with every field present: `id`, `class`, `provider`, `provider_identity`,
   `disposition`, `keeper_service`, `keeper_account`, `rotated_by_sds` (boolean), and both
   consumers (`keychain` with `service`/`account`/`note`, `bws-secret` with `uuid`/`note`). The
   parser's class check at line ~207 (string `id` and `class`) and its `rotated_by_sds` boolean
   check pass.
2. **Cross-file load.** I loaded the four files in the current `cred-consumers.list` together
   with the new file: 53 credentials, and no `duplicate credential id ... across files` error.
3. **Rotation policy.** `bws-machine-token` is in `CLASS_POLICY` (`cred-rotation.ts` line 88,
   365-day max age). `credFindings` on the row, with an empty rotation state, returns no findings,
   so there's no `cred.unknown-class` warning. `buildCredClassifications` builds the row's five
   classifications without error, and `scanFindings` over the full 53-credential set returns
   nothing for the row.
4. **tomllib.** Python 3.14.3 `tomllib` parses the file: `version` 1, one credential, consumer
   kinds `keychain` and `bws-secret`.

I didn't edit `~/Projects/infraops-mcp-server`. I did run `git fetch` there to resolve `origin/main`.

## The list line

The 03:00 scan doesn't read this file without the list entry. `src/cli/security-drift-cli.ts`
(lines 119 and 171) loads only the files that `~/.config/infra-drift/cred-consumers.list` names,
and an unlisted file isn't loaded. The list names four files and not this one. After the PR
merges and the main checkout fast-forwards, add this exact line:

```
/Users/devon/Projects/security-standards/.cred-consumers.toml
```

It's the main checkout's path, the same form as the other four entries, not this worktree's.
Until the PR merges, that path doesn't exist. A listed file that can't be read throws
`CredConsumersParseError` and fails the whole registry load, so add the line only after the merge.

## Tests and checks

- `make check` (exit 0): ruff check passed, ruff format found 66 files already formatted, pyright
  reported 0 errors, and shellcheck was clean. pytest **collected 293 items, 25 deselected
  (`-m 'not integration'`), 268 selected: 268 passed**.
- Security scanner (`python -m security_scan.cli . --category security`, the CI step), rerun
  after the file was committed: 0 BLOCK, 4 WARN, and 1 INFO. None names `.cred-consumers.toml`. All of them predate this change and are in files I didn't touch.
- CI's `security-scan.yml` also runs `agent_registry validate` and the read-guard tests. Neither
  touches this file. The read-guard tests are part of the 268.

## Files changed

- `.cred-consumers.toml` (new).
- `docs/superpowers/reports/nightly-token-registry-row-report.md` (this report).

## Self-review

- No value of any kind is in the file. It names the token only by its row id, its Keychain item,
  and its keeper UUID.
- The parser rejects embedded double quotes in strings. The notes contain none; the `'` and `—`
  characters in them parse, as they do in the siblings.
- The header doesn't copy orchestrator's line about `healthchecks_check`, because no row here is
  `rotated_by_sds`. It says plainly that the row falls to the manual checklist.
- `/code-review low` on `main...HEAD` reported no findings.

## Concerns

- The scan doesn't cover this token until someone adds the list line in the preceding section.
  This worker was told not to edit the list.
- orchestrator's `.cred-consumers.toml` comment (around line 1363) still says that
  security-standards keeps no `.cred-consumers.toml`. After this PR merges, that comment is
  out of date and needs an orchestrator follow-up. I didn't change it, because it's outside my
  worktree.
- The repository's docs don't forbid a consumer registry. The only mention is in
  `docs/superpowers/reports/work-carrier-identity-registry-report.md`, which refers to other
  repositories' files. So neither stop point applied.

## Standards followed

- **Code Brain rule 5 (BLOCK): never log or write secrets, credentials, or tokens.** The file,
  commit, PR body, and this report name the token only by row id
  (`bws-factory-events-nightly-token`), Keychain item (`Claude` /
  `BWS_ACCESS_TOKEN_FACTORY_EVENTS_NIGHTLY`), and keeper UUID. I never read the value or a
  fingerprint. The scanner reports 0 BLOCK.
- **Code Brain rules 3 and 4 (structured logs, no swallowed exceptions):** don't apply, because
  the change has no code.
- **BWS standard (secrets by UUID, no token in any file):** the keeper copy is named by its stable
  UUID `4c1bcf0e-46f6-4ac3-9d3f-b50300d50015`, and no token is in any file.
- **Not covered by the Standards section:** none. Infra Brain wasn't needed, because the change
  makes no infrastructure change.
