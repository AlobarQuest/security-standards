from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .loader import Manifest, Tool


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def _source_path(tool: Tool, manifest: Manifest) -> Path:
    for r in manifest.repos:
        if r.name == tool.home_repo:
            return _expand(r.path) / tool.source
    raise KeyError(f"home_repo {tool.home_repo!r} for tool {tool.name!r} not in manifest")


def deploy_artifacts(manifest: Manifest) -> list[tuple[str, str]]:
    actions: list[tuple[str, str]] = []
    for t in manifest.tools:
        if t.artifact_class != "deployed":
            continue
        src = _source_path(t, manifest)
        dst = _expand(t.deploy_target)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        os.chmod(dst, int(t.mode, 8))
        actions.append((t.name, "deployed"))
    return actions


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _toplevel(path: Path) -> Path | None:
    """The git work-tree root containing `path`, or None if it is not in a repo."""
    base = path if path.is_dir() else path.parent
    r = _git(base, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        return None
    return Path(r.stdout.strip())


def _repo_head(manifest: Manifest, repo_name: str) -> str:
    for r in manifest.repos:
        if r.name == repo_name:
            h = _git(_expand(r.path), "rev-parse", "--short", "HEAD")
            if h.returncode == 0:
                return f"{repo_name}@{h.stdout.strip()}"
    return repo_name


def reconcile_control_plane(manifest: Manifest) -> list[tuple[str, str]]:
    """Commit freshly-deployed artifacts that live inside a git work-tree (the
    ``~/.claude`` control-plane repo) so a legitimate ``make install`` is *silent*
    to the Check-13 tamper-evidence scan and only out-of-band changes alert.

    Discipline that keeps the tamper-evidence meaningful:
      * stage ONLY the exact deployed paths (never ``git add -A``) — unrelated
        working-tree changes stay flagged as drift;
      * skip gitignored targets (e.g. ``~/.claude/bin/``, outside the tracked set);
      * commit only when those paths actually changed (idempotent);
      * silent no-op when a target is not inside a git repo.
    """
    by_root: dict[Path, list[Path]] = {}
    home_repos: dict[Path, set[str]] = {}
    for t in manifest.tools:
        if t.artifact_class != "deployed":
            continue
        dst = _expand(t.deploy_target)
        if not dst.exists():
            continue
        root = _toplevel(dst)
        if root is None:
            continue
        by_root.setdefault(root, []).append(dst)
        home_repos.setdefault(root, set()).add(t.home_repo)

    actions: list[tuple[str, str]] = []
    for root, targets in by_root.items():
        rels = [
            str(dst.relative_to(root))
            for dst in targets
            if _git(root, "check-ignore", "-q", str(dst.relative_to(root))).returncode != 0
        ]
        if not rels:
            continue
        _git(root, "add", "--", *rels)
        # commit ONLY the paths that actually changed, so the message and the
        # commit scope are precise (a deploy that re-copies identical files is a
        # no-op, not a churn commit).
        changed = sorted(
            r for r in rels if _git(root, "diff", "--cached", "--quiet", "--", r).returncode != 0
        )
        if not changed:
            actions.append((str(root), "control-plane already in sync"))
            continue
        srcs = ", ".join(sorted(_repo_head(manifest, n) for n in home_repos[root]))
        msg = (
            "chore(control-plane): reconcile make install deploy\n\n"
            "Auto-committed by security-standards `make install` so a legitimate "
            "deploy is silent to the Check-13 control-plane tamper-evidence scan; "
            "out-of-band changes to these files still surface as drift.\n\n"
            f"Reconciled: {', '.join(changed)}\n"
            f"Source: {srcs}\n"
        )
        c = _git(root, "commit", "-m", msg, "--", *changed)
        if c.returncode == 0:
            actions.append((str(root), f"control-plane committed: {', '.join(changed)}"))
        else:
            actions.append((str(root), f"control-plane commit FAILED: {c.stderr.strip()}"))
    return actions


def verify_artifacts(manifest: Manifest) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    for t in manifest.tools:
        if t.artifact_class != "deployed":
            continue
        src = _source_path(t, manifest)
        dst = _expand(t.deploy_target)
        if not dst.exists():
            problems.append((t.name, "missing"))
        elif src.read_bytes() != dst.read_bytes():
            problems.append((t.name, "drift"))
    return problems
