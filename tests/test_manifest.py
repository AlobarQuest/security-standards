import tomllib

from security_scan import manifest


def test_referenced_uuids_follows_a_uuid_assigned_away_from_the_bws_call(git_repo):
    # The launcher shape: the UUID is assigned on one line and the variable reaches `bws` later.
    git_repo.write(
        "scripts/run-lane.sh",
        'LANE_UUID="${LANE_BWS_UUID:-45eb083f-4b05-4251-924d-b46700e5a643}"\n'
        'token="$(sds_bws_value "$LANE_UUID")"\n',
    )
    git_repo.commit()
    assert manifest.referenced_uuids(git_repo.path) == {"45eb083f-4b05-4251-924d-b46700e5a643"}


def test_referenced_uuids_ignores_a_file_that_never_mentions_bws(git_repo):
    git_repo.write("app/ids.py", 'WORK_UNIT_ID = "11111111-2222-3333-4444-555555555555"\n')
    git_repo.commit()
    assert manifest.referenced_uuids(git_repo.path) == set()


def test_referenced_uuids_skips_tests_data_registry_and_the_nil_uuid(git_repo):
    line = "bws secret get {}\n"
    git_repo.write("run.sh", line.format("aaaaaaaa-1111-2222-3333-444444444444"))
    git_repo.write("tests/test_run.py", line.format("bbbbbbbb-1111-2222-3333-444444444444"))
    git_repo.write("tasks.json", line.format("cccccccc-1111-2222-3333-444444444444"))
    git_repo.write("package.yaml", line.format("dddddddd-1111-2222-3333-444444444444"))
    git_repo.write(".cred-consumers.toml", line.format("eeeeeeee-1111-2222-3333-444444444444"))
    git_repo.write("example.py", line.format("00000000-0000-0000-0000-000000000000"))
    git_repo.commit()
    assert manifest.referenced_uuids(git_repo.path) == {"aaaaaaaa-1111-2222-3333-444444444444"}


def test_parse_declared_uuids(git_repo):
    git_repo.write(
        ".bws-secrets.toml",
        '[[secret]]\nuuid = "45eb083f-4b05-4251-924d-b46700e5a643"\nname = "X"\npurpose = "p"\n',
    )
    git_repo.commit()
    assert manifest.declared_uuids(git_repo.path) == {"45eb083f-4b05-4251-924d-b46700e5a643"}


def test_diff_reports_undeclared_and_stale(git_repo):
    git_repo.write("start.sh", "bws secret get 45eb083f-4b05-4251-924d-b46700e5a643\n")
    git_repo.write(
        ".bws-secrets.toml",
        '[[secret]]\nuuid = "99999999-0000-0000-0000-000000000000"\nname="Y"\npurpose="p"\n',
    )
    git_repo.commit()
    d = manifest.diff(git_repo.path)
    assert d.undeclared == {"45eb083f-4b05-4251-924d-b46700e5a643"}
    assert d.stale == {"99999999-0000-0000-0000-000000000000"}
    assert d.manifest_exists is True


def test_environment_injection_manifest_entries_are_not_stale(git_repo):
    git_repo.write(
        ".bws-secrets.toml",
        'consumption = "coolify-env"\n\n'
        '[[secret]]\nuuid = "11111111-1111-1111-1111-111111111111"\n',
    )
    git_repo.commit()

    assert manifest.diff(git_repo.path).stale == set()


def test_referenced_uuids_excludes_docs_and_markdown(git_repo):
    # "consumes a BWS secret" means runtime code, not prose. A UUID mentioned only
    # in docs/ or a .md file is documentation, not consumption, and must not count.
    git_repo.write("run.sh", "bws secret get aaaaaaaa-1111-2222-3333-444444444444\n")
    git_repo.write("docs/plan.md", "bws secret get bbbbbbbb-1111-2222-3333-444444444444\n")
    git_repo.write("BACKUP.md", 'fetch_bws_secret "cccccccc-1111-2222-3333-444444444444"\n')
    git_repo.commit()
    found = manifest.referenced_uuids(git_repo.path)
    assert found == {"aaaaaaaa-1111-2222-3333-444444444444"}


def test_build_manifest_renders_deterministic_enriched_toml():
    toml = manifest.build_manifest(
        {"bbbbbbbb-1111-2222-3333-444444444444", "aaaaaaaa-1111-2222-3333-444444444444"},
        enrich={"aaaaaaaa-1111-2222-3333-444444444444": {"name": "TOKEN_A", "project": "proj1"}},
    )
    data = tomllib.loads(toml)
    secrets = data["secret"]
    # sorted by uuid for stable, diff-friendly output
    assert [s["uuid"] for s in secrets] == [
        "aaaaaaaa-1111-2222-3333-444444444444",
        "bbbbbbbb-1111-2222-3333-444444444444",
    ]
    assert secrets[0]["name"] == "TOKEN_A"
    assert secrets[0]["project"] == "proj1"
    # an un-enriched UUID still appears (flagged), never silently dropped
    assert "name" not in secrets[1] or secrets[1]["name"] == ""


def test_build_manifest_output_satisfies_declared_uuids(git_repo):
    refd = {"aaaaaaaa-1111-2222-3333-444444444444", "dddddddd-1111-2222-3333-444444444444"}
    git_repo.write(".bws-secrets.toml", manifest.build_manifest(refd, enrich={}))
    git_repo.commit()
    assert manifest.declared_uuids(git_repo.path) == refd
