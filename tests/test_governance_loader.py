from security_scan.governance.loader import load_map

SAMPLE = """
[[tool]]
name = "security-scan.sh"
lane = "detect"
home_repo = "security-standards"
source = "scripts/security-scan.sh"
artifact_class = "deployed"
deploy_target = "~/.claude/bin/security-scan.sh"
mode = "755"

[[repo]]
name = "security-standards"
path = "~/Projects/security-standards"
class = "tool-home"
lane = "detect"
owns = ["security-scan.sh"]
consumers = ["infraops-mcp-server"]

[[repo]]
name = "FacelessTT"
path = "~/Projects/FacelessTT"
class = "consumer"
uses_bws = true

[[runtime_dir]]
path = "~/.claude/audit"
note = "weekly detector logs"
"""


def test_load_map_parses_all_sections(tmp_path):
    p = tmp_path / "governance-map.toml"
    p.write_text(SAMPLE)
    m = load_map(p)
    assert len(m.tools) == 1
    assert m.tools[0].name == "security-scan.sh"
    assert m.tools[0].artifact_class == "deployed"
    assert m.tools[0].mode == "755"
    assert {r.name: r.cls for r in m.repos} == {
        "security-standards": "tool-home",
        "FacelessTT": "consumer",
    }
    fac = next(r for r in m.repos if r.name == "FacelessTT")
    assert fac.uses_bws is True
    assert m.repos[0].consumers == ["infraops-mcp-server"]
    assert m.runtime_dirs[0].path == "~/.claude/audit"


def test_repo_defaults(tmp_path):
    p = tmp_path / "g.toml"
    p.write_text('[[repo]]\nname="x"\npath="~/x"\nclass="consumer"\n')
    m = load_map(p)
    assert m.repos[0].uses_bws is False
    assert m.repos[0].owns == []


def test_real_map_is_internally_consistent():
    """The checked-in map: every tool's home repo is declared, deploy targets are unique."""
    from security_scan.governance.__main__ import DEFAULT_MAP

    m = load_map(DEFAULT_MAP)
    repos = {r.name for r in m.repos}
    assert {t.home_repo for t in m.tools} <= repos
    targets = [t.deploy_target for t in m.tools if t.artifact_class == "deployed"]
    assert len(targets) == len(set(targets))
    cs = {t.name: t for t in m.tools if t.home_repo == "code-standards"}
    assert {"correction-recorder.sh", "quality-gate.sh"} <= set(cs)
    assert all(t.artifact_class == "deployed" and t.mode == "755" for t in cs.values())
