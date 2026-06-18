#!/usr/bin/env bash
# PreToolUse read-guard (Read tool): opens the target file, scans it for a BWS
# token, and DENIES the read (with a Keychain redirect) before it executes, so
# the token never enters the transcript. Fail-open on any uncertainty.
# Pure logic lives in the security_scan package.
# Design: ~/Projects/security-standards/docs/superpowers/specs/2026-06-17-bws-read-guard-pretooluse-design.md
#
# Interpreter pin: the security_scan package targets Python >=3.12. The ambient
# `python3` under macOS launchd resolves to system Python 3.9, which silently
# broke the guard (fail-open) once before. Pin to a known >=3.12 interpreter so
# execution matches the package's supported floor regardless of PATH. Fall back
# to ambient `python3` only as a last resort (the package is import-safe to 3.9).
PYBIN=""
for cand in \
    /opt/homebrew/bin/python3.13 \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/opt/python@3.12/libexec/bin/python3; do
    [ -x "$cand" ] && PYBIN="$cand" && break
done
[ -n "$PYBIN" ] || PYBIN="python3"

exec /usr/bin/env PYTHONPATH="$HOME/Projects/security-standards/src" \
    "$PYBIN" -m security_scan.read_guard.hook
