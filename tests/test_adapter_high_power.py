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
    shutil.copy(FIXTURE, src)
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


def test_malformed_source_line_raises_source_error_and_keeps_watermark(source):
    high_power.adapt(source=source)
    with source.open("a") as fh:
        fh.write("{not json\n")
    with pytest.raises(high_power.SourceError):
        high_power.adapt(source=source)
    # watermark untouched by the failed run: fixing the file resumes cleanly
    assert len(store.event_ids()) == 3


def test_cli_reports_source_error(tmp_path, monkeypatch, capsys):
    src = tmp_path / "hp.jsonl"
    src.write_text("{not json\n")
    monkeypatch.setattr(high_power, "DEFAULT_SOURCE", src)
    from factory_events.cli import main
    assert main(["adapt", "--source", "high-power"]) == 1
    assert "ADAPT FAIL (high-power)" in capsys.readouterr().err


def test_governance_bypass_record_maps(source):
    with source.open("a") as fh:
        fh.write(json.dumps({
            "action": "code-standards-bypass", "repo": "/Users/devon/Projects/x",
            "note": "CODE_STANDARDS_BYPASS=1 was set; quality gate bypassed",
            "timestamp": "2026-06-28T12:03:10Z",
        }) + "\n")
    count = high_power.adapt(source=source)
    assert count == 4
    ev = list(store.iter_records())[-1]["event"]
    assert ev["action"] == "governance.code-standards-bypass"
    assert ev["target"] == "/Users/devon/Projects/x"
    assert ev["result"] == "success"


def test_record_with_neither_tool_nor_action_raises(source):
    high_power.adapt(source=source)
    with source.open("a") as fh:
        fh.write('{"timestamp":"2026-06-28T12:03:10Z","mystery":"x"}\n')
    with pytest.raises(high_power.SourceError):
        high_power.adapt(source=source)
