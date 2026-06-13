import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Hit:
    file: str
    line: int
    match: str


def _git(repo_path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo_path,
                          capture_output=True, text=True, timeout=30)


def is_git_repo(repo_path) -> bool:
    """True only if repo_path is inside a usable git work tree.
    The scan relies entirely on git; if this is False the scan must fail closed."""
    res = _git(repo_path, "rev-parse", "--is-inside-work-tree")
    return res.returncode == 0 and res.stdout.strip() == "true"


def tracked_files(repo_path) -> list[str]:
    out = _git(repo_path, "ls-files").stdout
    return [p for p in out.splitlines() if p]


def grep_tracked(repo_path, pattern: str) -> list[Hit]:
    """Regex search across git-tracked files in the working tree."""
    repo_path = Path(repo_path)
    rx = re.compile(pattern)
    hits: list[Hit] = []
    for rel in tracked_files(repo_path):
        try:
            text = (repo_path / rel).read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            m = rx.search(line)
            if m:
                hits.append(Hit(file=rel, line=i, match=m.group(0)))
    return hits


def grep_history(repo_path, pattern: str) -> list[str]:
    """Commit SHAs whose diff added or removed a line matching the pattern.
    Uses `git log --all -G<pattern>`. Returns full SHAs (newest first); empty if none."""
    res = _git(repo_path, "log", "--all", "-G", pattern, "--format=%H")
    return [s for s in res.stdout.splitlines() if s]


def is_ignored(repo_path, path: str) -> bool:
    """True if `path` is covered by .gitignore (git check-ignore exits 0)."""
    res = _git(repo_path, "check-ignore", "-q", path)
    return res.returncode == 0
