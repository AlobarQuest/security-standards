from security_scan import genmanifest


def test_build_enrich_map_joins_key_and_project_name_without_values():
    secrets = [
        {"id": "u1", "key": "TOKEN_A", "value": "SUPERSECRET", "projectId": "p1"},
        {"id": "u2", "key": "TOKEN_B", "value": "alsosecret", "projectId": "p2"},
    ]
    projects = [{"id": "p1", "name": "infra"}, {"id": "p2", "name": "backups"}]
    m = genmanifest.build_enrich_map(secrets, projects)
    assert m == {
        "u1": {"name": "TOKEN_A", "project": "infra"},
        "u2": {"name": "TOKEN_B", "project": "backups"},
    }
    # a scanner that leaked the secret value would itself be the leak
    assert "SUPERSECRET" not in str(m)
    assert "alsosecret" not in str(m)


def test_build_enrich_map_falls_back_to_project_id_when_name_missing():
    secrets = [{"id": "u1", "key": "T", "value": "x", "projectId": "p9"}]
    m = genmanifest.build_enrich_map(secrets, projects=[])
    assert m == {"u1": {"name": "T", "project": "p9"}}
