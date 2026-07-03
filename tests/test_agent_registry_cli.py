"""agent_registry CLI: validate / list / show / authority."""

import json

from agent_registry import cli


def test_validate_ok_on_real_registry(capsys):
    assert cli.main(["validate"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("registry ok:")


def test_list_names_all_agents(capsys):
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "change-window-agent" in out and "factory-runner" in out


def test_show_prints_record(capsys):
    assert cli.main(["show", "security-executor"]) == 0
    out = capsys.readouterr().out
    assert "security-window-v1" in out


def test_authority_json_merges(capsys):
    assert cli.main(["authority", "security-executor", "--json"]) == 0
    auth = json.loads(capsys.readouterr().out)
    assert "secret_write" in auth["capabilities"]
    assert "credential_revoke" in auth["prohibited"]


def test_unknown_agent_exits_nonzero(capsys):
    assert cli.main(["show", "nobody"]) == 1
