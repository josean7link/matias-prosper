# Nota de auditoría — 2026-06-19

Auditoría forense read-only ejecutada (ver chat). Hallazgos clave registrados:
- Disco /app estaba 100% lleno → mongo FATAL + frontend ENOSPC. Limpiados tmp_pack/tmp_obj de .git (1.1GB). Quedan 1.1GB libres; .git pesa 6.4GB por frontend/.next trackeado (154 archivos).
- Secretos: memory/PROD_DEPLOY.md (con ANDES_API_KEY prod plaintext) está commiteado en HEAD (a1902d7). backend/.env + frontend/.env están staged y entrarán al próximo commit. Rotación de ANDES_API_KEY pendiente.
- deposit_watcher.start_scheduler() NO está cableado en server.py startup (solo tick manual admin).
- Redis no instalado en el pod → cache 12s snapshot inactivo (fallback sin cache).
- Suite completa vs preview: 429 passed / 47 failed / 69 skipped. Fails = drift de datos del DB vivo + CMS 503 externo + fixture CUIT sin .zfill(8) (test_iter27:48, sigue abierto).
- Suites de features nuevas (deposit engine + event bus + notifications + snapshot + kyc widget): 82/82 PASSED.
- Withdraw USDC: no implementado (solo rail-usdc-soon placeholder). ARSa safety poller: no existe (env var huérfana ARSA_BACKUP_POLLER_INTERVAL_SECONDS). Fix estructural CVU auto-sync: no implementado (solo webhook handler + manual get_funding_instructions).
