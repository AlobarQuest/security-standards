"""Controls for `scripts/activate-checkout.sh`.

The helper is sourced into a scheduled launcher and pulls the checkout that launcher reads.
Its whole contract is that it acts when it safely can, says what it did in one line, and never
fails its caller — so these controls drive real git repositories rather than mocking git, and
every one of them asserts the return code as well as the line.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "scripts" / "activate-checkout.sh"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **GIT_ENV},
    )
    return result.stdout.strip()


def commit(repo: Path, name: str, body: str, message: str) -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(body)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def run_helper(checkout: Path, *extra: str, env: dict[str, str] | None = None):
    """Source the helper in a fresh bash and activate `checkout`."""
    script = f'. "{HELPER}"\nactivate_checkout "{checkout}" {" ".join(extra)}\n'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV, **(env or {})},
    )


@pytest.fixture
def estate(tmp_path: Path) -> tuple[Path, Path]:
    """An `origin` and a checkout of it, both on `main`, as every enrolled repository is."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "--bare", "--initial-branch=main")

    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "--initial-branch=main")
    commit(seed, "README.md", "one\n", "first")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "main")

    checkout = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(checkout)],
        check=True,
        env={**os.environ, **GIT_ENV},
    )
    return origin, checkout


def advance_origin(origin: Path, tmp_path: Path, name: str = "README.md", body: str = "two\n"):
    """Land a commit on origin/main, the way a Dependabot auto-merge does."""
    work = tmp_path / "advance"
    if not work.exists():
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(work)],
            check=True,
            env={**os.environ, **GIT_ENV},
        )
    sha = commit(work, name, body, f"land {name}")
    git(work, "push", "-q", "origin", "main")
    return sha


# ── the ordinary paths ────────────────────────────────────────────────────────────────────────


def test_a_current_checkout_reports_current_and_moves_nothing(estate, tmp_path):
    _, checkout = estate
    before = git(checkout, "rev-parse", "HEAD")

    result = run_helper(checkout)

    assert result.returncode == 0
    assert "is current at" in result.stdout
    assert git(checkout, "rev-parse", "HEAD") == before


def test_a_behind_checkout_is_fast_forwarded_onto_the_landed_commit(estate, tmp_path):
    origin, checkout = estate
    landed = advance_origin(origin, tmp_path)

    result = run_helper(checkout)

    assert result.returncode == 0
    assert "activated" in result.stdout
    assert git(checkout, "rev-parse", "HEAD") == landed


# ── the two conditions, named differently on purpose ──────────────────────────────────────────


def test_a_checkout_on_a_build_branch_is_left_alone_and_is_not_called_held(estate, tmp_path):
    """A main tree on a build branch is ordinary here — run what is there, and say so plainly."""
    origin, checkout = estate
    advance_origin(origin, tmp_path)
    git(checkout, "checkout", "-q", "-b", "ws/some-build")
    before = git(checkout, "rev-parse", "HEAD")

    result = run_helper(checkout)

    assert result.returncode == 0
    assert "is on 'ws/some-build', not main" in result.stdout
    assert "HELD" not in result.stdout
    assert git(checkout, "rev-parse", "HEAD") == before


def test_a_checkout_that_cannot_fast_forward_is_held_loudly_and_still_returns_zero(
    estate, tmp_path
):
    origin, checkout = estate
    advance_origin(origin, tmp_path)
    commit(checkout, "local.txt", "diverged\n", "local commit")
    before = git(checkout, "rev-parse", "HEAD")

    result = run_helper(checkout)

    assert result.returncode == 0
    assert "HELD" in result.stdout
    assert "cannot fast-forward" in result.stdout
    assert git(checkout, "rev-parse", "HEAD") == before


def test_an_uncommitted_change_to_an_incoming_file_holds_rather_than_clobbering_it(
    estate, tmp_path
):
    """`--ff-only` refuses rather than overwriting local work, and the helper must not force."""
    origin, checkout = estate
    advance_origin(origin, tmp_path, name="README.md", body="landed\n")
    (checkout / "README.md").write_text("work in progress\n")
    before = git(checkout, "rev-parse", "HEAD")

    result = run_helper(checkout)

    assert result.returncode == 0
    assert "HELD" in result.stdout
    assert git(checkout, "rev-parse", "HEAD") == before
    assert (checkout / "README.md").read_text() == "work in progress\n"


def test_an_uncommitted_change_elsewhere_does_not_prevent_activation(estate, tmp_path):
    """Three of the nine enrolled checkouts are dirty on a given day; that alone must not block."""
    origin, checkout = estate
    landed = advance_origin(origin, tmp_path, name="other.txt", body="landed\n")
    (checkout / "scratch.txt").write_text("untracked\n")

    result = run_helper(checkout)

    assert result.returncode == 0
    assert "activated" in result.stdout
    assert git(checkout, "rev-parse", "HEAD") == landed


# ── the degenerate inputs, all of which are survivable ─────────────────────────────────────────


def test_a_path_that_is_not_a_checkout_is_reported_and_survived(tmp_path):
    result = run_helper(tmp_path / "nowhere")
    assert result.returncode == 0
    assert "is not a git checkout" in result.stdout


def test_a_checkout_with_no_upstream_runs_what_is_there(tmp_path):
    solo = tmp_path / "solo"
    solo.mkdir()
    git(solo, "init", "-q", "--initial-branch=main")
    commit(solo, "README.md", "one\n", "first")

    result = run_helper(solo)

    assert result.returncode == 0
    assert "has no upstream" in result.stdout


def test_an_unreachable_origin_runs_what_is_there(estate, tmp_path):
    origin, checkout = estate
    git(checkout, "remote", "set-url", "origin", str(tmp_path / "gone"))
    before = git(checkout, "rev-parse", "HEAD")

    result = run_helper(checkout)

    assert result.returncode == 0
    assert "could not reach origin" in result.stdout
    assert git(checkout, "rev-parse", "HEAD") == before


def test_the_helper_does_not_abort_a_caller_running_under_set_e(estate, tmp_path):
    """Callers run `set -euo pipefail`; a non-zero internal step must not kill them."""
    origin, checkout = estate
    git(checkout, "remote", "set-url", "origin", str(tmp_path / "gone"))
    script = (
        f'set -euo pipefail\n. "{HELPER}"\nactivate_checkout "{checkout}"\necho REACHED_THE_END\n'
    )
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env={**os.environ, **GIT_ENV}
    )

    assert result.returncode == 0
    assert "REACHED_THE_END" in result.stdout


# ── dependency sync, keyed on the manifest actually moving ─────────────────────────────────────


def stub_uv(tmp_path: Path, *, succeed: bool = True) -> dict[str, str]:
    """A `uv` on PATH that records that it ran, so the control can tell invoked from not."""
    bindir = tmp_path / "stubbin"
    bindir.mkdir(exist_ok=True)
    marker = tmp_path / "uv-ran"
    (bindir / "uv").write_text(
        f'#!/bin/bash\necho "$@" >> "{marker}"\nexit {0 if succeed else 1}\n'
    )
    (bindir / "uv").chmod(0o755)
    return {"PATH": f"{bindir}:{os.environ['PATH']}", "_MARKER": str(marker)}


def test_a_pull_that_moves_the_manifest_syncs_dependencies(estate, tmp_path):
    origin, checkout = estate
    (checkout / ".venv").mkdir()
    advance_origin(origin, tmp_path, name="pyproject.toml", body="[project]\nname='x'\n")
    env = stub_uv(tmp_path)

    result = run_helper(checkout, env=env)

    assert result.returncode == 0
    assert "dependencies synced" in result.stdout
    assert Path(env["_MARKER"]).exists()
    assert "sync" in Path(env["_MARKER"]).read_text()


def test_a_pull_that_leaves_the_manifest_alone_does_not_sync(estate, tmp_path):
    """`uv sync` on every pull would be cost for nothing; nothing installed can have changed."""
    origin, checkout = estate
    (checkout / ".venv").mkdir()
    advance_origin(origin, tmp_path, name="docs/note.md", body="prose\n")
    env = stub_uv(tmp_path)

    result = run_helper(checkout, env=env)

    assert result.returncode == 0
    assert "activated" in result.stdout
    assert "dependencies synced" not in result.stdout
    assert not Path(env["_MARKER"]).exists()


def test_a_failed_sync_is_loud_and_still_does_not_fail_the_caller(estate, tmp_path):
    origin, checkout = estate
    (checkout / ".venv").mkdir()
    advance_origin(origin, tmp_path, name="uv.lock", body="version = 1\n")
    env = stub_uv(tmp_path, succeed=False)

    result = run_helper(checkout, env=env)

    assert result.returncode == 0
    assert "SYNC FAILED" in result.stderr


def test_a_checkout_with_no_venv_never_reaches_uv(estate, tmp_path):
    origin, checkout = estate
    advance_origin(origin, tmp_path, name="pyproject.toml", body="[project]\nname='x'\n")
    env = stub_uv(tmp_path)

    result = run_helper(checkout, env=env)

    assert result.returncode == 0
    assert not Path(env["_MARKER"]).exists()


# ── the re-exec, which is what makes the pulling run the running run ──────────────────────────


def caller_script(checkout: Path, tmp_path: Path) -> Path:
    """A launcher shaped like the real ones: it lives inside the checkout it activates."""
    path = checkout / "launcher.sh"
    log = tmp_path / "passes"
    path.write_text(
        "#!/bin/bash\n"
        "set -uo pipefail\n"
        f'. "{HELPER}"\n'
        f'activate_checkout "{checkout}" "$0" "$@"\n'
        f'echo "pass reexec=${{SDS_ACTIVATION_REEXEC:-0}} args=$*" >> "{log}"\n'
    )
    path.chmod(0o755)
    return path


def test_a_pull_reruns_the_caller_once_on_the_code_it_just_activated(estate, tmp_path):
    origin, checkout = estate
    advance_origin(origin, tmp_path)
    launcher = caller_script(checkout, tmp_path)

    result = subprocess.run(
        ["bash", str(launcher), "--submit"],
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
    )
    passes = (tmp_path / "passes").read_text().splitlines()

    assert result.returncode == 0
    assert "re-running launcher.sh" in result.stdout
    # Exactly one re-exec: the body runs once, in the second pass, with its arguments intact.
    assert passes == ["pass reexec=1 args=--submit"]


def test_a_current_checkout_does_not_rerun_the_caller(estate, tmp_path):
    _, checkout = estate
    launcher = caller_script(checkout, tmp_path)

    result = subprocess.run(
        ["bash", str(launcher)], capture_output=True, text=True, env={**os.environ, **GIT_ENV}
    )
    passes = (tmp_path / "passes").read_text().splitlines()

    assert result.returncode == 0
    assert "re-running" not in result.stdout
    assert passes == ["pass reexec=0 args="]


def test_activating_a_checkout_the_caller_does_not_live_in_never_reruns(estate, tmp_path):
    """Callers pass no self-path when they activate a checkout they only read."""
    origin, checkout = estate
    advance_origin(origin, tmp_path)

    result = run_helper(checkout)

    assert result.returncode == 0
    assert "activated" in result.stdout
    assert "re-running" not in result.stdout
