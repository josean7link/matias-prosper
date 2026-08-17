# Backlog: aislamiento de la suite de tests (trabajo pendiente)

Relevado en Fase 1 del KYB (jun 2026). **No ejecutado** — es una fase
propia, separada de las fases KYB. Contexto: no existe entorno de
test; la suite corre contra la base real `prosper_phase0` y contra el
backend vivo, en mainnet con dinero real.

## Estado actual

- Mecanismo de aislamiento existente: patrón artesanal en solo 3
  archivos (`test_deposit_engine.py`, `test_event_bus.py`,
  `test_admin_notifications_test.py`): fixture que muta
  `os.environ["DB_NAME"]` a una DB dedicada, resetea
  `db_module._client` y hace `drop_database` al final. Funciona porque
  `db()` relee `DB_NAME` en cada llamada.
- En Fase 1 se migraron a ese patrón (con drop garantizado en
  `finally`): `test_kyb_legacy_migration.py`,
  `test_kyb_apply_transition.py`, `test_storage_gridfs.py`.
- Todo lo demás escribe donde apunta la conexión: la base real.

## Parte A — Tests con escritura directa a la base real (~13 archivos)

| Archivo | Colecciones |
|---|---|
| `test_phase13_ramp_provider.py` | ⚠️ `ramp_provider_config` con `delete_many({})` sin filtro (x4) |
| `test_p0_invest_onchain.py` | `organizations`, `positions`, `ramp_accounts`, `ramp_balances`, `alerts` |
| `test_ramp_balance_sync.py` | `ramp_accounts`, `ramp_balances`, `ramp_wallets`, `ramp_provider_config` |
| `test_phase17_arsa_chain.py` | `ramp_wallets`, `ramp_balances`, `ramp_fiat_accounts`, `ramp_accounts` |
| `test_phase18_wallet_activation.py` | `ramp_webhook_events`, `ramp_wallets`, `ramp_movements` |
| `test_phase15_2_intl_offramp.py` | `ramp_movements`, `ramp_balances` |
| `test_iter26_sanctions_gate.py` | `ramp_accounts`, `organizations` (escribe `kyb_status`) |
| `test_iter27_activation_helper.py` | `ramp_accounts`, `organizations` |
| `test_phase22_admin_yield.py` | `users`, `organizations`, `investment_intents` |
| `test_phase23_hierarchy.py` | `organizations`, `users` |
| `test_andes_kyc_widget.py` | `organizations`, `users` |
| `test_sprint12_6_alfred_kyc.py` | `signed_links`, `organizations` |
| `test_email_idempotency.py` | `outbound_emails` |

**Qué haría falta:** adoptar el patrón scratch (fixture compartido en
`conftest.py`) + sembrar por archivo los datos que hoy asumen del seed
de producción (orgs, users, ramp accounts). **Esfuerzo: moderado,
~1-2 días**, archivo por archivo. **Riesgo principal:** varios de
estos tests están entre los 47 rojos del baseline; al tocarlos cambia
su comportamiento y hay que re-fijar el baseline en el mismo cambio.

## Parte B — Tests contra el backend vivo (~36 archivos)

### B.0 — HALLAZGO CRÍTICO (Fase 5a): el startup de los servers efímeros
### llama al CMS REAL (sistema de producción)

**Qué llama y cuándo** (todo en el startup/lifespan de `server:app` — es
decir en CADA arranque de un server efímero de test y del backend de
preview):

1. `prosper.factory` construye el adapter **REAL** cuando
   `PROSPER_MODE=development` (log: `Prosper adapter: REAL (development)`).
2. `RealProsperAdapter` se inicializa contra
   `https://cmsback.protocol-prosper.io` (usuario `prosperCMS@mail.com`)
   y en el arranque ejecuta:
   - `POST /api/v1/auth/login` (201 — crea una sesión real), y
   - `GET /api/v1/cms/staking`.
3. `apscheduler` registra `run_sync_once` (staking sync, intervalo 5 min)
   y lo dispara inmediatamente; mientras el server efímero viva, sigue
   pegándole al CMS real cada 5 minutos.
4. Colateral: el startup siembra demo data (300 posiciones, 395
   transacciones, 180 snapshots NAV) en la DB del proceso — arranques a
   veces >60s, causa de los timeouts intermitentes al correr varias
   suites KYB juntas.

**Implicancia**: arrancar un test toca un sistema de producción. Hoy son
login + lecturas; si el sync alguna vez escribe, cada corrida de tests
mutaría el CMS real.

**Remediación propuesta (NO ejecutada — fase propia)**: variable tipo
`PROSPER_ADAPTER=mock` / `DISABLE_EXTERNAL_SYNC=1` respetada por
`prosper.factory` y los schedulers, seteada siempre por los servers de
test; y un flag para saltear el demo-seed en arranques de test.


Golpean el backend real por HTTP (`requests`): dev-logins, decisiones
de la bandeja KYB legacy, webhooks AiPrise simulados, MFA, inversiones,
ramp. El backend escribe en la base real — **no se aíslan cambiando
`DB_NAME` en el proceso de test**, porque el proceso servidor apunta a
`prosper_phase0`.

Evidencia de contaminación ya producida: ver
`docs/kyb/test_data_contamination.md` (132 entradas `kyb.decided`
sintéticas en `audit_logs`; manipulación del MFA del usuario real
`client.admin@alemany.capital`).

**Qué haría falta:**
1. Un segundo backend de test: proceso propio (puerto dedicado,
   `DB_NAME` de test, supervisor o uvicorn efímero por sesión de
   pytest).
2. Un harness de seed: usuarios para dev-login, orgs con estados KYB /
   sanctions / travel-rule, ramp accounts y balances — hoy todo eso se
   asume del seed de producción.
3. Parametrizar la URL base (`API`) en cada archivo de test.

**Esfuerzo: alto — fase dedicada de varios días.** Interacción fuerte
con el baseline de 47 fallos: muchos rojos cambiarían de comportamiento
contra una base limpia y el baseline debe re-fijarse al final.

## Orden recomendado

1. Parte A primero (menor riesgo, valor inmediato: elimina escrituras
   sobre `organizations`/`ramp_*` reales).
2. Parte B después, como fase propia con re-fijado de baseline.
3. No mezclar ninguna de las dos con fases del módulo KYB.
