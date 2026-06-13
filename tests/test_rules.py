import json
from security_scan import rules


def test_load_from_cache_when_no_infrabrain(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps([
        {"id": "bws.x", "severity": "BLOCK",
         "check": {"kind": "forbidden_pattern", "pattern": "p", "scope": "tracked"},
         "remediation": "r", "reason": "y"}
    ]))
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    loaded, source = rules.load_rules(category="security", cache_path=cache)
    assert source == "cache"
    assert loaded[0]["id"] == "bws.x"
    assert loaded[0]["severity"].value == "BLOCK"   # coerced to Severity


def test_live_fetch_filters_to_rules_with_checks(monkeypatch, tmp_path):
    def fake_get(url, headers, timeout):
        return {"rules": [
            {"id": 1, "rule": "no token", "reason": "leak", "severity": "BLOCK",
             "check": {"kind": "forbidden_pattern", "pattern": "p", "scope": "tracked"},
             "remediation": "r"},
            {"id": 2, "rule": "prose only", "reason": "x", "severity": "INFO", "check": None},
        ]}
    monkeypatch.setattr(rules, "_http_get_json", fake_get)
    monkeypatch.setenv("INFRABRAIN_BASE_URL", "https://ib.example")
    monkeypatch.setenv("INFRABRAIN_ACCESS_KEY", "k")
    loaded, source = rules.load_rules(category="security", cache_path=tmp_path / "nope.json")
    assert source == "live"
    assert len(loaded) == 1 and loaded[0]["id"] == 1
