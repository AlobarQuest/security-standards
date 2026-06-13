from security_scan import manifest


def test_referenced_uuids_only_in_bws_context(git_repo):
    git_repo.write("start.sh",
        'fetch_bws_secret "45eb083f-4b05-4251-924d-b46700e5a643"\n'
        'UNRELATED_UUID = "11111111-2222-3333-4444-555555555555"\n')   # not a bws line
    git_repo.commit()
    found = manifest.referenced_uuids(git_repo.path)
    assert "45eb083f-4b05-4251-924d-b46700e5a643" in found
    assert "11111111-2222-3333-4444-555555555555" not in found


def test_parse_declared_uuids(git_repo):
    git_repo.write(".bws-secrets.toml",
        '[[secret]]\nuuid = "45eb083f-4b05-4251-924d-b46700e5a643"\nname = "X"\npurpose = "p"\n')
    git_repo.commit()
    assert manifest.declared_uuids(git_repo.path) == {"45eb083f-4b05-4251-924d-b46700e5a643"}


def test_diff_reports_undeclared_and_stale(git_repo):
    git_repo.write("start.sh", 'bws secret get 45eb083f-4b05-4251-924d-b46700e5a643\n')
    git_repo.write(".bws-secrets.toml",
        '[[secret]]\nuuid = "99999999-0000-0000-0000-000000000000"\nname="Y"\npurpose="p"\n')
    git_repo.commit()
    d = manifest.diff(git_repo.path)
    assert d.undeclared == {"45eb083f-4b05-4251-924d-b46700e5a643"}
    assert d.stale == {"99999999-0000-0000-0000-000000000000"}
    assert d.manifest_exists is True
