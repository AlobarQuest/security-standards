"""Secret shapes are built at runtime, so no literal secret sits in this file or its diff."""

import pytest

from security_scan.token_shapes import BWS_TOKEN_RX, SECRET_SHAPES

_UUID = "-".join(("1" * 8, "2" * 4, "3" * 4, "4" * 4, "5" * 12))
_OPENAI = "OpenAI or Anthropic API key"
_SK = "s" + "k-" + "a" * 24

CAUGHT = [
    ("private key", "-----BEGIN " + "RSA PRIVATE KEY-----"),
    ("private key", "-----BEGIN " + "PRIVATE KEY-----"),
    ("AWS access key", "key = 'AKIA" + "Q" * 16 + "'"),
    ("GitHub token", "token: gh" + "p_" + "a" * 36),
    ("GitHub token", "token: gh" + "s_" + "a" * 40),
    ("GitHub token", "github" + "_pat_" + "a" * 22),
    ("Slack token", "xox" + "b-" + "1" * 12),
    (_OPENAI, "OPENAI=" + _SK),
    (_OPENAI, "s" + "k-ant-" + "a" * 24),
    (_OPENAI, "MYKEY" + _SK),
    (_OPENAI, "x_" + _SK),
    ("BWS access token", "0." + _UUID + "." + "a" * 30 + ":" + "b" * 12),
]


def _kinds(text: str) -> list[str]:
    return [kind for kind, shape in SECRET_SHAPES if shape.search(text)]


@pytest.mark.parametrize(("kind", "line"), CAUGHT, ids=[f"shape-{i}" for i in range(len(CAUGHT))])
def test_shape_caught(kind: str, line: str):
    assert _kinds(line) == [kind]


@pytest.mark.parametrize(
    "line",
    [
        "risk-based-authentication-flow-handler = 1",
        "disk-cache-invalidation-strategy",
        "task-" + _SK,
        "v2" + _SK,
        "AKIA" + "q" * 16,
        "-----BEGIN PUBLIC KEY-----",
        "version = 10.0.1",
    ],
    ids=[
        "slug-risk",
        "slug-disk",
        "hyphen-joined",
        "digit-joined",
        "lowercase-akia",
        "public-key",
        "version",
    ],
)
def test_lookalikes_not_caught(line: str):
    assert _kinds(line) == []


def test_bws_shape_is_the_scanner_pattern():
    assert ("BWS access token", BWS_TOKEN_RX) in SECRET_SHAPES
