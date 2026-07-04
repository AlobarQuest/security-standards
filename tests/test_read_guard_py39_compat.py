"""The read-guard is deployed as a Claude Code PreToolUse hook, executed by the
ambient ``python3`` — which under macOS launchd (the nightly scan, and hook
invocation) resolves to the *system* interpreter, Python 3.9, below the package's
3.12 dev floor. If a read_guard module fails to import there, the hook crashes,
emits nothing, and — being fail-open — silently stops protecting reads (observed:
``readguard.health`` canary FAIL, "shim emitted no deny decision, stdout=''").

So the read_guard subpackage carries a stricter contract than the rest of the
package: it MUST import under Python 3.9. This guards the whole class of bug
(e.g. a PEP 604 ``X | None`` union evaluated at import time)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_SRC = str(Path(__file__).resolve().parent.parent / "src")
_MODULES = [
    "security_scan.read_guard.core",
    "security_scan.read_guard.hook",
    "security_scan.read_guard.audit",
    "security_scan.read_guard.selfcheck",
]


def _find_py39():
    """Locate a real Python 3.9 interpreter (the deploy-time interpreter), or None."""
    for cand in ("python3.9", "/usr/bin/python3"):
        path = shutil.which(cand) or (cand if Path(cand).exists() else None)
        if not path:
            continue
        try:
            out = subprocess.run(
                [path, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except OSError:
            continue
        if out.returncode == 0 and out.stdout.strip() == "3.9":
            return path
    return None


@pytest.mark.parametrize("module", _MODULES)
def test_read_guard_module_imports_under_python39(module):
    py39 = _find_py39()
    if not py39:
        pytest.skip("no Python 3.9 interpreter available to test hook-deploy import safety")
    r = subprocess.run(
        [py39, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONPATH": _SRC},
    )
    assert r.returncode == 0, (
        f"{module} fails to import under {py39} (Python 3.9) — the read-guard hook "
        f"would crash and fail open here:\n{r.stderr}"
    )
