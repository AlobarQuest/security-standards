#!/usr/bin/env bash
# activate-checkout.sh — bring a working copy up to date before the job that reads it runs.
#
# Source of truth: ~/Projects/security-standards/scripts/activate-checkout.sh
# Deployed to:     ~/.claude/bin/activate-checkout.sh  (governance-map.toml, `make install`)
# Edit here, not in place; then: cd ~/Projects/security-standards && make install
#
# WHY THIS EXISTS. The estate's Dependabot cascade (ADR-0016/0018/0023) arms auto-merge and stops
# at the merge. That is complete for a repository whose landing redeploys a hosted application and
# incomplete for one whose code runs from a working copy on this machine: the merge changes nothing
# until someone pulls. Measured 2026-08-21 — `security-standards` #41 and `project-standards` #26
# were merged by `github-actions[bot]` and both checkouts were a commit behind, while the Stop hook
# and two scheduled scans were executing from them. GitHub has no inbound path to this machine, so
# the trigger has to be local, and the honest place for it is the consumer: a periodic job pulls
# what it reads, immediately before reading it. Activation and execution become one event.
#
# ONE COPY, SOURCED CROSS-REPO. Callers live in six repositories. A copy per repository is six
# copies of one rule, which is where this estate's drift reliably lives — `observe-run.sh` already
# has two copies and that is the cautionary tale, not the pattern. A second copy of THIS file is a
# defect, not a convenience.
#
# IT NEVER FAILS ITS CALLER, and that is the decision rather than an oversight. Activation is
# best-effort; the job is not gated on it. A backup that refuses to run because a tree is dirty is
# worse than a backup running slightly old code, and a scan that refuses is worse than a stale scan.
# So every path returns 0 and every path prints exactly one `[activation]` line saying what
# happened. The line is the whole signal — read the log, not the exit code.
#
# TWO CONDITIONS, DELIBERATELY NAMED DIFFERENTLY. A checkout on a branch other than `main` is a
# build session working in the main tree; that is ordinary here and the correct response is to run
# what is there and say so. A checkout on `main` that cannot fast-forward is anomalous, and its line
# says HELD so it reads differently in a log. Neither stops the job; ADR-0030's sweep is what turns
# a persistent one into a finding.
#
# IT RE-EXECS THE CALLER WHEN HEAD MOVES, and this is a correctness requirement rather than
# thoroughness. Every caller's own file lives inside the checkout it activates, and bash reads a
# script incrementally by byte offset — rewriting the file underneath a running shell can garble
# everything after the current read position. Re-execing also makes the run that pulled the change
# the run that uses it, which is what "activated" should mean. `SDS_ACTIVATION_REEXEC` guards
# against a loop; a second pass finds the checkout current and re-execs nothing.
#
# Usage, as the first statement of a scheduled launcher:
#   ACTIVATE="$HOME/.claude/bin/activate-checkout.sh"
#   if [ -r "$ACTIVATE" ]; then . "$ACTIVATE"; else
#     activate_checkout() { echo "[activation] helper missing — this run is not activated"; }
#   fi
#   activate_checkout "$REPO_ROOT" "$0" "$@"
#
# The second and later arguments are optional: pass them to get the re-exec, omit them to activate
# a checkout the caller reads but does not live in.

# shellcheck shell=bash

activate_checkout() {
    local root="${1:-}"
    local self="${2:-}"
    if [ $# -ge 1 ]; then shift; fi
    if [ $# -ge 1 ]; then shift; fi
    local label="${root/#$HOME/~}"

    if [ -z "$root" ] || ! git -C "$root" rev-parse --git-dir >/dev/null 2>&1; then
        echo "[activation] $label is not a git checkout — nothing to activate"
        return 0
    fi

    local branch
    branch="$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
    if [ "$branch" != "main" ]; then
        echo "[activation] $label is on '$branch', not main — running what is there"
        return 0
    fi

    if ! git -C "$root" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
        echo "[activation] $label has no upstream — running what is there"
        return 0
    fi

    local before
    before="$(git -C "$root" rev-parse --short HEAD 2>/dev/null || echo unknown)"

    # Plain `git fetch origin`, not `git fetch origin main`: the configured refspec is what
    # reliably advances the remote-tracking ref the comparison below reads.
    if ! git -C "$root" fetch --quiet origin >/dev/null 2>&1; then
        echo "[activation] $label could not reach origin — running $before"
        return 0
    fi

    local behind
    behind="$(git -C "$root" rev-list --count 'HEAD..@{u}' 2>/dev/null || echo 0)"
    if [ "$behind" = "0" ]; then
        echo "[activation] $label is current at $before"
        return 0
    fi

    if ! git -C "$root" merge --ff-only --quiet '@{u}' >/dev/null 2>&1; then
        echo "[activation] $label HELD: $behind commit(s) behind and cannot fast-forward — running $before"
        return 0
    fi

    local after
    after="$(git -C "$root" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo "[activation] $label activated $before..$after ($behind commit(s))"

    _activate_sync_dependencies "$root" "$label" "$before" "$after"
    _activate_reexec "$label" "$self" "$@"
    return 0
}

# A pull alone does not install a newly declared console script, and every caller invokes its
# program by absolute path inside `.venv/bin` — so the failure of skipping this is a missing binary,
# not an import error. Keyed on the manifest actually moving: `uv sync` on every pull would be cost
# for nothing, and a pull that touches neither file cannot have changed what is installed.
_activate_sync_dependencies() {
    local root="$1" label="$2" before="$3" after="$4"

    [ -d "$root/.venv" ] || return 0
    command -v uv >/dev/null 2>&1 || return 0
    git -C "$root" diff --name-only "$before" "$after" 2>/dev/null \
        | grep -qE '(^|/)(pyproject\.toml|uv\.lock)$' || return 0

    if ( cd "$root" && uv sync --frozen >/dev/null 2>&1 ); then
        echo "[activation] $label dependencies synced"
    else
        # Loud on purpose. Most launchers still fold their exit codes in a way that can read a
        # missing binary as success, so this line is the only signal that the next invocation may
        # not find the program it is about to run by absolute path.
        echo "[activation] $label SYNC FAILED — 'uv sync --frozen' did not succeed; the next" \
             "program invoked from .venv/bin may be missing or stale" >&2
    fi
}

_activate_reexec() {
    local label="$1" self="$2"
    shift 2

    # `[ -r "" ]` is false, so this one test covers both "no self-path was passed" (a caller
    # activating a checkout it only reads) and "the path is unreadable". An additional -n check
    # was here and was removed: mutation testing found nothing could tell it apart from this line.
    [ -r "$self" ] || return 0
    [ -z "${SDS_ACTIVATION_REEXEC:-}" ] || return 0

    echo "[activation] $label re-running $(basename "$self") on the code just activated"
    export SDS_ACTIVATION_REEXEC=1
    exec /bin/bash "$self" "$@"
}
