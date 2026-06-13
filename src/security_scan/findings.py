from dataclasses import dataclass, asdict
from enum import Enum


class Severity(str, Enum):
    BLOCK = "BLOCK"
    WARN = "WARN"
    INFO = "INFO"


@dataclass
class Finding:
    rule_id: str
    severity: Severity
    file: str | None
    line: int | None
    evidence: str          # MUST already be redacted
    remediation: str
    reason: str
    kind: str              # "deterministic" | "judgment"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


def redact(value: str) -> str:
    """Mask a matched secret: keep a short non-secret prefix, hide the rest.
    A scanner that printed the secret it found would itself be the leak."""
    if len(value) <= 12:
        return "***"
    return f"{value[:8]}…(len {len(value)})"
