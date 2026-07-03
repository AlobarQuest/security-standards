import pytest

from factory_events import envelope


def _valid_event() -> dict:
    return envelope.make_event(
        actor="claude-code-unattributed",
        action="tool.vps_exec",
        result="unknown",
        source={"system": "high-power-audit", "ref": "line:1"},
        timestamp="2026-07-02T23:33:35Z",
        correlation_id="3ca07069-0000-0000-0000-000000000000",
        evidence=[{"type": "source-record", "record": {"tool": "mcp__infraops__vps_exec"}}],
        event_id=envelope.deterministic_event_id("high-power-audit", "rawline"),
    )


def test_make_event_produces_valid_event():
    ev = _valid_event()
    envelope.validate_event(ev)  # must not raise
    assert ev["schema"] == "factory-event/v1"
    assert ev["work_package"] is None and ev["input_revision"] is None


def test_deterministic_event_id_is_stable_and_prefixed():
    a = envelope.deterministic_event_id("high-power-audit", "rawline")
    b = envelope.deterministic_event_id("high-power-audit", "rawline")
    c = envelope.deterministic_event_id("change-manager", "rawline")
    assert a == b and a != c and a.startswith("evt-") and len(a) == 4 + 64


def test_new_event_id_unique_and_valid_shape():
    a, b = envelope.new_event_id(), envelope.new_event_id()
    assert a != b and a.startswith("evt-")


def test_validate_rejects_bad_result():
    ev = _valid_event()
    ev["result"] = "ok"
    with pytest.raises(envelope.EnvelopeError):
        envelope.validate_event(ev)


def test_validate_rejects_unknown_field():
    ev = _valid_event()
    ev["extra"] = 1
    with pytest.raises(envelope.EnvelopeError):
        envelope.validate_event(ev)


def test_validate_rejects_non_z_timestamp():
    ev = _valid_event()
    ev["timestamp"] = "2026-07-02T23:33:35+00:00"
    with pytest.raises(envelope.EnvelopeError):
        envelope.validate_event(ev)


def test_canonical_json_sorted_and_compact():
    assert envelope.canonical_json({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'
