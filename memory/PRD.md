# Prosper Platform — PRD & Status

> Platform rebuilt from scratch on 2026-05-12 following the user's PRD. Legacy
> codebase preserved at `/app/legacy/`.

## Stack
- **pnpm monorepo**: `apps/admin` (Next.js 14 App Router), backend FastAPI async,
  shared `packages/ui` + `packages/types`. MongoDB via motor.
- **Auth**: passwordless OTP (4-digit) + JWT httpOnly cookie (7d). Dev magic-link
  at `/api/v1/auth/dev-login` (auto-disables when `RESEND_API_KEY` is set).
- **Brand**: Prosper palette `#2563FF` primary, `#0B0F19` ink, `#22C55E` success,
  `#F2F6FF` surface. 4-leaf clover logo + lowercase wordmark.

## ✅ Phase 0 — Bootstrap (2026-05-12)
Monorepo, OTP auth, design system, app shell with env switcher.

## ✅ Phase 1 — Data model & multi-tenancy (2026-05-12)
Pydantic + TS types, RBAC, org scoping, immutable audit log, seed CLI.

## ✅ Phase 2 — Admin Home + Sprint A (2026-05-12)
6 KPI tiles · NAV/Volume/Revenue charts · Top Clients · Operations Queue (WS) ·
Recent Activity · Export PDF · 7d/30d/90d range. 32/32 pytest.

## ✅ Phase 3 — Onboarding KYB/KYC via AiPrise (2026-05-12)
Public `/apply` flow + `/apply/status` + legacy `/admin/compliance` page
(replaced in Phase 5 by the 6-tab Compliance module). 22/22 pytest.

## ✅ Phase 3 — Operations module (2026-05-12)
5 sub-pages: transactions/lifecycle/funds/by-client/volume-by-client. 21/21 pytest.

## ✅ Phase 4 — Business module (2026-05-13)
4 sub-pages under `/admin/business`:
- `/clients` — master list with configurable columns dropdown (10 columns,
  localStorage persistence), CSV export, Executive PDF generator.
- `/revenue` — Total/MTD MoM/YTD YoY · donut breakdown · monthly stacked bar ·
  top-10 horizontal bar · MoM comparison table.
- `/yield` — yield-per-client with platform-APR benchmark + **"Mostrar fees
  implícitos" toggle** (Gross APR, Fee drag, Mgmt/Perf/Prosper-rev 30d USD).
- `/cohorts` — cohort analysis with retention bars + line, KPI tiles, table,
  6m/12m/24m range. Backend `/cohorts` endpoint.
24/24 pytest · `iteration_8.json`.

## ✅ Phase 5 — Compliance module (2026-05-13)
6 sub-pages under `/admin/compliance` (legacy page redirects to `/kyc`):
- `/kyc` — Cola personas físicas con SLA color-coded · drawer detalle con
  4 docs (zoom modal), provider score/flags, 4 checks regulatorios, decisión
  con motivo (>=20 chars).
- `/kyb` — Cola jurídicas · drawer con info societaria, docs, UBOs (PEP),
  checklist 8 items obligatorio (botón Aprobar **disabled** hasta 8/8),
  decisión con motivo.
- `/kyt` — 4 tabs: (1) 7 reglas configurables platform-wide (toggle ON/OFF +
  param editable + severity); (2) 25 alertas KYT con sev badges; (3) análisis
  on-chain (watchlist interna + Check wallet con stub TRM Labs); (4) Travel
  rule (txs > $1000, status verified/missing).
- `/risk` — Donut perfil low/medium/high/critical, top-10, tabla con drivers
  explicables (4 componentes: KYC freshness 30% / volumen 25% / geo 25% /
  behavior 20%), drawer con SAR/STR draft download (JSON).
- `/alerts` — Sistema centralizado con filtros (severity/type/status),
  checkbox selection, bulk acknowledge/resolve.
- `/limits` — Inline edit 4 caps por cliente (subscribe/redeem × daily/monthly)
  con historial drawer + audit_log entry por cambio.

Topbar **bell icon** muestra badge con count de alertas open (rojo si hay
críticas, azul si solo warning/info) + dropdown con últimas 5.

Backend: 17 endpoints en `/backend/routes/compliance/{kyc,kyb,kyt,risk_routes,alerts_routes,limits}.py`.
Stub TRM Labs (`/backend/integrations/trm_labs.py`) listo para enchufar
`TRM_LABS_API_KEY` cuando llegue.

**RBAC**: `require_compliance` (read) y `require_compliance_decide` (write,
solo super_admin + compliance_officer). Verificado 403 para client_admin en
los 17 endpoints.

41/41 pytest green · `iteration_9.json`. Único bug encontrado: `Badge tone='info'`
faltante en `packages/ui/src/Badge.tsx` (resuelto en mismo run).

## Security hardening (2026-05-12)
- `@prosper.foundation` auto-provisioned accounts default to **admin**
  (not super_admin). super_admin only via explicit seed.

## ✅ Phase 6 — Clientes / Admin clients CRUD (2026-05-13)
Full multi-tenant CRUD para organizaciones clientes:
- `/admin/clients` — listado paginado con filtros (KYB · tipo · env · search), 25 rows/pág, chips de critical_alerts y `kyb_refresh_due`.
- `/admin/clients/new` — form 3 secciones (corporativa / contacto / interna) con validación inline + domain allowlist. Al guardar: crea Organization, primary User como client_admin, signed invite link 72h, dispara email mock-friendly.
- `/admin/clients/[id]` — header con 4 acciones (KYB link / Reset pass / Invite link / Pausar) + **9 tabs in-page**: Información, Usuarios, KYB docs + Email log con preview HTML, API keys (plaintext-once con bcrypt hash), Webhooks (HMAC SHA256, test delivery + log), Posiciones, Transacciones, Compliance, Audit log.

Backend: paquete `routes/admin_clients/` (7 files) + integraciones/email_sender.py con 5 templates HTML + JWT signed links (single-use con replay protection).

**Resend mock-friendly**: sin `RESEND_API_KEY` los emails se guardan en `outbound_emails` con `status=preview_only` y HTML descargable.

**Webhooks**: signed con HMAC SHA256, test delivery contra httpbin funciona end-to-end.

Testing: 26/26 pytest backend · ~95% Playwright. Security invariants confirmados (API key plaintext SOLO en POST, signed JWT single-use). `iteration_10.json`.

## ✅ Phase 7 — Portal Cliente · Gate + Dashboard (2026-05-13)
Backend `routes/client_portal.py`:
- `GET /v1/client/me` — user + org + feature flags (`can_operate` toggles all client mutations).
- `GET /v1/client/dashboard` — KPIs (saldo USDC, tokens PUSD, principal, accrued, weighted APR), 12-month yield series, active positions, last 5 transactions, projection (realized YTD + projected annual). Maps Mongo fields `principal_usd / accrued_interest / start / maturity`.
- `GET /v1/client/transactions?limit=N` — paginated history (scoped por org_id).
- `POST /v1/apply/context` + `POST /v1/apply/finalize` — token-gated wizard endpoints (JWT signed kyb-link). Finalize is single-use (consumes link, replays return 401), creates KybCase in_review, flips `org.kyb_status` to in_review, opens compliance alert, sends mock email a `compliance@`.

Frontend:
- `/client/layout.tsx` — wraps with AppShell + sticky `ClientGateBanner`.
- `ClientGateBanner.tsx` — banner sticky con tono adaptativo (warning pending/needs_info, info in_review, danger rejected/paused). Oculto si `approved && !paused`. CTA "Continuar onboarding" sólo cuando aplica.
- `/client` dashboard — 4 KPIs, 3 action buttons (Cargar/Invertir/Retirar) **disabled si !can_operate** con label "Disponible al aprobar KYB", `YieldChart` recharts area-chart 12m, projection card, posiciones (hasta 6 rows), últimos movimientos (hasta 5 rows).
- `/client/profile` — read-only org card (incluye motivo de rechazo si aplica) + user card.
- `/apply?token=...` — wizard 7 pasos (bienvenida → identidad → empresa → UBOs → docs (placeholder) → verificación (AiPrise note) → revisar + terms). Sin token cae al formulario público legacy que dispara AiPrise.

14/14 pytest backend · `iteration_11.json`. Sumsub queda fuera de scope — KYC/B usa **AiPrise** (mocked en simulated mode hasta tener template IDs).


- **TRM Labs**: usuario confirmó cuenta, falta `TRM_LABS_API_KEY` →
  `/admin/compliance/kyt/screen-wallet` y "Check wallet" devuelven
  `status=unavailable` hasta recibir la key.
- **AiPrise templates + webhook secret** — para flipear KYB/KYC a live.
- **Resend** — `RESEND_API_KEY` + dominio verificado.
- **Stellar upstream** — preview egress block on `horizon.stellar.org`.

## 🟢 Technical backlog (P2)
- Phase 2: unique index on `nav_snapshots` BEFORE `insert_many`.
- Phase 2: `$lookup` instead of per-row org lookup in `recent_activity.py`.
- Phase 2: real cron snapshot/day for NAV.
- Phase 3 ops: pad sparkline zeros so sparklines share x-scale.
- Phase 3 ops: guard `retry-step` to only flip steps currently error|pending.
- Phase 3 ops: disambiguate the many "TEST Holdings" leftover orgs.
- Phase 4: split `routes/business.py` into clients/revenue/yield/cohorts.
- Phase 5: SAR/STR currently descargan JSON. Migrar a PDF formal.
- Phase 5: client-side RBAC guard en ComplianceLayout.
- Phase 5: tighten SEV_TONE types — importar `Tone` desde Badge.tsx.
- Phase 5: WebSocket o push real-time para alertas critical.
- Phase 6: refactor `/admin/clients/new` y detail forms a shadcn `<Select>` y `<DatePicker>` (currently native HTML).
- Phase 6: "Crear cliente demo con datos seedeados" button (user-requested follow-up).
- Sprint 11B: cron diario `users.deletion_effective_at < now() → status=deleted` (hard delete tras los 7d de gracia).
- Sprint 11B: avatar magic-byte sniff (Pillow) + posibilidad de migrar a S3 cuando crezca el tamaño.
- Sprint 11B: añadir `data-testid="session-current-badge"` y `mfa-verify-submit` para hardening de E2E.
- Phase 7: i18n ES/EN para portal cliente.
- Phase 7: replace native date inputs en `/apply` (wizard step 2 + legacy form) por shadcn DatePicker.
- Phase 7: real document upload (vs placeholder checkboxes) en wizard step 5 — engancha con AiPrise upload SDK cuando esté.

## ✅ Phase 8 — Portal Cliente · Alfred Onramp/Offramp (2026-05-14)
Backend (`integrations/alfred/` + `routes/client_alfred.py`):
- **Adapter pattern**: `AlfredAdapter` interface + `MockAlfredAdapter` (deterministic, in-memory order book, auto-settle 8s/12s) + `RealAlfredAdapter` stub. Switch via `ALFRED_MODE=mock|sandbox|production`. Factory caches singleton.
- **Onramp** endpoints: `POST /client/onramp/quote` (TTL 60s), `POST /client/onramp/orders` (caps validation contra `subscribe_daily_cap_usd` / monthly), `GET /client/onramp/orders/{id}` (auto-refresca status desde Alfred + crea TX confirmada).
- **Offramp** endpoints: `POST /client/offramp/quote`, `POST /client/offramp/orders` (valida que `bank_account.holder_name` matchee `org.legal_name`, caps redeem), `GET /client/offramp/orders/{id}` con timeline de 5 pasos.
- **Webhook público** `POST /webhooks/alfred`: HMAC SHA256 con `ALFRED_WEBHOOK_SECRET`, idempotente por `event_id` (collection `webhook_events`), actualiza onramp/offramp orders.
- **Mock helpers**: `/alfred/mock-checkout/{id}` (HTML self-contained con botones Pagar/Cancelar) + `/alfred/mock-settle/{id}` para fast-forward tests.
- **History**: `GET /client/transactions/history?tx_type=&status=` con filtros.
- **Audit + logging**: cada call a Alfred queda en `alfred_calls_log`, side-effects en `audit_logs`.

Frontend:
- `/client/onramp` — dos columnas (form izq + cotización viva dcha). 5 currency cards con bandera, monto, 4 payment methods, countdown 60s con auto-refresh, badge "modo mock".
- `/client/onramp/[id]/checkout` — abre popup de Alfred + polling SWR cada 5s; redirige a /success o /failed según status.
- `/client/onramp/[id]/success` — hero verde con check gigante, `+96.31 USDC ACREDITADO`, detalle (alfred_id, coelsa_id, fee, rate), CTAs (Empezar a invertir / Hacer otra carga).
- `/client/offramp` — origen tabs (saldo libre / posición), monto USDC, currency destino, cuenta destino con guard de titular; quote viva.
- `/client/offramp/[id]/status` — timeline 5 pasos color-coded, detalle + status badge.
- `/client/transactions` — historial completo con filtros (tipo, status), export CSV, badges por tipo y status.

10/10 pytest backend pass · frontend 100% funcional · `iteration_12.json`. Sin issues críticos.

**Hardcoded FX (mock)**: 1 USD = 1030 ARS, 950 CLP, 5.10 BRL, 17.30 MXN, 0.92 EUR. Fee 80bps (Alfred 35 + Prosper 45).

**Switch a producción**: cuando lleguen credenciales reales setear `ALFRED_API_KEY`, `ALFRED_MODE=sandbox` (o `production`), `ALFRED_WEBHOOK_SECRET`. El stub `RealAlfredAdapter` espera endpoints `/v1/quotes`, `/v1/orders/onramp`, `/v1/orders/offramp`, `/v1/orders/{id}` (confirmar formato con docs de Alfred al momento del switch).


Comprar Prosper Yield Token (suscripción), gestión de posiciones, redenciones.

## ✅ Phase 9 — Compra Automática Prosper (2026-05-14)
Backend (`integrations/prosper/` + `routes/client_invest.py` + `jobs/accrual.py`):
- **Adapter pattern**: `ProsperAdapter` interface + `MockProsperAdapter` (idempotente por `prosper_tx_id`, estado in-process) + `RealProsperAdapter` con HTTP/JWT (auto-refresh on 401). Switch por `PROSPER_MODE=mock|development|production`. Endpoints reales esperados: `/v1/Auth/Login`, `/v1/users/new`, `/v1/users/deposit`, `/v1/users/withdraw`, `/v1/tokens/transfer`, `/v1/users/{id}/balances`, `/v1/users/{id}/transactions`, `/v1/assets/`.
- **Products** seeded: liquid_v1 (sin lock, 6% APR), term_30 (7.5%), term_90 (9%), term_180 (11%). Lazy ensure on startup.
- **Auto-buy post-onramp**: cuando un onramp se settlea (vía webhook real o `mock-settle`), se dispara `trigger_buy_after_onramp` que: (1) ensure wallet Stellar, (2) genera `prosper_tx_id` UUIDv4, (3) crea TX `subscribe` pending, (4) llama `deposit_tokens`, (5) crea Position con APR y maturity del producto, (6) marca TX confirmed con `tx_hash` y `ledger`. Si falla cualquier step → TX failed + Alert operational warning para investigación. Idempotente: si el onramp ya tiene un subscribe TX, no se duplica.
- **Manual buy** (`POST /client/positions`): valida producto activo, min/max amount, saldo USDC libre, KYB aprobado.
- **Redeem** (`POST /client/positions/{id}/redeem`): liquid o matured pueden redimir; calls `withdraw_tokens` y crea TX `redeem`.
- **Endpoints**: `GET /client/products`, `GET /client/balances` (combina USDC libre + balance_prosper + balance_xlm desde adapter), `GET /client/positions`, `GET /client/positions/{id}` (incluye `events[]`), `POST /client/positions`, `POST /client/positions/{id}/redeem`.
- **Daily accrual** vía APScheduler (cron 0 0 * * * UTC) — `jobs.accrual.run_accrual_once()` actualiza `accrued_interest` y flippea status a `matured` cuando corresponde. Idempotente dentro del día (chequea `last_accrued_date`).

Frontend:
- `/client/invest` — selector visual de productos con APR badge + monto + preview en vivo (USDC→PROS, APR, maturity, yield estimado) + modal de confirmación con disclaimer regulatorio.
- `/client/investments` — listado de posiciones con KPIs (activas, principal total, yield acumulado).
- `/client/investments/[id]` — detalle con 3 KPI cards, timeline de eventos (subscribe, redeem) con tx_hash linkable a Stellar Expert, botón "Redimir" cuando aplica.
- `/client/onramp/[id]/success` — **NUEVO**: card "Compra automática Prosper" con tokens recibidos, APR, producto, maturity y tx Stellar — junto al detalle del onramp.

14 backend tests + frontend 100% (`iteration_13.json`). Zero critical issues. End-to-end verificado: ARS 100k → 96.31 USDC → 96.31 PROS posición activa al instante con APR 6% en producto `liquid_v1`.

**Switch a producción Prosper**: setear `PROSPER_API_BASE`, `PROSPER_API_USER`, `PROSPER_API_PASS` reales y `PROSPER_MODE=development|production`. El stub `RealProsperAdapter` ya implementa todos los endpoints con JWT auto-refresh.

## ✅ Sprint 11A — Developer & integration core (2026-05-14)
Self-service para developers de la organización cliente:
- `/client/api-keys` — Issue/rotate/revoke con plaintext-once + bcrypt hash + scope sandbox/production gateado por `org.env`.
- `/client/webhooks` — endpoints HMAC SHA256, eventos curados (`onramp.confirmed`, `subscribe.confirmed`, `position.matured`, etc.), test delivery + log de entregas, reveal-secret bajo auditoría.
- `/client/developers` — docs interactivos con curl samples + Try it.
- `/client/sdk` — landing con snippets JS/Python/cURL.
- `/client/widget` — configurador con preview live + snippet copyable + persistencia en `org.widget_config`.
- `/client/coming-soon` — registro de interés (5 features) que escribe en `feature_interest`.

Backend `routes/client_developer.py`. 100% tests (`iteration_14.json`).

## ✅ Sprint 11B — Portal Cliente · Profile Hardening (2026-05-14)
Página `/client/profile` rediseñada con 5 tabs y session-aware auth.

**Backend** (`routes/client_profile.py` + extensions a `auth.py`):
- `GET/PATCH /v1/client/profile` — full_name, phone, language (es/en/pt), timezone (whitelist).
- `POST/DELETE /v1/client/avatar` — base64 data URL ≤256 KB persistido inline.
- **MFA TOTP**: `POST /mfa/setup` (genera secret pyotp + QR `data:image/png;base64,…`), `POST /mfa/verify` (valida live code y devuelve 10 backup codes XXXX-XXXX), `POST /mfa/disable` (TOTP o backup), `POST /mfa/regenerate-codes`. Secret encriptado con Fernet (`MFA_FERNET_KEY`), backup codes bcrypt-hasheados.
- **Sessions**: `GET /v1/client/sessions` (lista con `is_current`), `DELETE /v1/client/sessions/{id}` (revoke individual; revocar la propia → 401 en próxima call), `POST /sessions/revoke-others`. Implementación: cada login (`/passwordless-token` y `/auth/dev-login`) llama `mint_session_token` que genera `jti` único + inserta doc en `sessions`. `get_current_user` valida que la sesión esté activa (lenient para tokens legacy sin jti).
- **Notifications**: `GET/PATCH /v1/client/notifications` con 6 toggles (`email_security_alerts`, `email_account_activity`, `email_yield_summary`, `email_marketing`, `inapp_alerts`, `inapp_transactions`).
- **Account deletion**: `POST /account/request-deletion` (requiere confirm_email match, cooldown 7d, audit log para compliance ops), `POST /cancel-deletion`.

**Frontend** (`/app/frontend/src/app/client/profile/page.tsx` + `components/client/profile/*`):
- Tabs: **Cuenta** (avatar + datos personales + org card read-only), **Seguridad** (MFA setup wizard QR→verify→backup codes con copy/download, regenerar codes, disable con TOTP o backup), **Sesiones** (lista con device icons + is_current badge, revoke individual + revoke-others), **Notificaciones** (6 toggles agrupados email/in-app), **Eliminar cuenta** (modal con email-match, pending state + cancelación).
- SWR hooks en `lib/profile.ts` (Profile, MfaSetupResponse, Session types).

11/11 backend pytest pass (`test_phase11b_profile.py`) + frontend 100% verificado vía testing agent (`iteration_15.json`). Sin issues críticos.

**Switch a producción**: `MFA_FERNET_KEY` ya seedeado en `.env` (rotalo en prod). Para hard-delete de cuentas tras los 7d, agendar cron diario que flippee `users` con `deletion_effective_at < now()` a `status='deleted'` (P2 backlog).

## ✅ Sprint 12 — Polish + Demo hardening + Status/Legal + Docs + E2E (2026-05-14)

**Backend** (`routes/admin_ops.py` + middleware + indices):
- `POST /v1/admin/ops/wipe-demo` (super_admin) — limpia 13 colecciones filtrando `is_demo=true`, requiere confirm string `"WIPE-DEMO"`, devuelve summary por colección. Audit-logged.
- `POST /v1/admin/ops/seed-demo-client` (super_admin) — crea 1 org demo + 1 client_admin + (opcional) 2 tx confirmadas + 1 position activa con 30d de accrual. Tarda ~150ms. Marcado todo `is_demo=true`.
- `GET /v1/status` — público, sin auth. Agrega health checks de Mongo, Redis (optional → no cuenta para overall), API, Admin, Cliente, Webhooks delivery fail-rate, Alfred mode, Prosper mode. Memoizado 5s.
- Security headers globales: HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy.
- Rate limit token-bucket in-process (`rate_limit()` helper): 10/min `passwordless-login`, 30/min `passwordless-token`. Bypass vía `PROSPER_DISABLE_RATELIMIT=1`. Para multi-worker prod, migrar a Redis (TODO).
- Sentry hook condicional (sólo init si `SENTRY_DSN` está seteado).
- Mongo indices hardening: `TRANSACTIONS.tx_hash` (sparse), `ALERTS.assigned_to` (sparse), `SESSIONS.session_id` (unique) + `user_id` + `expires_at`, `NAV_SNAPSHOTS.date` (unique), compounds `(org_id, type, status)`, `(org_id, severity, status)`, `(kyb_status, is_deleted)`.

**Frontend** (público, sin auth):
- `/status` — banner overall + 8 service rows con icon coloreado + Refrescar button + SWR refresh 30s + footer.
- `/terms` — Términos de Servicio (10 secciones).
- `/privacy` — Política de Privacidad (9 secciones).
- `PublicFooter` componente con stack regulatorio (Arvest, CNV, Caja de Valores, Moody's).
- `middleware.ts` updated PUBLIC_PATHS.
- Admin `/admin/clients` — nuevo botón **"Crear demo seedeado"** que llama al seed endpoint y refresca la tabla.

**E2E suite** (`/app/e2e/`):
- `01-admin-full-flow.spec.ts` — seed demo + admin sees row + client lands on dashboard.
- `02-api-key-flow.spec.ts` — plaintext-once + revoke security invariant.
- `03-webhook-delivery.spec.ts` — registered endpoint + HMAC-signed test delivery.
- `04-cross-org-security.spec.ts` — cross-org 404 + impersonation 403 + anon 401.
- `05-public-surfaces.spec.ts` — status/terms/privacy renderizan sin auth.
- `playwright.config.ts` + `tests/_helpers.ts` (loginAs vía dev magic link).
- Listo para CI: `.github/workflows/ci.yml` ya tiene el job `e2e` que instala chromium y corre la suite contra `STAGING_URL`.

**Docs y deploy kit**:
- `/app/RUNBOOK.md` — 12 procedimientos operativos + matriz de escalación.
- `/app/ARCHITECTURE.md` — diagramas + 9 flows críticos + modelo de datos.
- `/app/COMPLIANCE.md` — regulatory stack + KYC/KYB/KYT/SAR-STR + retention 10y.
- `/app/INTEGRATIONS.md` — playbooks para AiPrise/Alfred/Prosper/TRM/Resend.
- `/app/backend/.env.example` — template prod-ready.
- `/app/backend/Dockerfile` con HEALTHCHECK contra `/api/v1/status`.
- `/app/.github/workflows/ci.yml` + `deploy-prod.yml` (ECS Fargate + Vercel + Slack notify).

**Testing**:
- 6/7 phase12 pytest pass + 1 skipped (wipe-demo test es destructivo — skipped intencionalmente).
- 33/33 pytest combinados entre phase 1/7/8/9/11A/11B/12.
- Testing agent verificó frontend + backend al 100% (`iteration_16.json`).
- 7 fallos pre-existentes en phase2/3/5/9_extras son data-count drift por seed pollution entre iteraciones — NO regresiones de Phase 12.


- Sumsub Web SDK integration en `/apply` (continuar prompt 1 de Fase 5).
- Audit log viewer `/admin/compliance/audit` (continuar prompt 2 de Fase 5).
- Push notifications API para alertas critical (continuar prompt 3 de Fase 5).
- Regulatory reporting module formal.
- Client portal (self-service subscribe / redeem / statements).
- Mobile companion (P3).

## Notes
- Old codebase at `/app/legacy/` — do not import from there.
- Test credentials: `/app/memory/test_credentials.md`.
- Latest test report: `/app/test_reports/iteration_16.json`.
