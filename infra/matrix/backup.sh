#!/usr/bin/env bash
# Ежедневный бэкап: дампы Postgres (synapse, lifeos) + ключи/медиа Synapse + ntfy + бот + .env
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
DEST="${BACKUP_DIR:?}"; KEEP="${KEEP_DAYS:-14}"; ts=$(date +%F_%H%M)
mountpoint -q "$(echo "$DEST" | cut -d/ -f1-3)" || { echo "диск для бэкапов не смонтирован: $DEST" >&2; exit 1; }
mkdir -p "$DEST"
docker compose exec -T postgres pg_dump -U synapse -Fc synapse > "$DEST/synapse-db_$ts.dump"
if docker compose exec -T postgres psql -U synapse -d postgres -tAc "select 1 from pg_database where datname='lifeos'" | grep -q 1; then
  docker compose exec -T postgres pg_dump -U synapse -Fc lifeos > "$DEST/lifeos-db_$ts.dump"
fi
tar -czf "$DEST/synapse-files_$ts.tar.gz" .env data/synapse data/ntfy/lib $(ls -d data/bot ../../bot/local 2>/dev/null)
find "$DEST" -type f -mtime +"$KEEP" -delete
echo "backup ok: $DEST ($ts)"
