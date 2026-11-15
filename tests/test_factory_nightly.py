"""Controls for `scripts/factory-events-nightly.sh` on the database chain, and its refusal with
no switch file.

The nightly runs against stubs only: `security`, `bws`, `curl`, the venv's `python -m
factory_events`, and the observation helper. Each stub records its argv and the chain variables
it received, so the tests show which child got the password and which didn't. The script is
copied out of the repository first, because the real `observe-run.sh` beside it posts to the
orchestrator. `BWS_ACCESS_TOKEN_BROAD` is always set to a stub value, so the change-manager fetch
never reads the real Keychain.

Every stub value is obviously fake and doesn't match the BWS token shape (Infra Brain 591-593).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "factory-events-nightly.sh"

CM_SECRET_ID = "af0e4192-edc6-46ae-9e4f-b469011dbb8d"
APPEND_SECRET_ID = "2ce0dbc7-eeac-4bf0-8204-b50200c97516"
NIGHTLY_ITEM = "BWS_ACCESS_TOKEN_FACTORY_EVENTS_NIGHTLY"
STUB_BROAD = "stub-broad-identity"
STUB_NIGHTLY = "stub-nightly-identity"
STUB_PASSWORD = "stub-append-password"
STUB_BEARER = "stub-cm-bearer"
CHAIN_VARS = (
    "FACTORY_EVENTS_APPEND_PASSWORD",
    "FACTORY_EVENTS_DB_HOST",
    "FACTORY_EVENTS_DB_PORT",
    "FACTORY_EVENTS_DB_NAME",
)
SWITCH = (
    "FACTORY_EVENTS_DB_HOST=100.64.0.1\n"
    "FACTORY_EVENTS_DB_PORT=15432\n"
    "FACTORY_EVENTS_DB_NAME=postgres\n"
)
# The script's own shell variables for the settings, the token and the password.
LOCAL_VARS = (
    "CHAIN_DB_HOST",
    "CHAIN_DB_PORT",
    "CHAIN_DB_NAME",
    "NIGHTLY_IDENTITY",
    "CHAIN_PASSWORD",
)
PING_URL = "https://hc.invalid/ping/nightly"

# One recorder for every stub: it appends {tool, argv, chain vars, BWS token} to calls.jsonl,
# then acts as that tool, steered by control.json.
RECORDER = r"""
import json, os, sys
from pathlib import Path

tool = os.environ.get("STUB_TOOL") or Path(sys.argv[0]).name
rec = Path(os.environ["STUB_RECORD_DIR"])
control = json.loads((rec / "control.json").read_text())
argv = sys.argv[1:]
chain = {k: os.environ[k] for k in %(chain_vars)r if k in os.environ}
local = {k: os.environ[k] for k in %(local_vars)r if k in os.environ}
with (rec / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"tool": tool, "argv": argv, "chain": chain, "local": local,
                         "bws_token": os.environ.get("BWS_ACCESS_TOKEN")}) + "\n")

if tool == "security":
    if control.get("no_item"):
        sys.exit(44)
    print(%(nightly)r)
elif tool == "bws":
    values = {%(cm_id)r: %(bearer)r}
    if not control.get("empty_password"):
        values[%(append_id)r] = %(password)r
    secret_id = argv[2]
    if secret_id not in values:
        sys.exit(1)
    print(json.dumps({"value": values[secret_id]}))
elif tool == "curl":
    pass
elif tool == "python":
    command = argv[2]
    verifies = sum(1 for line in (rec / "calls.jsonl").read_text().splitlines()
                   if json.loads(line)["argv"][2:3] == ["verify"])
    if command == "verify" and verifies == control.get("fail_verify_call"):
        print("VERIFY FAIL: stub", file=sys.stderr)
        sys.exit(1)
    if command == "adapt":
        print("high-power: 2 events appended")
        print("change-manager: 1 events appended")
    elif command == "verify":
        if "--against-anchor" in argv or "--record-anchor" in argv:
            print("anchor ok: seq 4 present")
        print("chain ok: 7 events, head stubhead")
"""

OBSERVE_STUB = """\
observe_init() { :; }
observe_fact() { echo "$1=$2" >> "$STUB_RECORD_DIR/facts.txt"; }
observe_report() { echo "rc=$1 stage=${3:-}" >> "$STUB_RECORD_DIR/facts.txt"; }
"""


class Nightly:
    """A temporary HOME, stub tools, and one way to run the script against them."""

    def __init__(self, tmp_path: Path) -> None:
        self.home = tmp_path / "home"
        self.rec = tmp_path / "rec"
        self.stubs = tmp_path / "stubs"
        self.bin = tmp_path / "bin"
        self.log = tmp_path / "factory-events.log"
        for path in (self.home / ".factory", self.rec, self.stubs, self.bin):
            path.mkdir(parents=True)
        self.control: dict = {}

        recorder = self.stubs / "recorder.py"
        recorder.write_text(
            RECORDER
            % {
                "chain_vars": CHAIN_VARS,
                "local_vars": LOCAL_VARS,
                "nightly": STUB_NIGHTLY,
                "cm_id": CM_SECRET_ID,
                "bearer": STUB_BEARER,
                "append_id": APPEND_SECRET_ID,
                "password": STUB_PASSWORD,
            }
        )
        for tool in ("security", "bws", "curl"):
            self._stub(self.stubs / tool, tool, recorder)
        venv_python = self.home / "Projects/security-standards/.venv-events/bin/python"
        venv_python.parent.mkdir(parents=True)
        self._stub(venv_python, "python", recorder)

        shutil.copy(SCRIPT, self.bin / SCRIPT.name)
        (self.bin / "observe-run.sh").write_text(OBSERVE_STUB)
        (self.home / ".factory/env").write_text(
            f"CM_BASE_URL=https://cm.invalid\nFACTORY_HC_PING_URL={PING_URL}\n"
        )

    @staticmethod
    def _stub(path: Path, tool: str, recorder: Path) -> None:
        path.write_text(
            f'#!/bin/bash\nSTUB_TOOL={tool} exec "{sys.executable}" -I "{recorder}" "$@"\n'
        )
        path.chmod(0o755)

    @property
    def switch(self) -> Path:
        return self.home / ".factory/chain-db.env"

    def run(self) -> subprocess.CompletedProcess[str]:
        (self.rec / "control.json").write_text(json.dumps(self.control))
        env = {
            "PATH": f"{self.stubs}:/usr/bin:/bin",
            "HOME": str(self.home),
            "FACTORY_EVENTS_LOG": str(self.log),
            "FACTORY_EVENTS_SECURITY_BIN": str(self.stubs / "security"),
            "BWS_ACCESS_TOKEN_BROAD": STUB_BROAD,
            "STUB_RECORD_DIR": str(self.rec),
        }
        return subprocess.run(
            ["/bin/bash", str(self.bin / SCRIPT.name)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def calls(self, tool: str | None = None) -> list[dict]:
        path = self.rec / "calls.jsonl"
        if not path.exists():
            return []
        calls = [json.loads(line) for line in path.read_text().splitlines()]
        return [c for c in calls if tool is None or c["tool"] == tool]

    def commands(self) -> list[list[str]]:
        """The argv after `-m factory_events` of every venv python call, in order."""
        return [c["argv"][2:] for c in self.calls("python")]

    def pings(self) -> list[str]:
        """The URL each curl call pinged."""
        return [next(a for a in c["argv"] if a.startswith(PING_URL)) for c in self.calls("curl")]

    def facts(self) -> dict[str, str]:
        lines = (self.rec / "facts.txt").read_text().splitlines()
        return dict(line.split("=", 1) for line in lines if not line.startswith("rc="))


@pytest.fixture
def nightly(tmp_path: Path) -> Nightly:
    return Nightly(tmp_path)


def assert_failed(nightly: Nightly, result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 1, result.stdout + result.stderr
    assert nightly.pings()[-1] == f"{PING_URL}/fail"


# ── No switch file: the run fails ─────────────────────────────────────────────────────────


def test_file_absent_fails_by_name_and_runs_nothing(nightly: Nightly) -> None:
    result = nightly.run()

    assert_failed(nightly, result)
    assert nightly.commands() == []
    assert nightly.calls("security") == []
    assert APPEND_SECRET_ID not in [c["argv"][2] for c in nightly.calls("bws")]
    assert "missing " + str(nightly.switch) in nightly.log.read_text()
    assert nightly.facts()["shipped"] == "0"


# ── Database mode: the switch file is present ─────────────────────────────────────────────


def test_file_present_verifies_adapts_and_records_the_anchor_without_ship(
    nightly: Nightly,
) -> None:
    nightly.switch.write_text(SWITCH)

    result = nightly.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert nightly.commands() == [
        ["verify", "--against-anchor"],
        ["adapt", "--source", "all"],
        ["verify", "--record-anchor"],
    ]
    assert nightly.pings() == [f"{PING_URL}/start", PING_URL]
    success = nightly.calls("curl")[-1]["argv"]
    assert "chain ok: 7 events, head stubhead" in success[success.index("--data-raw") + 1]
    facts = nightly.facts()
    assert facts["shipped"] == "0"
    assert facts["chain_events"] == "7"
    assert facts["anchor_verified"] == "true"


def test_file_present_fetches_the_password_through_the_nightly_item_only(
    nightly: Nightly,
) -> None:
    nightly.switch.write_text(SWITCH)

    nightly.run()

    security = nightly.calls("security")
    assert len(security) == 1
    assert security[0]["argv"][security[0]["argv"].index("-a") + 1] == NIGHTLY_ITEM
    tokens = {c["argv"][2]: c["bws_token"] for c in nightly.calls("bws")}
    assert tokens == {CM_SECRET_ID: STUB_BROAD, APPEND_SECRET_ID: STUB_NIGHTLY}


def test_file_present_passes_the_chain_variables_to_the_python_children_only(
    nightly: Nightly,
) -> None:
    nightly.switch.write_text(SWITCH)

    nightly.run()

    expected = {
        "FACTORY_EVENTS_APPEND_PASSWORD": STUB_PASSWORD,
        "FACTORY_EVENTS_DB_HOST": "100.64.0.1",
        "FACTORY_EVENTS_DB_PORT": "15432",
        "FACTORY_EVENTS_DB_NAME": "postgres",
    }
    assert all(c["chain"] == expected for c in nightly.calls("python"))
    others = [c for c in nightly.calls() if c["tool"] != "python"]
    assert others and all(c["chain"] == {} for c in others)


def test_file_present_keeps_the_password_and_token_out_of_argv_and_the_log(
    nightly: Nightly,
) -> None:
    nightly.switch.write_text(SWITCH)

    result = nightly.run()

    assert all(c["chain"] for c in nightly.calls("python")), "no child received the password"
    argv = json.dumps([c["argv"] for c in nightly.calls()])
    written = nightly.log.read_text() + result.stdout + result.stderr
    for secret in (STUB_PASSWORD, STUB_NIGHTLY):
        assert secret not in argv
        assert secret not in written


def test_file_present_and_item_missing_fails(nightly: Nightly) -> None:
    nightly.switch.write_text(SWITCH)
    nightly.control["no_item"] = True

    result = nightly.run()

    assert_failed(nightly, result)
    assert APPEND_SECRET_ID not in [c["argv"][2] for c in nightly.calls("bws")]
    assert nightly.commands() == []
    assert "BWS_ACCESS_TOKEN_FACTORY_EVENTS_NIGHTLY" in nightly.log.read_text()


def test_file_present_and_password_empty_fails(nightly: Nightly) -> None:
    nightly.switch.write_text(SWITCH)
    nightly.control["empty_password"] = True

    result = nightly.run()

    assert_failed(nightly, result)
    assert nightly.commands() == []


def test_first_verify_failure_stops_before_adapt(nightly: Nightly) -> None:
    nightly.switch.write_text(SWITCH)
    nightly.control["fail_verify_call"] = 1

    result = nightly.run()

    assert_failed(nightly, result)
    assert nightly.commands() == [["verify", "--against-anchor"]]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(SWITCH + "FACTORY_EVENTS_DB_USER=someone\n", id="unknown-key"),
        pytest.param(SWITCH.replace("FACTORY_EVENTS_DB_PORT=15432\n", ""), id="missing-key"),
        pytest.param(SWITCH + "FACTORY_EVENTS_DB_NAME=other\n", id="duplicate-key"),
        pytest.param(SWITCH.replace("=postgres", '="postgres"'), id="quoted-value"),
        pytest.param(SWITCH.replace("=postgres", "="), id="empty-value"),
        pytest.param(SWITCH + "\n", id="blank-line"),
    ],
)
def test_a_malformed_switch_file_fails(nightly: Nightly, content: str) -> None:
    nightly.switch.write_text(content)

    result = nightly.run()

    assert_failed(nightly, result)
    assert nightly.calls("security") == []
    assert nightly.commands() == []


def test_a_directory_at_the_switch_path_fails(nightly: Nightly) -> None:
    nightly.switch.mkdir()

    result = nightly.run()

    assert_failed(nightly, result)
    assert nightly.commands() == []


def test_a_symlink_at_the_switch_path_fails(nightly: Nightly, tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.env"
    target.write_text(SWITCH)
    os.symlink(target, nightly.switch)

    result = nightly.run()

    assert_failed(nightly, result)
    assert nightly.commands() == []


def test_an_unreadable_switch_file_fails(nightly: Nightly) -> None:
    nightly.switch.write_text(SWITCH)
    nightly.switch.chmod(0)

    result = nightly.run()

    assert_failed(nightly, result)
    assert "chain-db.env is not readable" in nightly.log.read_text()
    assert nightly.commands() == []


def test_a_malformed_line_never_reaches_the_log(nightly: Nightly) -> None:
    nightly.switch.write_text(SWITCH + "pasted-secret-value\n")

    result = nightly.run()

    assert_failed(nightly, result)
    assert "pasted-secret-value" not in nightly.log.read_text()


def test_names_the_env_file_exports_never_carry_the_password(nightly: Nightly) -> None:
    env_file = nightly.home / ".factory/env"
    env_file.write_text(
        env_file.read_text() + "".join(f"{name}=placeholder\n" for name in LOCAL_VARS)
    )
    nightly.switch.write_text(SWITCH)

    result = nightly.run()

    assert result.returncode == 0, result.stdout + result.stderr
    # Children before the switch see the env file's own placeholders, as on main; none sees
    # a value this script assigned.
    seen = {value for c in nightly.calls() for value in c["local"].values()}
    assert seen <= {"placeholder"}
    assert all(c["local"] == {} for c in nightly.calls("python"))
