import json
import os
import urllib.request
from pathlib import Path

from security_scan.findings import Severity


def _http_get_json(url: str, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _coerce(rule: dict) -> dict:
    rule = dict(rule)
    sev = rule.get("severity", "INFO")
    rule["severity"] = sev if isinstance(sev, Severity) else Severity(sev)
    # infra-brain's add_rule has no `remediation` field, so live rules carry it folded into
    # `reason` (see seed script). Default it so downstream rule["remediation"] is always safe.
    rule.setdefault("remediation", rule.get("reason", ""))
    # Normalize rule identity across sources. The bundled cache uses a semantic string `id`
    # (e.g. "bws.no-token-in-tracked-files"); live infra-brain rules carry a numeric `id` and
    # store the semantic slug in the `rule` field (see seed script). Prefer the slug so finding
    # rule_ids and allowlist keys are identical in cache and live mode. A slug looks like a
    # dotted token with no spaces; prose `rule` statements (with spaces) are left as-is.
    slug = rule.get("rule")
    if isinstance(slug, str) and slug and " " not in slug and "." in slug:
        rule["id"] = slug
    return rule


def _fetch_live(category: str) -> list[dict] | None:
    base = os.environ.get("INFRABRAIN_BASE_URL")
    key = os.environ.get("INFRABRAIN_ACCESS_KEY")
    if not base or not key:
        return None
    try:
        data = _http_get_json(
            f"{base.rstrip('/')}/api/rules?category={category}",
            headers={"x-brain-key": key},
            timeout=10,
        )
    except Exception:
        return None
    return [r for r in data.get("rules", []) if r.get("check")]


def load_rules(category: str, cache_path: Path) -> tuple[list[dict], str]:
    """Returns (rules, source) where source is 'live' or 'cache'.
    Rules are filtered to those carrying a `check`, with severity coerced to Severity."""
    live = _fetch_live(category)
    if live:  # non-empty only; empty/None → fall through to cache (fail safe, never silent-pass)
        return [_coerce(r) for r in live], "live"
    cached = json.loads(Path(cache_path).read_text())
    return [_coerce(r) for r in cached], "cache"
