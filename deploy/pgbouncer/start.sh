#!/bin/sh
set -eu

# The application's DSN and PgBouncer configuration must represent the same
# password without URL or configuration-file escaping ambiguities.
case "${POSTGRES_PASSWORD:-}" in
  ''|*[!a-zA-Z0-9]*) echo 'POSTGRES_PASSWORD must contain only letters and digits' >&2; exit 1 ;;
esac
if [ "${#POSTGRES_PASSWORD}" -lt 32 ]; then
  echo 'POSTGRES_PASSWORD must contain at least 32 characters' >&2
  exit 1
fi
umask 077
mkdir -p /tmp/rpg-pgbouncer
printf '"rpg" "%s"\n' "$POSTGRES_PASSWORD" > /tmp/rpg-pgbouncer/userlist.txt
cat > /tmp/rpg-pgbouncer/pgbouncer.ini <<'EOF'
[databases]
rpg = host=postgres port=5432 dbname=rpg
[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = scram-sha-256
auth_file = /tmp/rpg-pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 20
min_pool_size = 5
reserve_pool_size = 5
reserve_pool_timeout = 3
server_idle_timeout = 600
ignore_startup_parameters = extra_float_digits
EOF
exec pgbouncer /tmp/rpg-pgbouncer/pgbouncer.ini
