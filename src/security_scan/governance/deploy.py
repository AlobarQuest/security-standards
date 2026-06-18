from __future__ import annotations

import os
import shutil
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
