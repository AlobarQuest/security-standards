import re
import uuid
from security_scan import token_shapes


def _synth_token() -> str:
    """Build a shape-matching token at runtime — never a literal in source."""
    return "0." + str(uuid.uuid4()) + "." + ("A" * 30)


def test_bws_token_rx_matches_synthetic_token():
    assert token_shapes.BWS_TOKEN_RX.search(_synth_token()) is not None


def test_bws_token_rx_ignores_lookalikes():
    for s in ["0.1.2", str(uuid.uuid4()), "abc123def456", "0.short.x"]:
        assert token_shapes.BWS_TOKEN_RX.search(s) is None
