#!/usr/bin/env bash
# Run the integration tests (`pytest -m integration`) against a disposable Postgres.
#
# With FACTORY_TEST_DSN set (CI's service container), use it. Without it, start a throwaway
# postgres:16-alpine container on a random 127.0.0.1 port with a random password, run the
# tests, and remove the container on every exit path. The DSN is never printed.
#
# Never point FACTORY_TEST_DSN at a database you'd keep: the tests drop tables and create
# databases and roles. Usage (from the Makefile): PYBIN=<python> scripts/check-integration.sh
set -euo pipefail

PYBIN="${PYBIN:?PYBIN is required}"
run_tests() { PYTHONPATH=src "$PYBIN" -m pytest -q -m integration "$@"; }

if [ -n "${FACTORY_TEST_DSN:-}" ]; then
    run_tests "$@"
    exit
fi

command -v docker >/dev/null 2>&1 || { echo "check-integration: docker not found"; exit 1; }
NAME="factory-events-it-$$-$RANDOM"
POSTGRES_PASSWORD="$(openssl rand -hex 16)"
export POSTGRES_PASSWORD  # passed by name, so the value stays out of docker's argv
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

docker run -d --rm --name "$NAME" -e POSTGRES_PASSWORD -p 127.0.0.1::5432 \
    postgres:16-alpine >/dev/null
PORT="$(docker port "$NAME" 5432/tcp | head -n1 | sed 's/.*://')"

for _ in $(seq 1 60); do
    if docker exec "$NAME" pg_isready -q -U postgres -h 127.0.0.1; then break; fi
    sleep 1
done
docker exec "$NAME" pg_isready -q -U postgres -h 127.0.0.1 \
    || { echo "check-integration: the disposable Postgres didn't start"; exit 1; }

FACTORY_TEST_DSN="postgresql://postgres:${POSTGRES_PASSWORD}@127.0.0.1:${PORT}/postgres" \
    run_tests "$@"
