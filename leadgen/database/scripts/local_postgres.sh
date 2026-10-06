#!/usr/bin/env bash
# Throwaway PostgreSQL 16 for development and tests, without Docker.
#
#   database/scripts/local_postgres.sh start     # init (first run) + start + create db
#   database/scripts/local_postgres.sh dsn       # print the superuser DSN
#   database/scripts/local_postgres.sh psql      # open a psql shell
#   database/scripts/local_postgres.sh stop | status | destroy
#
# Data lives in .data/pg (git-ignored). Listens on 127.0.0.1 only.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PGDATA="${LEADINTEL_PGDATA:-$ROOT/.data/pg}"
PGPORT="${LEADINTEL_PGPORT:-54329}"
DB_NAME="${LEADINTEL_PGDATABASE:-leadintel}"

if command -v pg_config >/dev/null 2>&1 && [ -x "$(pg_config --bindir)/initdb" ]; then
  PG_BIN="$(pg_config --bindir)"
else
  PG_BIN="$(find /usr/lib/postgresql -mindepth 2 -maxdepth 2 -type d -name bin 2>/dev/null | sort -V | tail -1 || true)"
fi
[ -x "${PG_BIN:-}/initdb" ] || { echo "PostgreSQL server binaries not found (install postgresql-16)" >&2; exit 1; }

# initdb/postgres refuse to run as root; use the postgres system user when we are root.
as_db_user() {
  if [ "$(id -u)" -eq 0 ]; then
    runuser -u postgres -- "$@"
  else
    "$@"
  fi
}

dsn() { echo "postgresql://postgres@127.0.0.1:${PGPORT}/${DB_NAME}"; }

start() {
  if [ ! -s "$PGDATA/PG_VERSION" ]; then
    mkdir -p "$PGDATA"
    [ "$(id -u)" -eq 0 ] && chown -R postgres:postgres "$(dirname "$PGDATA")"
    as_db_user "$PG_BIN/initdb" -D "$PGDATA" -U postgres --auth=trust --encoding=UTF8 \
      --locale=C.UTF-8 >/dev/null
  fi
  if ! as_db_user "$PG_BIN/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
    as_db_user "$PG_BIN/pg_ctl" -D "$PGDATA" -w -l "$PGDATA/server.log" \
      -o "-p ${PGPORT} -c listen_addresses=127.0.0.1 -k ${PGDATA}" start >/dev/null
  fi
  if ! "$PG_BIN/psql" -h 127.0.0.1 -p "$PGPORT" -U postgres -Atc \
      "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" postgres | grep -q 1; then
    "$PG_BIN/createdb" -h 127.0.0.1 -p "$PGPORT" -U postgres "$DB_NAME"
  fi
  echo "PostgreSQL running: $(dsn)"
}

case "${1:-}" in
  start) start ;;
  stop) as_db_user "$PG_BIN/pg_ctl" -D "$PGDATA" -m fast stop ;;
  status) as_db_user "$PG_BIN/pg_ctl" -D "$PGDATA" status ;;
  dsn) dsn ;;
  psql) exec "$PG_BIN/psql" "$(dsn)" ;;
  destroy)
    as_db_user "$PG_BIN/pg_ctl" -D "$PGDATA" -m immediate stop >/dev/null 2>&1 || true
    rm -rf "$PGDATA"
    echo "removed $PGDATA"
    ;;
  *) echo "usage: $0 start|stop|status|dsn|psql|destroy" >&2; exit 2 ;;
esac
