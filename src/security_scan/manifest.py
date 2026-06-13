import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from security_scan import repo

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_UUID_RX = re.compile(_UUID)
# A UUID "referenced as a BWS secret" = a UUID on a line mentioning bws / a secret-id var.
_BWS_LINE_RX = re.compile(r"(?i)(bws\s+secret|fetch_bws_secret|BWS_\w*SECRET_ID|BWS_ACCESS)")

MANIFEST = ".bws-secrets.toml"


def referenced_uuids(repo_path) -> set[str]:
    repo_path = Path(repo_path)
    found: set[str] = set()
    for rel in repo.tracked_files(repo_path):
        if rel == MANIFEST:
            continue
        try:
            text = (repo_path / rel).read_text(errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if _BWS_LINE_RX.search(line):
                found.update(_UUID_RX.findall(line))
    return found


def declared_uuids(repo_path) -> set[str]:
    p = Path(repo_path) / MANIFEST
    if not p.exists():
        return set()
    data = tomllib.loads(p.read_text())
    return {s["uuid"] for s in data.get("secret", []) if "uuid" in s}


@dataclass
class ManifestDiff:
    manifest_exists: bool
    undeclared: set[str]   # referenced in code, not in manifest
    stale: set[str]        # in manifest, not referenced


def diff(repo_path) -> ManifestDiff:
    refd = referenced_uuids(repo_path)
    decl = declared_uuids(repo_path)
    exists = (Path(repo_path) / MANIFEST).exists()
    return ManifestDiff(manifest_exists=exists,
                        undeclared=refd - decl,
                        stale=decl - refd)
