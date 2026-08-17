#!/bin/sh
# Prosper — precheck de disco para el operador ANTES de correr `pytest -m kyb_gate`.
#
# Uso:
#   sh /app/scripts/ops/disk_precheck.sh
#
# Devuelve:
#   exit 0  → verde, listo para correr el gate
#   exit 1  → amarillo, correr pero monitorear
#   exit 2  → rojo, NO correr — falta espacio; ejecutar log_janitor y reevaluar.
#
# Lee /var/log/prosper-disk-alert.log para mostrar las últimas alertas del cron.

set -eu

MIN_FREE_MB_GREEN=800    # verde ≥ 800 MB
MIN_FREE_MB_YELLOW=300   # amarillo entre 300 y 800

AVAIL_KB=$(df -P /data/db 2>/dev/null | awk 'NR==2 {print $4}')
AVAIL_MB=$((AVAIL_KB / 1024))
USE_PCT=$(df -P /data/db 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}')

MONGO_UP=$(supervisorctl status mongodb 2>/dev/null | awk '{print $2}')
[ -z "$MONGO_UP" ] && MONGO_UP=UNKNOWN

printf '== Prosper disk precheck (mount /data/db) ==\n'
printf '  free       = %s MB\n' "$AVAIL_MB"
printf '  used       = %s%%\n' "$USE_PCT"
printf '  mongodb    = %s\n' "$MONGO_UP"
printf '  timestamp  = %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Últimas 3 alertas del cron janitor
if [ -f /var/log/prosper-disk-alert.log ]; then
	printf '\n  Últimas alertas del cron janitor:\n'
	tail -3 /var/log/prosper-disk-alert.log | sed 's/^/    /'
fi

printf '\n'

if [ "$MONGO_UP" != "RUNNING" ]; then
	printf 'ROJO: MongoDB no está RUNNING. Estado: %s\n' "$MONGO_UP" >&2
	exit 2
fi

if [ "$AVAIL_MB" -lt "$MIN_FREE_MB_YELLOW" ]; then
	printf 'ROJO: %s MB libres < umbral %s MB. NO correr el gate.\n' \
		"$AVAIL_MB" "$MIN_FREE_MB_YELLOW" >&2
	printf 'Acción: ejecutar `/app/scripts/ops/prosper_log_janitor.sh` y reevaluar.\n' >&2
	exit 2
fi

if [ "$AVAIL_MB" -lt "$MIN_FREE_MB_GREEN" ]; then
	printf 'AMARILLO: %s MB libres < umbral verde %s MB. Correr con monitoreo.\n' \
		"$AVAIL_MB" "$MIN_FREE_MB_GREEN"
	exit 1
fi

printf 'VERDE: %s MB libres. Ok para correr el gate.\n' "$AVAIL_MB"
exit 0
