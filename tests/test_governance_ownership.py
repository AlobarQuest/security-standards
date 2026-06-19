from security_scan.governance.__main__ import main as gov_main
from security_scan.governance.loader import Manifest, Repo, Tool
from security_scan.governance.ownership import (
    START, END, strip_stanza, ensure_bws_manifest,
    render_ownership, write_ownership, verify_ownership,
    source_header_lines, verify_headers,
)


def _repo_at(tmp_path, uses_bws=True):
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(name="FacelessTT", path=str(d), cls="consumer", uses_bws=uses_bws), d


def test_ensure_bws_manifest(tmp_path):
    repo, d = _repo_at(tmp_path, uses_bws=True)
    assert ensure_bws_manifest(repo) == "created"
    assert (d / ".bws-secrets.toml").exists()
    assert ensure_bws_manifest(repo) == "exists"
    nob_dir = tmp_path / "n"
    nob_dir.mkdir()
    nob = Repo(name="N", path=str(nob_dir), cls="consumer", uses_bws=False)
    assert ensure_bws_manifest(nob) == "skip"


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
    p = (tmp_path / "home" / "scripts" / "a.sh")
    p.write_text("#!/bin/bash\n# Source of truth: WRONG/path (deployed → nope)\necho a\n")
    assert verify_headers(m) == [("a.sh", "wrong")]


def test_verify_headers_flags_missing_when_source_file_absent(tmp_path):
    # manifest points at a deployed tool whose source file does not exist
    tool = Tool(name="gone.sh", lane="detect", home_repo="home",
                source="scripts/gone.sh", artifact_class="deployed",
                deploy_target="~/.claude/bin/gone.sh", mode="755")
    repo = Repo(name="home", path=str(tmp_path / "home"), cls="tool-home")
    (tmp_path / "home" / "scripts").mkdir(parents=True)
    m = Manifest(tools=[tool], repos=[repo], runtime_dirs=[])
    assert verify_headers(m) == [("gone.sh", "missing")]


def test_strip_removes_block_preserves_surrounding(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    cm = d / "CLAUDE.md"
    cm.write_text(f"# Title\n\nIntro.\n\n{START}\nGENERATED\n{END}\n\nTail.\n")
    repo = Repo(name="R", path=str(d), cls="consumer")
    assert strip_stanza(repo) == "stripped"
    text = cm.read_text()
    assert "GENERATED" not in text and START not in text and END not in text
    assert "Intro." in text and "Tail." in text
    # idempotent
    assert strip_stanza(repo) == "absent"


def test_strip_block_at_end(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    cm = d / "CLAUDE.md"
    cm.write_text(f"# Title\n\nBody.\n\n{START}\nX\n{END}\n")
    repo = Repo(name="R", path=str(d), cls="consumer")
    assert strip_stanza(repo) == "stripped"
    assert cm.read_text() == "# Title\n\nBody.\n"


def test_strip_missing_claude_md(tmp_path):
    repo = Repo(name="R", path=str(tmp_path / "nope"), cls="consumer")
    assert strip_stanza(repo) == "missing"


# ─────────────────────── CLI tests ───────────────────────

def _cli_map(tmp_path, with_header=True):
    home = tmp_path / "home"
    (home / "scripts").mkdir(parents=True)
    target = tmp_path / "out" / "t.sh"
    tool_src = home / "scripts" / "t.sh"
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
path = "{home}"
class = "tool-home"
''')
    hdr = (f"# Source of truth: {home}/scripts/t.sh (deployed → {target})\n"
           "# Edit here, not in place; then: cd ~/Projects/security-standards && make install\n"
           ) if with_header else ""
    tool_src.write_text("#!/bin/bash\n" + hdr + "echo x\n")
    return toml, target


def test_cli_ownership_then_full_verify(tmp_path, capsys):
    toml, target = _cli_map(tmp_path)
    own = tmp_path / "OWNERSHIP.md"
    assert gov_main(["deploy", "--map", str(toml)]) == 0
    assert gov_main(["ownership", "--map", str(toml), "--ownership-path", str(own)]) == 0
    assert own.exists()
    assert gov_main(["verify", "--map", str(toml), "--ownership-path", str(own)]) == 0


def test_cli_verify_fails_on_missing_header(tmp_path, capsys):
    toml, target = _cli_map(tmp_path, with_header=False)
    gov_main(["deploy", "--map", str(toml)])
    assert gov_main(["verify", "--artifacts-only", "--map", str(toml)]) == 1
    assert "header" in capsys.readouterr().out


def test_cli_strip_stanzas(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    (home / "CLAUDE.md").write_text(f"# H\n\n{START}\nX\n{END}\n")
    toml = tmp_path / "g.toml"
    toml.write_text(f'[[repo]]\nname = "home"\npath = "{home}"\nclass = "tool-home"\n')
    assert gov_main(["strip-stanzas", "--map", str(toml)]) == 0
    assert START not in (home / "CLAUDE.md").read_text()
