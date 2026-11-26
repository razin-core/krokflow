#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${KROK_DB_PATH:-${ROOT_DIR}/data/krok.db}"
BACKUP_DIR="${KROK_BACKUP_DIR:-${ROOT_DIR}/data/backups}"
KEEP="${KROK_BACKUP_KEEP:-7}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "Database not found: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
OUT="${BACKUP_DIR}/krok-$(date +%Y%m%d-%H%M%S).db"

sqlite3 "$DB_PATH" ".timeout 5000" ".backup '${OUT}'"
sqlite3 "file:${OUT}?immutable=1" "PRAGMA quick_check;" | grep -qx "ok"

ls -1t "${BACKUP_DIR}"/krok-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f || true
ls -lh "$OUT"
