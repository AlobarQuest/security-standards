from security_scan.governance.loader import Manifest, Repo
from security_scan.governance.stanza import render_stanza, block, START, END

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


from security_scan.governance.stanza import (
    sync_stanza, verify_stanza, ensure_bws_manifest, block,
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
