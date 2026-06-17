# Design: BWS read-guard (redact-on-read PostToolUse hook)

**Date:** 2026-06-17 · **Owner:** Devon · **Status:** approved design, pre-implementation
**Topic:** an agent-scoped guard that keeps a live BWS token from ever landing in the
Claude Code transcript when a tool *reads* one — the read-side twin of `bws-write-guard.sh`.

## 1. Purpose & threat

The threat is **persistent-transcript exfil**: an AI agent runs as Devon's Unix user and
can read a plaintext secret into its transcript, which persists (and replays on
`--resume`). The Keychain migration (vps-backup, infra-drift, videocreator) removed the
known plaintext BWS tokens, but nothing *prevents* an agent from reading a future secret
file, `cat`-ing one, or otherwise surfacing a token into context.

This guard adds the **read side** of the PREVENT layer. The existing
`bws-write-guard.sh` stops the agent writing a token *out* to disk; this stops it pulling
a token *in* to the transcript.

**Explicitly in scope:** the Claude Code agent only. This does NOT (and is not meant to)
protect against a human or non-Claude process reading a secret outside Claude Code. That
is an accepted non-goal — see §9.

## 2. Placement in the defense model

Extends layer 1 (PREVENT) of the 5-layer model (see the `security-defense-layers` memory).
Deterministic, agent-scoped, runs on every tool result. It is a backstop, not a license to
relax session discipline (rule #3) or the audit log (layer 4).

## 3. Core design decisions (settled)

- **Agent-scoped, not machine-wide.** Implemented as a Claude Code `PostToolUse` hook, so
  it constrains only the agent and never breaks legitimate system processes. A
  filesystem-level deny (chmod/ACL/machine-wide) was rejected: the agent shares Devon's
  uid, so any FS deny is blunt, breaks real workloads, and emits noise to both Devon and
  the agent.
- **Redact, don't deny.** The guard replaces the secret *value* with a sentinel rather
  than failing the tool call. Accidental reads keep flowing (the agent harmlessly skips the
  redacted span); intentional reads get an inline redirect to the runtime path (Keychain /
  BWS). This is the property that makes it non-clunky.
- **Detection = content-shape (primary) + path (amplifier).** Redact wherever a secret
  *shape* appears in tool output — method-agnostic, so `Read`, `cat`, `grep`, `python`, and
  base64-decoded content are all caught because the value must surface to reach the
  transcript. A known secret-file *path* (from `tool_input`) is an amplifier: a read of such
  a path is treated as guilty-until-proven when content can't be scanned.
- **v1 matcher scope: BWS token shape only.** Reuse the repo's *existing* BWS-shape pattern
  — the one the `security_scan` package and `bws-write-guard.sh` already enforce — factored
  into a single shared definition the read-guard imports, so the read side and the existing
  checks cannot drift apart. (The write-guard is bash and this core is Python, so "one source
  of truth" means a shared pattern definition, not shared code; the implementation plan must
  pin down where that canonical pattern lives.) The shape is the `0.`-prefixed, dot-separated
  `0.<uuid>.<base64-ish-secret>` form (described, never instantiated literally — see §8).
  Broader secret sets (AWS keys, PEM blocks, etc.) are deferred.
- **Fail-safe = Option 3** (detection-robust + path tie-break) — see §6.
- **Implementation language: Python 3.12+.** Kills the reconstruction landmine (see §6) via
  the `json` module's correct handling of arbitrary strings, and matches the repo's primary
  language.

## 4. Mechanism (verified)

A `PostToolUse` hook can return `hookSpecificOutput.updatedToolOutput`, which **replaces
the tool result before the model sees it and persists the redacted version into the
transcript** (the original is never stored; `--resume` replays the redacted form). It fires
uniformly for `Read`, `Bash`, and other tools, and carries `additionalContext` — the
channel used for the "fetch from Keychain instead" redirect.

> **Implementation-time validation:** the exact field names (`updatedToolOutput`,
> `additionalContext`, `hookSpecificOutput`, the stdin envelope keys `tool_output` /
> `tool_input` / `tool_name`) come from a docs-research pass, and Claude Code hook schemas
> shift between versions. Confirm them against the *installed* version (layer 5 of the test
> plan) before relying on them. The load-bearing fact — PostToolUse can rewrite output — is
> confirmed.

**Platform constraint we must design around:** the default behavior when a hook crashes or
times out is **fail-open** (the unmodified result proceeds). Fail-closed only happens if the
hook *successfully runs and explicitly emits* the suppressing JSON. Therefore the hook must
be fast, size-bounded, and decisive — it can never rely on "if in doubt, die."

## 5. Architecture (units & boundaries)

Split pure logic from I/O so the hard part is unit-testable with no Claude Code involvement:

- **`core`** — pure, fast, no side effects:
  - `scan_for_bws(output: bytes) -> list[Match]` — raw byte scan for the BWS shape; robust
    on binary/huge input.
  - `redact(output: bytes, matches) -> str` — emit output with each match replaced by the
    sentinel; otherwise byte-faithful.
  - `decide(envelope) -> Decision` — apply the Option-3 matrix using scan results +
    `tool_input` path signal; returns one of `{passthrough, redact, suppress, fail_open}`.
- **`hook`** (entry script wired into settings) — thin: read stdin envelope, call `core`,
  write the stdout JSON contract, append the audit-log line. Holds the time/size budget and
  the platform-contract details.

This isolation is also what makes layers 1–4 of the test plan possible without a live agent.

## 6. Fail-safe: Option 3 (detection-robust + path tie-break)

"Can't cleanly parse" decomposes into two *separable* jobs:
1. **Detection** (is a token present?) — robust; a raw byte scan works even on binary/huge
   output. Rarely fails.
2. **Reconstruction** (re-emit with the token swapped, byte-faithful otherwise) — fragile
   only if done with shell string-interpolation; in Python (`json.dumps`, `surrogateescape`)
   it is reliable.

Because detection is robust, the guard almost always *knows* whether a secret is present,
so fail-closed fires only when it must:

| Detection | Reconstruction | Path is known-secret? | Action |
|---|---|---|---|
| no shape found | — | any | **passthrough** (nothing to leak) |
| shape found | succeeds | any | **redact** (happy path) |
| shape found | fails | any | **suppress that output** + redirect note (fail-closed) |
| cannot scan (envelope corrupt / timeout / size cap) | — | yes | **suppress** + redirect (guilty by path) |
| cannot scan | — | no | **fail-open + audit-log the gap** (rare, low-signal, never silent) |

Property: fail-closed triggers only when a secret is known or strongly suspected present, so
legitimate output is essentially never broken; the only residual fail-open window
(unscannable content *and* no path signal) is logged so it is never silent.

## 7. Redaction UX & audit

- **Inline sentinel** replaces the value, preserving surrounding structure so an accidental
  read still reads sensibly, e.g. `[REDACTED — BWS token withheld from transcript]`.
- **`additionalContext`** carries the redirect: a BWS token was withheld; fetch it at
  runtime from the login Keychain (`security find-generic-password …`) or BWS — do not read
  the file. Points to `~/.claude/CLAUDE.md` "Secure Way of Working".
- **Audit log:** append one line per redaction *and* per fail-open gap to
  `~/.claude/audit/high-power-actions.jsonl` (the existing weekly-review log): timestamp,
  tool_name, the matched path if any, decision, and match count — never the value.

## 8. Fixture / self-block gotcha

Test inputs need BWS-shaped tokens, but a **literal** shape-matching token committed to a
fixture would trip the write-guard on creation, the Stop scan-gate at session end, and CI.
So tests **construct the shape programmatically at runtime** from parts (prefix + generated
UUID + generated blob); no literal token ever sits in a source file. This is the same
constraint the repo documents for its scanner fixtures; here we prefer runtime generation
over the allowlist so no fixture holds a real-looking value.

## 9. Non-goals / known limitations (deliberate)

- **Not machine-wide.** A human or non-Claude process reading a secret is out of scope.
- **Read-and-use-without-printing** (a script that reads a token and uses it without ever
  echoing it) is not redacted — but it also never enters the transcript, so it is outside
  the threat. Codified as expected behavior, not a bug.
- **Transformed-before-print** (token reversed / rot13 / re-encoded before output) is not
  caught. Known limitation, documented.
- **v1 covers only the BWS token shape.** Other secret types are future scope.

## 10. Test strategy (7 layers)

Proves two properties equally: secrets get redacted **and** non-secret output passes through
byte-for-byte.

1. **Unit tests on `core` (pytest)** — full Option-3 matrix: token in `Read` output; token
   in `Bash` stdout via `cat`/`grep`/`echo` and via base64-decoded content; multiple tokens;
   shape-found-but-reconstruction-fails → suppress; unscannable + known path → suppress;
   unscannable + unknown path → fail-open *with* an audit line; malformed envelope → defined
   fail-open + log.
2. **Passthrough-fidelity** — battery of non-secret outputs that break naive hooks (embedded
   quotes, newlines, backslashes, unicode, control chars, NUL/binary, 10 MB blobs); assert
   output is byte-identical to input.
3. **Matcher precision corpus** — reuse the write-guard matcher; true-positives vs
   look-alikes that must NOT trip (bare UUIDs, semver like `0.1.2`, git hashes, generic
   base64).
4. **Performance/budget** — 10 MB output completes under the time budget; size-cap behavior
   matches Option 3. Measured and asserted.
5. **Live wiring (end-to-end)** — headless `claude -p` (or documented manual) session with
   the hook installed: read a runtime-generated fixture, assert the model-visible output and
   the persisted transcript show `[REDACTED]` not the token; confirm `--resume` replays the
   redacted version. Also validates the exact field names against the installed version.
6. **Adversarial / known-limits** — assert and document the §9 boundaries (read-and-use,
   transformed-before-print).
7. **CI** — layers 1–4 + 6 run in the existing `.github/workflows/security-scan.yml`; layer
   5 is a manual/gated step (needs the Claude Code binary).

## 11. Definition of done

- `core` + `hook` implemented in Python with the §5 boundaries.
- Wired as a `PostToolUse` hook on `Read` + `Bash`; field names validated against the
  installed Claude Code version.
- Option-3 fail-safe behavior implemented, with time/size budget and audit logging.
- All 7 test layers green (layer 5 documented if run manually).
- BWS-token-only matcher shared with the write-guard.
- README / `security-defense-layers` memory updated to record the read side of PREVENT.
