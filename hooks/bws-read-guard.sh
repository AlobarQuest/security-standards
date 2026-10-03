#!/usr/bin/env bash
# PreToolUse read-guard (Read tool): opens the target file, scans it for a BWS
# token, and DENIES the read (with a Keychain redirect) before it executes, so
# the token never enters the transcript. Fail-open on any uncertainty.
# Pure logic lives in the security_scan package.
# Design: ~/Projects/security-standards/docs/superpowers/specs/2026-06-17-bws-read-guard-pretooluse-design.md
#
# Interpreter pin: the security_scan package requires Python >=3.14. The ambient
# `python3` under macOS launchd resolves to system Python 3.9, which silently
# broke the guard (fail-open) once before. Pin to a 3.14 interpreter so execution
# matches the package's floor regardless of PATH; the uv path is absolute because
# launchd's PATH has no ~/.local/bin. Ambient `python3` is the last resort, and on
# anything older than 3.14 the guard fails open.
# Source of truth: ~/Projects/security-standards/hooks/bws-read-guard.sh (deployed → ~/.claude/hooks/bws-read-guard.sh)
# Edit here, not in place; then: cd ~/Projects/security-standards && make install
PYBIN=""
for cand in \
    "$HOME/.local/share/uv/python/cpython-3.14-macos-aarch64-none/bin/python3.14" \
    /opt/homebrew/bin/python3.14; do
    [ -x "$cand" ] && PYBIN="$cand" && break
done
[ -n "$PYBIN" ] || PYBIN="python3"

exec /usr/bin/env PYTHONPATH="$HOME/Projects/security-standards/src" \
    "$PYBIN" -m security_scan.read_guard.hook
