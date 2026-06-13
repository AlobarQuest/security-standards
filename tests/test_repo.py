from security_scan import repo


def test_grep_tracked_finds_pattern_with_location(git_repo):
    git_repo.write("a.txt", "hello\nTOKEN=0.45eb083f-4b05-4251-924d-b46700e5a643.K:V==\n")
    git_repo.commit()
    hits = repo.grep_tracked(git_repo.path, r"0\.[0-9a-f-]{36}\.")
    assert len(hits) == 1
    assert hits[0].file == "a.txt" and hits[0].line == 2
    assert "0.45eb083f" in hits[0].match


def test_grep_tracked_ignores_untracked(git_repo):
    git_repo.write("tracked.txt", "clean\n")
    git_repo.commit()
    git_repo.write("untracked.txt", "0.45eb083f-4b05-4251-924d-b46700e5a643.K:V==\n")
    assert repo.grep_tracked(git_repo.path, r"0\.[0-9a-f-]{36}\.") == []


def test_grep_history_finds_removed_secret(git_repo):
    git_repo.write("a.txt", "0.45eb083f-4b05-4251-924d-b46700e5a643.K:V==\n")
    git_repo.commit("add secret")
    git_repo.write("a.txt", "clean\n")
    git_repo.commit("remove secret")
    assert repo.grep_tracked(git_repo.path, r"0\.[0-9a-f-]{36}\.") == []
    assert repo.grep_history(git_repo.path, r"0\.[0-9a-f-]{36}\.")              # still in history (non-empty)


def test_is_ignored(git_repo):
    git_repo.write(".gitignore", "*.env\n")
    git_repo.commit()
    assert repo.is_ignored(git_repo.path, "secrets.env") is True
    assert repo.is_ignored(git_repo.path, "main.py") is False


def test_is_git_repo(git_repo, tmp_path):
    assert repo.is_git_repo(git_repo.path) is True
    plain = tmp_path / "plain"
    plain.mkdir()
    assert repo.is_git_repo(plain) is False
