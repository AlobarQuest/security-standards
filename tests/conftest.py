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
