from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Tool:
    name: str
    lane: str
    home_repo: str
    source: str
    artifact_class: str  # "source" | "deployed" | "runtime" | "hosted"
    deploy_target: str = ""
    mode: str = "755"


@dataclass
class Repo:
    name: str
    path: str
    cls: str  # "tool-home" | "consumer" | "host"
    lane: str = ""
    owns: list[str] = field(default_factory=list)
    consumers: list[str] = field(default_factory=list)
    uses_bws: bool = False
    remote: str = ""  # git remote URL (for the control-plane host repo)


@dataclass
class RuntimeDir:
    path: str
    note: str = ""


@dataclass
class Manifest:
    tools: list[Tool]
    repos: list[Repo]
    runtime_dirs: list[RuntimeDir]


def load_map(path: str | Path) -> Manifest:
    data = tomllib.loads(Path(path).read_text())
    tools = [Tool(**t) for t in data.get("tool", [])]
    repos = [
        Repo(
            name=r["name"],
            path=r["path"],
            cls=r["class"],
            lane=r.get("lane", ""),
            owns=r.get("owns", []),
            consumers=r.get("consumers", []),
            uses_bws=r.get("uses_bws", False),
            remote=r.get("remote", ""),
        )
        for r in data.get("repo", [])
    ]
    rdirs = [RuntimeDir(**d) for d in data.get("runtime_dir", [])]
    return Manifest(tools=tools, repos=repos, runtime_dirs=rdirs)
