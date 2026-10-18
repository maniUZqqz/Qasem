#!/bin/sh
# Nightly database dump.
#
# Deliberately boring: pg_dump to a gzipped file on a host-mounted path, with
# old files pruned. Nothing here needs the application, a cloud account or a
# tool that might not be installed the night something breaks.
#
# Restore:
#   gunzip -c backups/upmarket-YYYY-MM-DD.sql.gz | \
#     docker compose exec -T db psql -U upmarket -d upmarket

set -eu

DB_HOST="${DB_HOST:-db}"
DB_USER="${POSTGRES_USER:-upmarket}"
DB_NAME="${POSTGRES_DB:-upmarket}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
OUT_DIR=/backups

run_backup() {
    stamp=$(date +%Y-%m-%d_%H%M)
    file="$OUT_DIR/upmarket-$stamp.sql.gz"
    echo "[backup] $(date -Is) starting -> $file"

    if pg_dump -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" | gzip > "$file.partial"; then
        # Only rename once the dump finished. A half-written file with the real
        # name is worse than no file: it looks like a backup.
        mv "$file.partial" "$file"
        echo "[backup] $(date -Is) ok — $(du -h "$file" | cut -f1)"
    else
        rm -f "$file.partial"
        echo "[backup] $(date -Is) FAILED" >&2
        return 1
    fi

    find "$OUT_DIR" -name 'upmarket-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
}

# One immediately, so a broken configuration is discovered now rather than at
# 3am when the first scheduled run silently fails.
run_backup || echo "[backup] first run failed — check credentials" >&2

while true; do
    sleep 86400
    run_backup || true
done
