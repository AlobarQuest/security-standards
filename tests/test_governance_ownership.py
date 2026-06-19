from security_scan.governance.loader import Manifest, Repo
from security_scan.governance.ownership import render_stanza, block, START, END

TOOLHOME = Repo(name="infraops-mcp-server", path="~/Projects/infraops-mcp-server",
                cls="tool-home", lane="mutate",
                owns=["drift-audit.sh", "change-window.sh"],
                consumers=["FacelessTT"])
CONSUMER = Repo(name="FacelessTT", path="~/Projects/FacelessTT",
                cls="consumer", uses_bws=True)
M = Manifest(tools=[], repos=[TOOLHOME, CONSUMER], runtime_dirs=[])


def test_toolhome_stanza_mentions_ownership_and_lane():
    s = render_stanza(TOOLHOME, M)
    assert "tool-home" in s
    assert "mutate" in s
    assert "`drift-audit.sh`" in s
    assert "make install" in s and "make verify" in s
    assert "FacelessTT" in s


def test_toolhome_stanza_states_honest_gating_scope():
    # The "approve" lane oversells the interactive threat model unless the stanza
    # is explicit that only the autonomous path is approval-gated (review item #2).
    s = render_stanza(TOOLHOME, M)
    assert "autonomous" in s.lower()
    assert "interactive" in s.lower()
    assert "guardrail-gated" in s.lower()


def test_consumer_stanza_mentions_enforcement_and_bws():
    s = render_stanza(CONSUMER, M)
    assert "consumer" in s
    assert "security-standards" in s
    assert "bws-write-guard" in s
    assert ".bws-secrets.toml" in s


def test_consumer_without_bws_omits_manifest_line():
    nobws = Repo(name="X", path="~/X", cls="consumer", uses_bws=False)
    s = render_stanza(nobws, M)
    assert ".bws-secrets.toml" not in s


def test_block_is_wrapped_in_markers():
    b = block(CONSUMER, M)
    assert b.startswith(START)
    assert b.rstrip().endswith(END)


from security_scan.governance.ownership import (
    sync_stanza, verify_stanza, ensure_bws_manifest,
)


def _repo_at(tmp_path, uses_bws=True):
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(name="FacelessTT", path=str(d), cls="consumer", uses_bws=uses_bws), d


def test_sync_creates_then_is_idempotent(tmp_path):
    repo, d = _repo_at(tmp_path)
    m = Manifest(tools=[], repos=[repo], runtime_dirs=[])
    (d / "CLAUDE.md").write_text("# FacelessTT\n\nExisting notes.\n")
    assert sync_stanza(repo, m) == "created"
    assert START in (d / "CLAUDE.md").read_text()
    assert "Existing notes." in (d / "CLAUDE.md").read_text()
    assert sync_stanza(repo, m) == "unchanged"


def test_sync_updates_stale_block_in_place(tmp_path):
    repo, d = _repo_at(tmp_path)
    m = Manifest(tools=[], repos=[repo], runtime_dirs=[])
    (d / "CLAUDE.md").write_text(f"# T\n\n{START}\nOLD\n{END}\n\nTail.\n")
    assert sync_stanza(repo, m) == "written"
    text = (d / "CLAUDE.md").read_text()
    assert "OLD" not in text
    assert "Tail." in text
    assert verify_stanza(repo, m) == "ok"


def test_verify_reports_missing_and_drift(tmp_path):
    repo, d = _repo_at(tmp_path)
    m = Manifest(tools=[], repos=[repo], runtime_dirs=[])
    assert verify_stanza(repo, m) == "missing"
    sync_stanza(repo, m)
    assert verify_stanza(repo, m) == "ok"
    cur = (d / "CLAUDE.md").read_text().replace("consumer", "TAMPERED")
    (d / "CLAUDE.md").write_text(cur)
    assert verify_stanza(repo, m) == "drift"


def test_ensure_bws_manifest(tmp_path):
    repo, d = _repo_at(tmp_path, uses_bws=True)
    assert ensure_bws_manifest(repo) == "created"
    assert (d / ".bws-secrets.toml").exists()
    assert ensure_bws_manifest(repo) == "exists"
    nob_dir = tmp_path / "n"
    nob_dir.mkdir()
    nob = Repo(name="N", path=str(nob_dir), cls="consumer", uses_bws=False)
    assert ensure_bws_manifest(nob) == "skip"


from security_scan.governance.__main__ import main as gov_main


def test_cli_sync_then_full_verify(tmp_path, capsys):
    repo_root = tmp_path / "FacelessTT"
    repo_root.mkdir()
    (repo_root / "CLAUDE.md").write_text("# FacelessTT\n")
    toml = tmp_path / "g.toml"
    toml.write_text(f'''
[[repo]]
name = "FacelessTT"
path = "{repo_root}"
class = "consumer"
uses_bws = true
''')
    assert gov_main(["sync", "--map", str(toml)]) == 0
    assert START in (repo_root / "CLAUDE.md").read_text()
    assert (repo_root / ".bws-secrets.toml").exists()
    assert gov_main(["verify", "--map", str(toml)]) == 0
    # tamper → full verify fails
    (repo_root / "CLAUDE.md").write_text("# wiped\n")
    assert gov_main(["verify", "--map", str(toml)]) == 1
    assert "stanza" in capsys.readouterr().out


from security_scan.governance.ownership import (
    render_ownership, write_ownership, verify_ownership,
)
from security_scan.governance.loader import Tool


def _own_manifest():
    tool = Tool(name="security-scan.sh", lane="detect", home_repo="security-standards",
                source="scripts/security-scan.sh", artifact_class="deployed",
                deploy_target="~/.claude/bin/security-scan.sh", mode="755")
    th = Repo(name="security-standards", path="~/Projects/security-standards",
              cls="tool-home", lane="detect", owns=["security-scan.sh"])
    cons = Repo(name="FacelessTT", path="~/Projects/FacelessTT", cls="consumer", uses_bws=True)
    return Manifest(tools=[tool], repos=[th, cons], runtime_dirs=[])


def test_render_ownership_has_artifact_lane_and_gating():
    s = render_ownership(_own_manifest())
    assert "security-scan.sh" in s
    assert "~/.claude/bin/security-scan.sh" in s
    assert "~/Projects/security-standards/scripts/security-scan.sh" in s
    # honest-gating note migrated from item #2
    assert "autonomous" in s.lower() and "interactive" in s.lower()
    assert "guardrail-gated" in s.lower()
    # repos surfaced
    assert "security-standards" in s and "FacelessTT" in s


def test_write_ownership_idempotent(tmp_path):
    m = _own_manifest()
    p = tmp_path / "OWNERSHIP.md"
    assert write_ownership(m, p) == "written"
    assert write_ownership(m, p) == "unchanged"


def test_verify_ownership_missing_then_ok_then_drift(tmp_path):
    m = _own_manifest()
    p = tmp_path / "OWNERSHIP.md"
    assert verify_ownership(m, p) == "missing"
    write_ownership(m, p)
    assert verify_ownership(m, p) == "ok"
    p.write_text(p.read_text() + "tamper\n")
    assert verify_ownership(m, p) == "drift"


from security_scan.governance.ownership import source_header_lines, verify_headers


def _hdr_manifest(tmp_path, body_first_tool="echo a\n", with_header=True):
    home = tmp_path / "home"
    (home / "scripts").mkdir(parents=True)
    tool = Tool(name="a.sh", lane="detect", home_repo="home",
                source="scripts/a.sh", artifact_class="deployed",
                deploy_target="~/.claude/bin/a.sh", mode="755")
    repo = Repo(name="home", path=str(home), cls="tool-home")
    m = Manifest(tools=[tool], repos=[repo], runtime_dirs=[])
    hdr = "\n".join(source_header_lines(tool, m)) + "\n" if with_header else ""
    (home / "scripts" / "a.sh").write_text("#!/bin/bash\n" + hdr + body_first_tool)
    return m


def test_source_header_first_line_names_source_and_target(tmp_path):
    m = _hdr_manifest(tmp_path)
    first = source_header_lines(m.tools[0], m)[0]
    assert "Source of truth:" in first
    assert "scripts/a.sh" in first
    assert "~/.claude/bin/a.sh" in first


def test_verify_headers_ok_when_present(tmp_path):
    m = _hdr_manifest(tmp_path, with_header=True)
    assert verify_headers(m) == []


def test_verify_headers_flags_missing(tmp_path):
    m = _hdr_manifest(tmp_path, with_header=False)
    assert verify_headers(m) == [("a.sh", "missing")]


def test_verify_headers_flags_wrong_when_stale_header(tmp_path):
    m = _hdr_manifest(tmp_path, with_header=False)
    src = next(iter([m.tools[0]]))
    p = (tmp_path / "home" / "scripts" / "a.sh")
    p.write_text("#!/bin/bash\n# Source of truth: WRONG/path (deployed → nope)\necho a\n")
    assert verify_headers(m) == [("a.sh", "wrong")]
