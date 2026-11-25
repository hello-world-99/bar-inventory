#!/bin/sh
# Backups for the bar inventory database (architecture section 9). Runs inside the `backup` container.
#
#   pgtool.sh daemon            dump every day at BACKUP_AT (and on start if the newest dump is older than a day)
#   pgtool.sh dump              make one dump now
#   pgtool.sh list              list dumps
#   pgtool.sh verify FILE       restore FILE into a scratch database, print row counts, drop it
#   pgtool.sh restore FILE --yes
#                               restore FILE into a new database and swap it in; the current database is
#                               kept as <db>_before_<timestamp>. Stop the backend first (see README).
set -eu

DIR=/backups
DB="${PGDATABASE:?}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
KEEP_MIN="${BACKUP_KEEP_MIN:-7}"
AT="${BACKUP_AT:-04:00}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*"; }
psql_admin() { psql -X -q -v ON_ERROR_STOP=1 -d postgres "$@"; }

dump() {
  ts=$(date '+%Y%m%d-%H%M%S')
  out="$DIR/$DB-$ts.dump"
  tmp="$out.partial"
  pg_dump -Fc -Z 6 -f "$tmp" "$DB"
  pg_restore --list "$tmp" >/dev/null # readable archive, or fail before it counts as a backup
  mv "$tmp" "$out"
  log "dump ok: $(basename "$out") ($(du -h "$out" | cut -f1))"
  rotate
}

# Delete dumps older than KEEP_DAYS, but always keep the newest KEEP_MIN.
rotate() {
  ls -1t "$DIR"/"$DB"-*.dump 2>/dev/null | tail -n +"$((KEEP_MIN + 1))" | while read -r f; do
    if [ -n "$(find "$f" -mtime +"$KEEP_DAYS")" ]; then
      rm -f "$f" && log "rotated: $(basename "$f")"
    fi
  done
  # only stale leftovers: a dump running in parallel (manual + scheduled) keeps its own .partial
  find "$DIR" -name '*.partial' -mmin +60 -exec rm -f {} + 2>/dev/null || true
}

newest() { ls -1t "$DIR"/"$DB"-*.dump 2>/dev/null | head -n 1; }

daemon() {
  case "$AT" in
    [01][0-9]:[0-5][0-9] | 2[0-3]:[0-5][0-9]) ;;
    *) log "BACKUP_AT must be HH:MM, 24-hour, e.g. 04:00 (got '$AT')"; exit 1 ;;
  esac
  log "backup daemon: daily at $AT ($(date +%Z)), keep $KEEP_DAYS days (at least $KEEP_MIN dumps), into $DIR"
  until pg_isready -q; do sleep 2; done
  n=$(newest)
  if [ -z "$n" ] || [ -n "$(find "$n" -mmin +1440)" ]; then dump || log "dump FAILED"; fi
  last=""
  while true; do
    now=$(date '+%H:%M')
    today=$(date '+%Y%m%d')
    if [ "$now" = "$AT" ] && [ "$last" != "$today" ]; then
      dump || log "dump FAILED"
      last=$today
    fi
    sleep 20
  done
}

restore_into() { # FILE TARGETDB
  psql_admin -c "DROP DATABASE IF EXISTS \"$2\""
  psql_admin -c "CREATE DATABASE \"$2\""
  pg_restore --no-owner --exit-on-error -d "$2" "$1"
}

counts() { # DB
  psql -X -q -t -A -F ' ' -d "$1" -c "
    select 'users', count(*) from users union all
    select 'products', count(*) from products union all
    select 'locations', count(*) from locations union all
    select 'documents', count(*) from stock_documents union all
    select 'movements', count(*) from stock_movements union all
    select 'inventories', count(*) from inventories union all
    select 'balance_mismatches', count(*) from (
      select b.product_id, b.location_id from stock_balances b
      left join stock_movements m on m.product_id = b.product_id and m.location_id = b.location_id
      group by b.product_id, b.location_id, b.qty_base having b.qty_base <> coalesce(sum(m.delta_base), 0)) x"
}

need_file() {
  [ -n "${1:-}" ] || { echo "usage: $0 $cmd FILE" >&2; exit 2; }
  case "$1" in /*) f="$1" ;; *) f="$DIR/$(basename "$1")" ;; esac
  [ -f "$f" ] || { echo "no such dump: $f" >&2; exit 2; }
}

cmd="${1:-daemon}"
case "$cmd" in
  daemon) daemon ;;
  dump) dump ;;
  list) ls -lh "$DIR"/"$DB"-*.dump 2>/dev/null || echo "no dumps in $DIR" ;;
  verify)
    need_file "${2:-}"
    scratch="${DB}_restorecheck"
    restore_into "$f" "$scratch"
    log "restored $(basename "$f") into $scratch:"
    counts "$scratch"
    psql_admin -c "DROP DATABASE \"$scratch\""
    ;;
  restore)
    need_file "${2:-}"
    [ "${3:-}" = "--yes" ] || { echo "This replaces database $DB with $(basename "$f"). Add --yes to confirm." >&2; exit 2; }
    new="${DB}_restoring"
    old="${DB}_before_$(date '+%Y%m%d_%H%M%S')"
    restore_into "$f" "$new"
    psql_admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB' AND pid <> pg_backend_pid()" >/dev/null
    psql_admin -c "ALTER DATABASE \"$DB\" RENAME TO \"$old\""
    psql_admin -c "ALTER DATABASE \"$new\" RENAME TO \"$DB\""
    log "restored $(basename "$f") into $DB; previous database kept as $old"
    counts "$DB"
    echo "When everything looks right, free the space: docker compose exec backup psql -d postgres -c 'DROP DATABASE \"$old\"'"
    ;;
  *) echo "unknown command: $cmd" >&2; exit 2 ;;
esac
