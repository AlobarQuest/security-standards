import json

import pytest

from factory_events import store
from factory_events.cli import main


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def test_emit_appends_valid_event(capsys):
    rc = main([
        "emit",
        "--actor", "devon",
        "--action", "factory.bootstrap",
        "--result", "success",
        "--ref", "manual",
    ])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("evt-")
    assert store.head()[0] == 1


def test_emit_json_payload(capsys):
    payload = json.dumps({"note": "hello"})
    rc = main([
        "emit", "--actor", "devon", "--action", "factory.note",
        "--result", "success", "--ref", "manual", "--evidence-json", payload,
    ])
    assert rc == 0
    rec = list(store.iter_records())[0]
    assert rec["event"]["evidence"] == [{"note": "hello"}]


def test_emit_rejects_bad_action(capsys):
    rc = main(["emit", "--actor", "devon", "--action", "no-dots-here!",
               "--result", "success", "--ref", "manual"])
    assert rc == 1


def test_verify_ok_and_failure(capsys, tmp_path):
    main(["emit", "--actor", "devon", "--action", "factory.bootstrap",
          "--result", "success", "--ref", "manual"])
    assert main(["verify"]) == 0
    path = store.events_path()
    line = json.loads(path.read_text())
    line["event"]["actor"] = "mallory"
    path.write_text(json.dumps(line) + "\n")
    assert main(["verify"]) == 1
