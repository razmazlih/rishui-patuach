#!/bin/sh
# Optional native PostgreSQL fallback for macOS when Docker is unavailable.
set -eu
if [ -z "${PG_BIN:-}" ]; then
  if [ -d /opt/homebrew/opt/postgresql@14/bin ]; then
    PG_BIN=/opt/homebrew/opt/postgresql@14/bin
  elif command -v pg_config >/dev/null 2>&1; then
    PG_BIN=$(pg_config --bindir)
  else
    echo 'Install PostgreSQL or set PG_BIN to its bin directory.' >&2
    exit 1
  fi
fi
cluster="${DATA_DIR:-./data}/work/postgres"
mkdir -p "$cluster"
if [ ! -f "$cluster/PG_VERSION" ]; then
  "$PG_BIN/initdb" -D "$cluster" -A trust --encoding=UTF8 --no-locale >/dev/null
fi
if ! "$PG_BIN/pg_ctl" -D "$cluster" status >/dev/null 2>&1; then
  "$PG_BIN/pg_ctl" -D "$cluster" -l "$cluster/server.log" -o '-h 127.0.0.1 -p 55432 -k /tmp' start
fi
# This isolated loopback-only cluster is for development; never use it for hosting.
"$PG_BIN/psql" -h 127.0.0.1 -p 55432 -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='vehicle'" | grep -q '^1$' || \
  "$PG_BIN/psql" -h 127.0.0.1 -p 55432 -d postgres -c "CREATE ROLE vehicle LOGIN PASSWORD 'vehicle_local';"
"$PG_BIN/psql" -h 127.0.0.1 -p 55432 -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='vehicles'" | grep -q '^1$' || \
  "$PG_BIN/createdb" -h 127.0.0.1 -p 55432 -O vehicle vehicles
