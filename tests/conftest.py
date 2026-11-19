import subprocess

import pytest


def _run(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path):
    """A real, empty, committed git repo. Returns a helper to add/commit files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q")
    _run(repo, "git", "config", "user.email", "t@t.t")
    _run(repo, "git", "config", "user.name", "t")

    class Helper:
        path = repo

        def write(self, rel, content):
            f = repo / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content)
            return f

        def commit(self, msg="c"):
            _run(repo, "git", "add", "-A")
            _run(repo, "git", "commit", "-q", "-m", msg)

    return Helper()


# Every chain setting, the retired whole-DSN names included (a set one refuses every command).
_CHAIN_VARS = (
    "FACTORY_EVENTS_APPEND_PASSWORD",
    "FACTORY_EVENTS_READ_PASSWORD",
    "FACTORY_EVENTS_DB_HOST",
    "FACTORY_EVENTS_DB_PORT",
    "FACTORY_EVENTS_DB_NAME",
    "FACTORY_EVENTS_APPEND_DSN",
    "FACTORY_EVENTS_READ_DSN",
    "FACTORY_EVENTS_IMPORT_DSN",
    "FACTORY_EVENTS_OWNER_DSN",
)


@pytest.fixture(autouse=True)
def _no_ambient_chain_settings(monkeypatch):
    """A shell holding a real chain password must never reach it from a test; tests that need
    the database chain set disposable settings themselves."""
    for name in _CHAIN_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_real_portfolio_feed(tmp_path, monkeypatch):
    """No test reads the real ~/.portfolio/portfolio-feed.json: `adapt --source all` reads the
    feed, so every test points it at a path under tmp_path that doesn't exist."""
    monkeypatch.setenv("FACTORY_EVENTS_PORTFOLIO_FEED", str(tmp_path / "no-portfolio-feed.json"))


@pytest.fixture(autouse=True)
def _no_real_mac_conformance_inputs(tmp_path, monkeypatch):
    """No test reads the Mac's real infra-drift reports, LaunchAgents or Claude settings:
    `adapt --source all` reads all three, so every test points them at absent paths under
    tmp_path."""
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(tmp_path / "no-infra-drift-reports"))
    monkeypatch.setenv("LAUNCHAGENTS_DIR", str(tmp_path / "no-launchagents"))
    monkeypatch.setenv("CLAUDE_SETTINGS_JSON", str(tmp_path / "no-claude-settings.json"))


class MemoryChain:
    """An in-memory stand-in for the database chain: db.append_event and db.event_ids, linked
    by the same formula. `make check-integration` runs the real one."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    @property
    def events(self) -> list[dict]:
        return [record["event"] for record in self.records]

    def append_event(self, params, event: dict) -> dict:
        from factory_events import chain, db, store
        from factory_events.envelope import validate_event

        assert params.user == chain.APPEND_ROLE
        try:
            validate_event(event)
        except Exception as exc:  # the real append wraps every failure the same way
            raise db.ChainError(f"append failed ({type(exc).__name__})") from None
        seq = len(self.records) + 1
        prev_hash = self.records[-1]["hash"] if self.records else store.GENESIS
        record = {
            "seq": seq,
            "prev_hash": prev_hash,
            "hash": store.line_hash(seq, prev_hash, event),
            "event": event,
        }
        self.records.append(record)
        return record

    def event_ids(self, params) -> set[str]:
        return {event["event_id"] for event in self.events}


@pytest.fixture
def memory_chain(monkeypatch) -> MemoryChain:
    """The append password and disposable settings, with db's append and event_ids faked, so
    emit and adapt run chain.py's real routing without a database."""
    from factory_events import chain, db

    fake = MemoryChain()
    monkeypatch.setattr(db, "append_event", fake.append_event)
    monkeypatch.setattr(db, "event_ids", fake.event_ids)
    for name, value in {
        chain.APPEND_PASSWORD_VAR: "memory-chain-placeholder",
        chain.DB_HOST_VAR: "127.0.0.1",
        chain.DB_PORT_VAR: "1",
        chain.DB_NAME_VAR: "factory_events",
    }.items():
        monkeypatch.setenv(name, value)
    return fake
