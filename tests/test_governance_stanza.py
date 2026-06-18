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
