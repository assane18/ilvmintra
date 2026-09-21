#!/bin/bash
# Sauvegarde quotidienne de l'intranet ILVM : base PostgreSQL + fichiers uploadés.
#
# Destination : copie locale (backups/) + copie sur le partage réseau
# ilvmfap1_info (serveur physique séparé de cette VM), avec rotation 30 jours
# des deux côtés.
#
# Restauration :
#   Base   : gunzip -c intranet_db_AAAA-MM-JJ.sql.gz | psql "$DATABASE_URL"
#   Uploads: tar xzf uploads_AAAA-MM-JJ.tar.gz -C app/static/
#
# Usage : lancé quotidiennement par cron (voir crontab -l), ou manuellement :
#   /var/www/intranet/scripts/backup.sh

set -euo pipefail

PROJECT_DIR="/var/www/intranet"
LOCAL_BACKUP_DIR="$PROJECT_DIR/backups"
REMOTE_BACKUP_DIR="/mnt/ilvmfap1_info/Backups_Intranet"
RETENTION_DAYS=30
DATE="$(date +%F)"

mkdir -p "$LOCAL_BACKUP_DIR"

# Charge DATABASE_URL (et le reste de .env) sans les afficher.
set -a
source "$PROJECT_DIR/.env"
set +a

DB_DUMP="$LOCAL_BACKUP_DIR/intranet_db_${DATE}.sql.gz"
UPLOADS_DUMP="$LOCAL_BACKUP_DIR/uploads_${DATE}.tar.gz"

echo "[$(date '+%F %T')] Démarrage sauvegarde."

pg_dump "$DATABASE_URL" | gzip > "$DB_DUMP"
echo "[$(date '+%F %T')] Base sauvegardée : $DB_DUMP ($(du -h "$DB_DUMP" | cut -f1))"

tar czf "$UPLOADS_DUMP" -C "$PROJECT_DIR/app/static" uploads
echo "[$(date '+%F %T')] Uploads sauvegardés : $UPLOADS_DUMP ($(du -h "$UPLOADS_DUMP" | cut -f1))"

# Copie hors de la VM (partage réseau ilvmfap1_info) — le point qui compte :
# un incident sur le disque de cette VM ne doit pas emporter aussi la sauvegarde.
if mountpoint -q /mnt/ilvmfap1_info; then
    mkdir -p "$REMOTE_BACKUP_DIR"
    cp "$DB_DUMP" "$REMOTE_BACKUP_DIR/"
    cp "$UPLOADS_DUMP" "$REMOTE_BACKUP_DIR/"
    echo "[$(date '+%F %T')] Copié vers $REMOTE_BACKUP_DIR"
else
    echo "[$(date '+%F %T')] ATTENTION : /mnt/ilvmfap1_info non monté, copie distante ignorée." >&2
fi

# Rotation (30 jours), locale et distante.
find "$LOCAL_BACKUP_DIR" -name 'intranet_db_*.sql.gz' -mtime +$RETENTION_DAYS -delete
find "$LOCAL_BACKUP_DIR" -name 'uploads_*.tar.gz' -mtime +$RETENTION_DAYS -delete
if mountpoint -q /mnt/ilvmfap1_info; then
    find "$REMOTE_BACKUP_DIR" -name 'intranet_db_*.sql.gz' -mtime +$RETENTION_DAYS -delete
    find "$REMOTE_BACKUP_DIR" -name 'uploads_*.tar.gz' -mtime +$RETENTION_DAYS -delete
fi

echo "[$(date '+%F %T')] Sauvegarde terminée."
