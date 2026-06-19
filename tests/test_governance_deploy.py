import os
import subprocess
from security_scan.governance.loader import Manifest, Tool, Repo
from security_scan.governance.deploy import (
    deploy_artifacts,
    verify_artifacts,
    reconcile_control_plane,
)
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


# ─────────────────────── control-plane reconcile (prong 1) ───────────────────────

def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True)


def _control_plane_manifest(tmp_path):
    """A ~/.claude-like git repo that TRACKS hooks/ but GITIGNORES bin/, plus a
    home repo supplying one hook (tracked) and one bin script (ignored)."""
    cp = tmp_path / "dotclaude"
    (cp / "hooks").mkdir(parents=True)
    (cp / "bin").mkdir(parents=True)
    # deny-by-default gitignore mirroring the real ~/.claude one
    (cp / ".gitignore").write_text("/*\n!/.gitignore\n!/hooks/\n")
    _git(cp, "init", "-q")
    _git(cp, "config", "user.email", "t@t.test")
    _git(cp, "config", "user.name", "t")
    _git(cp, "add", "-A")
    _git(cp, "commit", "-qm", "init")

    home = tmp_path / "home"
    (home / "hooks").mkdir(parents=True)
    (home / "scripts").mkdir(parents=True)
    (home / "hooks" / "guard.sh").write_text("echo guard\n")
    (home / "scripts" / "scan.sh").write_text("echo scan\n")
    _git(home, "init", "-q")
    _git(home, "config", "user.email", "t@t.test")
    _git(home, "config", "user.name", "t")
    _git(home, "add", "-A")
    _git(home, "commit", "-qm", "init")

    hook = Tool(name="guard.sh", lane="detect", home_repo="home",
                source="hooks/guard.sh", artifact_class="deployed",
                deploy_target=str(cp / "hooks" / "guard.sh"), mode="755")
    binscan = Tool(name="scan.sh", lane="detect", home_repo="home",
                   source="scripts/scan.sh", artifact_class="deployed",
                   deploy_target=str(cp / "bin" / "scan.sh"), mode="755")
    repo = Repo(name="home", path=str(home), cls="tool-home")
    m = Manifest(tools=[hook, binscan], repos=[repo], runtime_dirs=[])
    return m, cp


def _porcelain(cp, *paths):
    return _git(cp, "status", "--porcelain", "--", *paths).stdout


def test_reconcile_commits_tracked_hook_but_not_ignored_bin(tmp_path):
    m, cp = _control_plane_manifest(tmp_path)
    deploy_artifacts(m)
    # before reconcile: the tracked hook is untracked → would FAIL Check 13
    assert _porcelain(cp, "hooks/") != ""
    head_before = _git(cp, "rev-parse", "HEAD").stdout.strip()

    reconcile_control_plane(m)

    # hook committed → clean (Check 13 sees no drift)
    assert _porcelain(cp, "hooks/") == ""
    assert _git(cp, "rev-parse", "HEAD").stdout.strip() != head_before
    # the gitignored bin/ script was deployed but NOT committed
    assert _git(cp, "ls-files", "bin/").stdout.strip() == ""


def test_reconcile_is_idempotent(tmp_path):
    m, cp = _control_plane_manifest(tmp_path)
    deploy_artifacts(m)
    reconcile_control_plane(m)
    head_after_first = _git(cp, "rev-parse", "HEAD").stdout.strip()
    # second deploy+reconcile with no source change → no new commit
    deploy_artifacts(m)
    reconcile_control_plane(m)
    assert _git(cp, "rev-parse", "HEAD").stdout.strip() == head_after_first


def test_reconcile_does_not_sweep_unrelated_dirty_files(tmp_path):
    m, cp = _control_plane_manifest(tmp_path)
    # an unrelated tracked control-plane file gets dirtied out-of-band
    (cp / ".gitignore").write_text("/*\n!/.gitignore\n!/hooks/\n# tampered\n")
    deploy_artifacts(m)
    reconcile_control_plane(m)
    # the hook is committed clean, but the unrelated .gitignore edit is UNTOUCHED
    assert _porcelain(cp, "hooks/") == ""
    assert _porcelain(cp, ".gitignore") != ""


def test_reconcile_reports_only_changed_paths(tmp_path):
    # two tracked hooks; only one changes on the second deploy
    m, cp = _control_plane_manifest(tmp_path)
    home = tmp_path / "home"
    (home / "hooks" / "guard2.sh").write_text("echo guard2\n")
    _git(home, "add", "-A")
    _git(home, "commit", "-qm", "add guard2")
    m.tools.append(Tool(name="guard2.sh", lane="detect", home_repo="home",
                        source="hooks/guard2.sh", artifact_class="deployed",
                        deploy_target=str(cp / "hooks" / "guard2.sh"), mode="755"))
    deploy_artifacts(m)
    reconcile_control_plane(m)  # commits both hooks
    # now change only guard2's source and redeploy
    (home / "hooks" / "guard2.sh").write_text("echo guard2 v2\n")
    deploy_artifacts(m)
    actions = reconcile_control_plane(m)
    notes = " ".join(note for _, note in actions)
    assert "guard2.sh" in notes
    assert "guard.sh" not in notes.replace("guard2.sh", "")  # only guard2 reported
    # commit touched only guard2.sh
    stat = _git(cp, "show", "--stat", "--format=", "HEAD").stdout
    assert "guard2.sh" in stat and "guard.sh\n" not in stat


def test_reconcile_noop_when_target_not_git(tmp_path):
    # reuse the simple non-git fixture
    m, target = _manifest(tmp_path)
    deploy_artifacts(m)
    # must not raise and must report no control-plane commits
    actions = reconcile_control_plane(m)
    assert all("committed" not in note for _, note in actions)
