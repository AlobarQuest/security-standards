PY := PYTHONPATH=src python3

.PHONY: install verify ownership strip-stanzas test

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
