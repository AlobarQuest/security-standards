# 2026-07-06: Factory Store Integration Gate

**Domain:** technical
**Status:** decided

## Context

The pre-Phase-4 foundation cleanliness pass found that `security-standards` default pytest output
included skipped `FACTORY_TEST_DSN` factory-store tests. The default foundation gate must be
warning-clean and skip-clean without requiring live or production credentials.

## Decision

`FACTORY_TEST_DSN` factory-store tests are integration-only. They are excluded from the default
`make check` gate and exposed through the explicit `make check-integration` target, which requires
a disposable PostgreSQL DSN.

## Rationale

The factory-store tests validate real projection-store behavior and need an external database. Keeping
them in default pytest as skips made the trust substrate noisy and ambiguous; requiring a live DSN in
the default gate would make normal local and CI checks depend on external state. An explicit integration
target preserves coverage while keeping the default gate deterministic.

## Implications

Default checks should not directly import optional integration dependencies such as `psycopg` from
default-scanned files. Use a DSN-gated integration target and dynamic imports inside that path so
foundation code scans remain clean even when integration dependencies are absent.
