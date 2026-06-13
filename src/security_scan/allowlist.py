import tomllib
from dataclasses import dataclass
from pathlib import Path

ALLOWLIST = ".security-scan-allow.toml"


@dataclass
class AllowEntry:
    rule: str
    file: str | None = None
    evidence: str | None = None
    reason: str = ""

    def matches(self, finding) -> bool:
        if finding.rule_id != self.rule:
            return False
        if self.file is not None and finding.file != self.file:
            return False
        if self.evidence is not None and finding.evidence != self.evidence:
            return False
        return True


def load(repo_path) -> list[AllowEntry]:
    p = Path(repo_path) / ALLOWLIST
    if not p.exists():
        return []
    data = tomllib.loads(p.read_text())
    return [AllowEntry(rule=e["rule"], file=e.get("file"),
                       evidence=e.get("evidence"), reason=e.get("reason", ""))
            for e in data.get("allow", [])]


def is_allowed(finding, entries) -> bool:
    return any(e.matches(finding) for e in entries)
