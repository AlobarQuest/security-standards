PY := PYTHONPATH=src python3

.PHONY: install sync verify test

install:  ## deploy manifest artifacts to ~/.claude/{bin,hooks}
	$(PY) -m security_scan.governance deploy

sync:     ## write governance stanzas into each repo's CLAUDE.md
	$(PY) -m security_scan.governance sync

verify:   ## assert deployed artifacts + stanzas match the manifest
	$(PY) -m security_scan.governance verify

test:
	$(PY) -m pytest -q
