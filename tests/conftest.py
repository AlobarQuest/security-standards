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
