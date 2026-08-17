#!/bin/sh
# Prosper — janitor de logs rotados de MongoDB y alerta de disco.
#
# Motivación: supervisord rota /var/log/mongodb.out.log en hasta 10 backups
# de 50 MB por defecto (500 MB techo). El mount /dev/nvme0n7 tiene solo 9.8 GB
# compartidos con /data/db y /app, así que 500 MB de logs es un techo
# demasiado alto — puede empujar a MongoDB a shutdown sucio.
#
# Este janitor:
#   1. Deja SOLO los 2 backups más recientes (mongodb.out.log.1 y .log.2).
#      Cualquier otro archivo /var/log/mongodb.out.log.N con N >= 3 se borra.
#      Techo efectivo: ~150 MB (activo 50 + .1 50 + .2 50).
#   2. Alerta a /var/log/prosper-disk-alert.log si el mount de /data/db supera
#      el 85% de uso. Formato JSONL para ser grep-able desde el operador.
#   3. Idempotente y silencioso: si no hay nada que hacer, no imprime.
#
# Instalado como /etc/cron.d/prosper-log-janitor (cada 10 minutos).
# NO edita ni el logfile activo ni ningún directorio de /data/db.

set -eu

LOG_DIR=/var/log
KEEP_BACKUPS=2
ALERT_THRESHOLD_PCT=85
ALERT_LOG=/var/log/prosper-disk-alert.log

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# --- 1) Janitor de logs rotados de mongodb.out.log -------------------------
# Solo tocamos backups (nombre termina en .NN). El activo (sin sufijo) queda.
REMOVED_COUNT=0
FREED_BYTES=0
for f in "$LOG_DIR"/mongodb.out.log.[0-9]* "$LOG_DIR"/mongodb.err.log.[0-9]*; do
	[ -f "$f" ] || continue
	# Extraer el número final del archivo (después del último punto).
	suffix="${f##*.}"
	# Validar que es entero (defensa contra nombres inesperados).
	case "$suffix" in
		''|*[!0-9]*) continue ;;
	esac
	if [ "$suffix" -gt "$KEEP_BACKUPS" ]; then
		size=$(stat -c%s "$f" 2>/dev/null || echo 0)
		if rm -f "$f" 2>/dev/null; then
			REMOVED_COUNT=$((REMOVED_COUNT + 1))
			FREED_BYTES=$((FREED_BYTES + size))
		fi
	fi
done

# --- 2) Alerta de espacio en disco -----------------------------------------
# `df -P` da output tabular estable. Extraer % de uso de /data/db.
USE_PCT=$(df -P /data/db 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}')
AVAIL_KB=$(df -P /data/db 2>/dev/null | awk 'NR==2 {print $4}')

# Emitir línea JSONL SIEMPRE si limpiamos algo o si estamos en alerta;
# si todo bien y no limpiamos, no ensuciamos el log.
if [ "$REMOVED_COUNT" -gt 0 ] || [ "${USE_PCT:-0}" -ge "$ALERT_THRESHOLD_PCT" ]; then
	# Detectar nivel de alerta
	if [ "${USE_PCT:-0}" -ge 95 ]; then
		level="critical"
	elif [ "${USE_PCT:-0}" -ge "$ALERT_THRESHOLD_PCT" ]; then
		level="warn"
	else
		level="info"
	fi
	printf '{"ts":"%s","level":"%s","use_pct":%s,"avail_kb":%s,"removed":%d,"freed_bytes":%d,"mount":"/data/db"}\n' \
		"$TIMESTAMP" "$level" "${USE_PCT:-null}" "${AVAIL_KB:-null}" \
		"$REMOVED_COUNT" "$FREED_BYTES" >> "$ALERT_LOG"
fi

exit 0
