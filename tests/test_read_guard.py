import time as _time
import uuid
from security_scan import token_shapes
from security_scan.read_guard import core


def _synth_token() -> str:
    """Build a shape-matching token at runtime — never a literal in source."""
    return "0." + str(uuid.uuid4()) + "." + ("A" * 30)


def test_bws_token_rx_matches_synthetic_token():
    assert token_shapes.BWS_TOKEN_RX.search(_synth_token()) is not None


def test_bws_token_rx_ignores_lookalikes():
    for s in ["0.1.2", str(uuid.uuid4()), "abc123def456", "0.short.x"]:
        assert token_shapes.BWS_TOKEN_RX.search(s) is None


def test_scan_finds_token_in_plain_text():
    t = _synth_token()
    out = f"some log line\nBWS_ACCESS_TOKEN={t}\nmore\n"
    assert core.scan_for_bws(out) == [t]


def test_scan_finds_multiple_tokens():
    a, b = _synth_token(), _synth_token()
    assert set(core.scan_for_bws(f"{a} and {b}")) == {a, b}


def test_scan_finds_token_in_decoded_output():
    # simulates `base64 -d` output: the decoded value is present in the string
    t = _synth_token()
    assert core.scan_for_bws(f"decoded: {t}") == [t]


def test_scan_returns_empty_for_clean_output():
    assert core.scan_for_bws("totally clean log output\nno secrets here\n") == []


def test_scan_large_output_is_fast():
    big = ("x" * 1_000_000 + "\n") * 10  # ~10 MB, no token
    start = _time.perf_counter()
    assert core.scan_for_bws(big) == []
    assert _time.perf_counter() - start < 1.0  # well under any hook timeout


def test_known_limit_transformed_token_not_caught():
    # Token reversed before printing is intentionally NOT detected (documented).
    t = _synth_token()
    assert core.scan_for_bws(t[::-1]) == []
