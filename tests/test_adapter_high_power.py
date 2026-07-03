import json
import shutil
from pathlib import Path

import pytest

from factory_events import store
from factory_events.adapters import high_power

FIXTURE = Path(__file__).parent / "fixtures" / "high_power_sample.jsonl"
PROVENANCE = "unknown (confirm at review: direct request vs inferred from read content)"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path / "factory"))
    yield tmp_path


@pytest.fixture()
def source(tmp_path) -> Path:
    src = tmp_path / "high-power-actions.jsonl"
    shutil.copy(FIXTURE, src)  # noqa: E501
    return src


def test_adapt_maps_fields(source):
    count = high_power.adapt(source=source)
    assert count == 3
    records = list(store.iter_records())
    ev = records[0]["event"]
    assert ev["action"] == "tool.vps_exec"
    assert ev["actor"] == "claude-code-unattributed"
    assert ev["result"] == "unknown"
    assert ev["correlation_id"] == "3ca07069-1111-2222-3333-444444444444"
    assert ev["source"] == {"system": "high-power-audit", "ref": "line:1"}
    assert ev["evidence"][0]["type"] == "source-record"
    assert ev["evidence"][0]["record"]["tool"] == "mcp__infraops__vps_exec"
    assert ev["target"] == "docker ps"
    # non-MCP tool name passes through
    assert records[2]["event"]["action"] == "tool.gmail__send"


def test_adapt_is_incremental_and_idempotent(source):
    assert high_power.adapt(source=source) == 3
    assert high_power.adapt(source=source) == 0  # nothing new
    with source.open("a") as fh:
        fh.write(json.dumps({
            "timestamp": "2026-07-03T02:00:00Z", "tool": "mcp__infraops__vps_exec",
            "session_id": "s", "args_summary": "{}",
            "provenance": PROVENANCE,
        }) + "\n")
    assert high_power.adapt(source=source) == 1
    assert len(store.event_ids()) == 4


def test_rewritten_source_raises_without_reanchor(source):
    high_power.adapt(source=source)
    lines = source.read_text().splitlines()
    lines[0] = lines[0].replace("docker ps", "docker kill")
    source.write_text("\n".join(lines) + "\n")
    with pytest.raises(high_power.WatermarkError):
        high_power.adapt(source=source)


def test_reanchor_reingests_with_dedupe(source):
    high_power.adapt(source=source)
    lines = source.read_text().splitlines()
    lines[0] = lines[0].replace("docker ps", "docker kill")
    source.write_text("\n".join(lines) + "\n")
    count = high_power.adapt(source=source, reanchor=True)
    # only the rewritten line is new (different raw line -> different event_id)
    assert count == 1
    assert len(store.event_ids()) == 4


def test_truncated_source_raises(source):
    high_power.adapt(source=source)
    source.write_text("")
    with pytest.raises(high_power.WatermarkError):
        high_power.adapt(source=source)
