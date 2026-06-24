#!/bin/bash
###############################################################################
# security-scan.sh — Phase 5 read-only drift detector
# Re-checks the core exposures from the 2026-06 machine security audit.
# READ-ONLY: never changes anything. Exit 0 = clean, 1 = drift (FAILs found).
# Findings also appended to ~/.claude/audit/security-scan-<date>.log
#
# NOTE: a large FAIL baseline is EXPECTED until the audit cutover is applied.
###############################################################################
# Source of truth: ~/Projects/security-standards/scripts/security-scan.sh (deployed → ~/.claude/bin/security-scan.sh)
# Edit here, not in place; then: cd ~/Projects/security-standards && make install
# OUTPUT CONTRACT (consumed by infraops src/security-drift/scan-parser.ts):
#   One finding per line:  printf '%-4s %-32s %s\n'  SEV  CHECK  detail
#     SEV     in {FAIL,WARN,PASS}
#     CHECK   dotted key, no spaces (e.g. credfile.over_permissive)
#     detail  free text; the path-bearing forms the parser keys on are:
#               "<path> (mode NNN) ..."  |  "<file>: <rest>"  |  leading "<path>"
#   Non-matching lines (the banner, "=== summary ===") are ignored by the parser.
# Bump SCANNER_OUTPUT_VERSION whenever the line shape OR a detail form above
# changes, so the infraops parser fails LOUD on skew instead of silently parsing
# zero findings at 3am. The infraops side reads this marker from the deployed file.
# SCANNER_OUTPUT_VERSION=1
###############################################################################
set -uo pipefail   # deliberately NOT -e: run every check, don't abort early

# launchd hands cron-style jobs a minimal PATH that omits ~/.cargo/bin (where rtk
# lives) and the Homebrew dirs, so tool-presence checks (rtk, jq, lsof) can
# false-FAIL even when the tool is installed (see supply.rtk_missing). Normalize
# PATH up front so detection never depends on which launchd job invoked us.
# (Mirrors the read-guard interpreter pin: don't trust the ambient PATH for
# resolving our own dependencies.)
export PATH="$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# Pin a Python >= 3.11 for our own module subprocesses (read-guard self-check,
# governance verify). `tomllib` — used by security_scan.governance/manifest/allowlist
# — is stdlib only on 3.11+, but a launchd/autonomous PATH can resolve bare `python3`
# to Apple's /usr/bin 3.9 (no tomllib): the module then crashes at import and its
# traceback surfaces as a false "drift" finding. The .venv path is absolute, so it
# holds even under a hostile PATH. Don't trust ambient `python3`.
PY=""
for _cand in "$HOME/Projects/security-standards/.venv/bin/python" python3.12 python3.11 python3; do
  if command -v "$_cand" >/dev/null 2>&1 \
     && "$_cand" -c 'import sys, tomllib; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$(command -v "$_cand")"; break
  fi
done

TS="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
AUDIT_DIR="${HOME}/.claude/audit"
LOG="${AUDIT_DIR}/security-scan-$(date -u '+%Y%m%d').log"
mkdir -p "$AUDIT_DIR"

FAIL=0; WARN=0; PASS=0

emit() { # severity check detail
  local sev="$1" check="$2" detail="$3"
  case "$sev" in
    FAIL) FAIL=$((FAIL+1));;
    WARN) WARN=$((WARN+1));;
    PASS) PASS=$((PASS+1));;
  esac
  printf '%-4s %-32s %s\n' "$sev" "$check" "$detail" | tee -a "$LOG"
}

have() { command -v "$1" >/dev/null 2>&1; }

# group/other bits set?  arg = path; echoes "yes"/"no"
go_readable() {
  local p="$1" mode
  mode="$(stat -f '%Lp' "$p" 2>/dev/null || echo 000)"
  if [ $(( 8#$mode & 8#077 )) -ne 0 ]; then echo yes; else echo no; fi
}

# is this an actual PEM private key (not a CA bundle / Keynote / public cert)?
is_private_key() {
  head -c 400 "$1" 2>/dev/null | grep -q -- '-----BEGIN \(RSA \|EC \|OPENSSH \|DSA \|PGP \)\?PRIVATE KEY-----'
}

echo "=== security-scan $TS ===" | tee "$LOG"

# ---------------------------------------------------------------------------
# 1. Plaintext secrets exported in shell config (inline value, not Keychain)
# ---------------------------------------------------------------------------
for f in "$HOME/.zshrc" "$HOME/.zshenv"; do
  [ -f "$f" ] || continue
  # export NAME=<starts with quote+alnum or alnum> ; exclude $(...) keychain lookups
  while IFS= read -r line; do
    # emit the KEY NAME ONLY — never the value (the detector must not log secrets)
    key="$(printf '%s' "$line" | sed -E 's/.*export[[:space:]]+([A-Za-z_]+)=.*/\1/')"
    emit FAIL "shell.plaintext_secret" "$f: $key=<inline value> (move to Keychain)"
  done < <(grep -E '^[[:space:]]*export[[:space:]]+[A-Za-z_]*(API_KEY|TOKEN|SECRET|PASSWORD)=["'"'"']?[A-Za-z0-9]' "$f" 2>/dev/null | grep -v '\$(' || true)
done

# ---------------------------------------------------------------------------
# 2. Secret/cred files readable by group/other
# ---------------------------------------------------------------------------
for root in "$HOME/Projects" "$HOME/Developer"; do
  [ -d "$root" ] || continue
  while IFS= read -r p; do
    [ -f "$p" ] || continue
    [ "$(go_readable "$p")" = yes ] || continue
    case "$p" in
      *.pem|*.key)
        # only real private keys (skip CA bundles like cacert.pem, Keynote .key, public certs)
        is_private_key "$p" && emit FAIL "credfile.private_key" "$p (mode $(stat -f '%Lp' "$p")) group/other-readable private key" ;;
      *)
        emit FAIL "credfile.over_permissive" "$p (mode $(stat -f '%Lp' "$p")) group/other-readable" ;;
    esac
  done < <(find "$root" -type d \( -name .venv -o -name venv -o -name node_modules -o -name site-packages -o -name .git -o -name .worktrees -o -name .n8n-cache \) -prune -o \
                 -type f \( -name '.env' -o -name '.env.local' -o -name 'credentials.json' -o -name 'token.json' -o -name '*.pem' -o -name '*.key' \) -print 2>/dev/null)
done

# ---------------------------------------------------------------------------
# 3. Inlined secrets in MCP configs
# ---------------------------------------------------------------------------
if have jq; then
  for f in "$HOME/.claude/.mcp.json" "$HOME/Library/Application Support/Claude/claude_desktop_config.json"; do
    [ -f "$f" ] || continue
    keys="$(jq -r '[.. | objects | to_entries[] | select(.key|test("(API_KEY|ACCESS_TOKEN|_TOKEN|PASSWORD|SECRET)$";"i")) | select(.value|type=="string" and .!="" and (startswith("$")|not)) | .key] | unique[]?' "$f" 2>/dev/null || true)"
    while IFS= read -r k; do
      [ -n "$k" ] && emit FAIL "mcp.inlined_secret" "$(basename "$f"): $k has inline value (should be Keychain-fetched/absent)"
    done <<< "$keys"
  done
else
  emit WARN "mcp.inlined_secret" "jq missing; skipped"
fi

# ---------------------------------------------------------------------------
# 4. settings.json permission regressions
# ---------------------------------------------------------------------------
S="$HOME/.claude/settings.json"
if have jq && [ -f "$S" ]; then
  jq -e '.permissions.allow[]? | select(.=="Write(*)")'      "$S" >/dev/null 2>&1 && emit FAIL settings.write_wildcard      "Write(*) present (use explicit paths)"
  jq -e '.permissions.allow[]? | select(.=="mcp__infraops")' "$S" >/dev/null 2>&1 && emit FAIL settings.infraops_wildcard   "mcp__infraops wildcard (use explicit read-only list)"
  jq -e '.permissions.allow[]? | select(test("^Update\\("))' "$S" >/dev/null 2>&1 && emit FAIL settings.update_wildcard     "Update(*) present"
  # skipDangerous=true is the chosen low-friction policy (2026-06-15): zero approval prompts,
  # acceptable ONLY with the bypass-surviving guardrails present — catastrophic permissions.deny
  # rules + the audit-log hook. (Hook denies are NOT guaranteed in bypass; deny rules ARE.)
  v="$(jq -r '.skipDangerousModePermissionPrompt // false' "$S" 2>/dev/null)"
  if [ "$v" = "true" ]; then
    deny_n="$(jq -r '[.permissions.deny[]? | select(test("rm -rf|sudo |dd of=|mkfs"))] | length' "$S" 2>/dev/null)"
    audit_n="$(jq -r '[.hooks.PostToolUse[]?.hooks[]?.command | select(test("high-power-audit"))] | length' "$S" 2>/dev/null)"
    if [ "${deny_n:-0}" -ge 1 ] && [ "${audit_n:-0}" -ge 1 ]; then
      emit PASS settings.skip_dangerous_prompt "bypass mode OK (catastrophic deny rules + audit log present)"
    else
      emit FAIL settings.skip_dangerous_prompt "skipDangerous=true WITHOUT guardrails (need permissions.deny catastrophic + audit-log hook)"
    fi
  fi
else
  emit WARN settings.checks "jq or settings.json missing; skipped"
fi

# ---------------------------------------------------------------------------
# 5. Sensitive listeners bound to 0.0.0.0
# ---------------------------------------------------------------------------
if have lsof; then
  for port in 6379 5433 6001 6002 8000 8766 9876; do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | grep -q '0\.0\.0\.0:'; then
      emit FAIL listener.lan_exposed "port $port bound to 0.0.0.0 (want 127.0.0.1)"
    fi
  done
else
  emit WARN listener.checks "lsof missing; skipped"
fi

# ---------------------------------------------------------------------------
# 6. High-power approval gate hook present + registered
# ---------------------------------------------------------------------------
GATE="$HOME/.claude/hooks/high-power-gate.sh"
if [ -f "$GATE" ]; then
  if have jq && jq -e '.. | strings | select(contains("high-power-gate"))' "$S" >/dev/null 2>&1; then
    emit PASS hooks.gate "high-power-gate.sh present and registered"
  else
    emit FAIL hooks.gate_unregistered "gate script exists but not registered in settings.json"
  fi
else
  emit FAIL hooks.gate_missing "high-power-gate.sh not installed (PreToolUse defense)"
fi

# ---------------------------------------------------------------------------
# 7. Supply-chain pins
# ---------------------------------------------------------------------------
have rtk && emit PASS supply.rtk "rtk present ($(rtk --version 2>/dev/null | head -1))" || emit FAIL supply.rtk_missing "rtk not on PATH"
OCTO="$HOME/Developer/devon-plugins/octo"
INSTALLED="$HOME/.claude/plugins/installed_plugins.json"
if [ -d "$OCTO/.git" ]; then
  cur="$(git -C "$OCTO" rev-parse HEAD 2>/dev/null || echo unknown)"
  # Pin = the commit Claude Code actually installed (gitCommitSha), read live — not a
  # frozen literal. It moves automatically on `claude plugin update`, so a legitimate
  # octo bump self-clears, and the check now catches the real failure mode: the clone
  # was pulled but the install was never refreshed (or vice-versa). Fail-closed: an
  # unreadable baseline WARNs, never silently PASSes.
  pin="$(have jq && jq -r '.plugins["octo@devon-plugins"][0].gitCommitSha // ""' "$INSTALLED" 2>/dev/null || echo "")"
  if [ -z "$pin" ]; then
    emit WARN supply.octo_pin "octo install pin unreadable (jq or $INSTALLED missing)"
  elif [ "$cur" = "$pin" ]; then
    emit PASS supply.octo_pin "octo clone HEAD == installed ${pin:0:12}"
  else
    emit WARN supply.octo_drift "octo clone ${cur:0:12} != installed ${pin:0:12} (run: claude plugin update octo@devon-plugins)"
  fi
fi

# ---------------------------------------------------------------------------
# 8. OS hardening toggles
# ---------------------------------------------------------------------------
ap="$(defaults read com.apple.screensaver askForPassword 2>/dev/null || echo 0)"
[ "$ap" = "1" ] && emit PASS os.screen_lock "askForPassword on" || emit FAIL os.screen_lock "screen lock off (askForPassword=$ap)"
cu="$(defaults read /Library/Preferences/com.apple.SoftwareUpdate CriticalUpdateInstall 2>/dev/null || echo 0)"
[ "$cu" = "1" ] && emit PASS os.critical_updates "critical updates on" || emit FAIL os.critical_updates "critical updates off"
if have spctl; then spctl --status 2>/dev/null | grep -q 'assessments enabled' && emit PASS os.gatekeeper "Gatekeeper on" || emit FAIL os.gatekeeper "Gatekeeper off"; fi

# ---------------------------------------------------------------------------
# 9. World-writable backup keys (stale iMac dir)
# ---------------------------------------------------------------------------
BK="$HOME/from iMac/downloads"
if [ -d "$BK" ]; then
  while IFS= read -r p; do
    is_private_key "$p" || continue   # skip Keynote .key files etc.
    m="$(stat -f '%Lp' "$p" 2>/dev/null || echo 000)"
    [ $(( 8#$m & 8#022 )) -ne 0 ] && emit FAIL backupkey.world_writable "$p (mode $m)"
  done < <(find "$BK" \( -name '*.pem' -o -name '*.key' \) -type f 2>/dev/null)
fi

# ---------------------------------------------------------------------------
# 10. TikTok scraper plist plaintext password (ledger item 32)
# ---------------------------------------------------------------------------
TP="$HOME/Library/LaunchAgents/com.facelesstt.tiktok-scraper.plist"
if [ -f "$TP" ] && grep -qiE 'password|postgresql://[^@]+:[^@]+@' "$TP" 2>/dev/null; then
  emit FAIL tiktok.plaintext_password "$TP contains an inline DB password/URL (move to env/Keychain)"
fi

# ---------------------------------------------------------------------------
# 11. Plaintext BWS tokens in non-repo locations (content-based)
#     The security-standards repo scanner greps the token shape inside git repos;
#     this covers the machine locations repos don't (~/.config, LaunchAgents),
#     where a per-workload env file or plist can hold a live token. CONTENT-based:
#     uses `grep -l` so it reports the PATH only and never logs the value.
#     NOTE: still an enumerated path list and a periodic *detector* — it backstops
#     prevention (Keychain + read-guard), it does not replace it.
# ---------------------------------------------------------------------------
BWS_TOKEN_RX='0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}|BWS_ACCESS_TOKEN[[:space:]]*[=:][[:space:]]*["'"'"']?0\.'
scan_paths=()
[ -d "$HOME/.config" ] && scan_paths+=("$HOME/.config")
[ -d "$HOME/Library/LaunchAgents" ] && scan_paths+=("$HOME/Library/LaunchAgents")
if [ "${#scan_paths[@]}" -gt 0 ]; then
  while IFS= read -r hit; do
    [ -n "$hit" ] && emit FAIL secret.bws_token_plaintext \
      "$hit holds a plaintext BWS token (move to Keychain; if it was exposed, ROTATE it)"
  done < <(grep -rlIE "$BWS_TOKEN_RX" "${scan_paths[@]}" 2>/dev/null || true)
fi

# ---------------------------------------------------------------------------
# 12. read-guard health (presence + functional canary)
#     The PreToolUse read-guard's wiring is machine-local config and FAILS OPEN,
#     so a broken/missing guard removes protection silently. This runs the
#     versioned self-check (presence + an end-to-end canary through the real shim,
#     which catches functional breakage the presence check can't — e.g. the
#     security-standards repo on a branch without the package). A FAIL means the
#     read-guard is not protecting reads right now.
# ---------------------------------------------------------------------------
if [ -z "$PY" ]; then
  emit WARN readguard.health "no python>=3.11 interpreter found; self-check skipped"
elif RG_OUT="$(PYTHONPATH="$HOME/Projects/security-standards/src" "$PY" -m security_scan.read_guard.selfcheck --canary 2>&1)"; then
  emit PASS readguard.health "read-guard wired + canary ok"
else
  emit FAIL readguard.health "read-guard self-check FAILED: $(printf '%s' "$RG_OUT" | tr '\n' ';' | tr -s ' ')"
fi

# ---------------------------------------------------------------------------
# 13. Claude control-plane git drift (~/.claude tamper-evidence)
#     ~/.claude is a git repo tracking the control-plane set (hooks, settings,
#     .mcp.json, CLAUDE.md, RTK.md). An uncommitted/untracked change to the
#     CRITICAL set => FAIL (deny-by-default URGENT escalation). settings.local.json
#     is expected churn => WARN controlplane.local_churn, dropped by taxonomy
#     (logged, never escalated). READ-ONLY: never commits.
# ---------------------------------------------------------------------------
CP="$HOME/.claude"
if have git && [ -d "$CP/.git" ]; then
  crit="$(git -C "$CP" status --porcelain -- .gitignore settings.json .mcp.json CLAUDE.md RTK.md hooks/ statusline-command.sh 2>/dev/null)"
  if [ -n "$crit" ]; then
    while IFS= read -r l; do
      [ -n "$l" ] && emit FAIL controlplane.drift "uncommitted/untracked control-plane change: ${l} (review + commit if intended)"
    done <<< "$crit"
  else
    emit PASS controlplane.clean "control-plane critical set matches HEAD"
  fi
  if [ -n "$(git -C "$CP" status --porcelain -- settings.local.json 2>/dev/null)" ]; then
    emit WARN controlplane.local_churn "settings.local.json changed since last commit (expected churn)"
  fi
else
  emit FAIL controlplane.unmanaged "$CP is not a git repo — control-plane tamper-evidence inactive (run: git -C $CP init)"
fi

# ---------------------------------------------------------------------------
# 14. Deployed artifacts in sync with home repos (governance-map)
# ---------------------------------------------------------------------------
# ── Check: deployed artifacts match their home repos (governance-map) ──
SECSTD="$HOME/Projects/security-standards"
if [ -f "$SECSTD/governance-map.toml" ] && [ -n "$PY" ]; then
  if gv_out="$(cd "$SECSTD" && PYTHONPATH=src "$PY" -m security_scan.governance verify --artifacts-only 2>&1)"; then
    emit PASS governance.artifacts_in_sync "deployed artifacts match home repos"
  else
    emit FAIL governance.artifacts_in_sync "$(printf '%s' "$gv_out" | tr '\n' ';')"
  fi
elif [ -f "$SECSTD/governance-map.toml" ]; then
  emit WARN governance.artifacts_in_sync "no python>=3.11 interpreter found; check skipped"
fi
# ---------------------------------------------------------------------------
echo "=== summary: PASS=$PASS WARN=$WARN FAIL=$FAIL ===" | tee -a "$LOG"
[ "$FAIL" -gt 0 ] && { echo "DRIFT DETECTED ($FAIL fail)"; exit 1; }
exit 0
