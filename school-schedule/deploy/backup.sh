#!/bin/sh
# Резервная копия базы. Хранит копии за последние 30 дней.
# Запуск по расписанию: sudo crontab -e  →  15 3 * * * /opt/school-schedule/deploy/backup.sh
set -eu
DB=/opt/school-schedule/data/schedule.db
DIR=/var/backups/school-schedule
mkdir -p "$DIR"
sqlite3 "$DB" ".backup '$DIR/schedule-$(date +%F).db'"
find "$DIR" -name 'schedule-*.db' -mtime +30 -delete
