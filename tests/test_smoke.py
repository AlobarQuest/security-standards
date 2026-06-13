def test_package_imports():
    import security_scan
    assert security_scan.__version__ == "0.1.0"
