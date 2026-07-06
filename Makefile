# Pin a Python >=3.11 for our module commands. `tomllib` (used by the governance/
# manifest/allowlist modules) is stdlib only on 3.11+; a bare `python3` can resolve
# to Apple's /usr/bin 3.9 (no tomllib). Prefer the repo .venv via its absolute path
# (survives a hostile PATH), then python3.12 / python3.11 / python3 — each verified.
# Mirrors the interpreter pin in scripts/security-scan.sh.
PYBIN := $(shell for c in "$(CURDIR)/.venv/bin/python" python3.12 python3.11 python3; do \
	if command -v "$$c" >/dev/null 2>&1 && "$$c" -c 'import sys, tomllib; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then command -v "$$c"; break; fi; \
	done)
ifeq ($(strip $(PYBIN)),)
$(error No Python >=3.11 with tomllib found (tried .venv, python3.12, python3.11, python3). Create the venv with: python3.12 -m venv .venv)
endif
PY := PYTHONPATH=src $(PYBIN)

.PHONY: install verify ownership strip-stanzas test check check-integration

check:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m pyright
	$(PY) -m pytest -q

check-integration:
	@if [ -z "$$FACTORY_TEST_DSN" ]; then echo "FACTORY_TEST_DSN is required for check-integration"; exit 2; fi
	$(PY) -m pytest -q -m integration

install:  ## deploy artifacts, reconcile control-plane, regenerate OWNERSHIP.md, then verify
	$(PY) -m security_scan.governance deploy
	$(PY) -m security_scan.governance ownership
	$(PY) -m security_scan.governance verify

ownership:  ## regenerate ~/.claude/OWNERSHIP.md + ensure consumer .bws-secrets.toml
	$(PY) -m security_scan.governance ownership

verify:   ## assert deployed artifacts + source headers + OWNERSHIP.md match the map
	$(PY) -m security_scan.governance verify

strip-stanzas:  ## one-shot migration: remove generated governance stanzas from all repos' CLAUDE.md
	$(PY) -m security_scan.governance strip-stanzas

test:
	$(PY) -m pytest -q
