import os
from security_scan.governance.loader import Manifest, Tool, Repo
from security_scan.governance.deploy import deploy_artifacts, verify_artifacts
from security_scan.governance.__main__ import main


def _manifest(tmp_path):
    repo_root = tmp_path / "home"
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "scripts" / "tool.sh").write_text("echo hi\n")
    target = tmp_path / "deployed" / "tool.sh"
    tool = Tool(name="tool.sh", lane="detect", home_repo="home",
                source="scripts/tool.sh", artifact_class="deployed",
                deploy_target=str(target), mode="755")
    repo = Repo(name="home", path=str(repo_root), cls="tool-home")
    return Manifest(tools=[tool], repos=[repo], runtime_dirs=[]), target


def test_deploy_copies_with_mode(tmp_path):
    m, target = _manifest(tmp_path)
    actions = deploy_artifacts(m)
    assert actions == [("tool.sh", "deployed")]
    assert target.read_text() == "echo hi\n"
    assert oct(target.stat().st_mode)[-3:] == "755"


def test_verify_clean_after_deploy(tmp_path):
    m, _ = _manifest(tmp_path)
    deploy_artifacts(m)
    assert verify_artifacts(m) == []


def test_verify_detects_drift_and_missing(tmp_path):
    m, target = _manifest(tmp_path)
    assert verify_artifacts(m) == [("tool.sh", "missing")]
    deploy_artifacts(m)
    target.write_text("tampered\n")
    assert verify_artifacts(m) == [("tool.sh", "drift")]


def test_cli_deploy_then_verify(tmp_path, capsys):
    repo_root = tmp_path / "home"
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "scripts" / "t.sh").write_text("x\n")
    target = tmp_path / "out" / "t.sh"
    toml = tmp_path / "g.toml"
    toml.write_text(f'''
[[tool]]
name = "t.sh"
lane = "detect"
home_repo = "home"
source = "scripts/t.sh"
artifact_class = "deployed"
deploy_target = "{target}"
mode = "755"

[[repo]]
name = "home"
path = "{repo_root}"
class = "tool-home"
''')
    assert main(["deploy", "--map", str(toml)]) == 0
    assert main(["verify", "--artifacts-only", "--map", str(toml)]) == 0
    target.write_text("tampered\n")
    assert main(["verify", "--artifacts-only", "--map", str(toml)]) == 1
    assert "drift" in capsys.readouterr().out
