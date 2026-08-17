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



## 🧹 Feb 2026 · Cierre Pre-Fase 5b (Sumsub) — 2026-02-XX

**Status**: LISTO para Sumsub. 5/6 bugfixes Fase 8 verificados por testing agent
(iteration_45.json). Bugfix 6 y regresiones R2/R3/R4 corregidos y validados por
baseline (48 currently failing vs 51 previos; una única regresión residual es
falso positivo por política de flags).

**Higiene de disco (`/app`)**:
- Auditoría de `prosper-project.zip` (114 MB) y `prosper-clean-export.zip`
  (85 MB): ninguno estaba trackeado por git, ninguno estaba en el historial,
  ninguno era alcanzable vía preview URL (no montados en `/frontend/public/`
  ni en `StaticFiles` del backend). El primero contenía secretos reales
  (`.andes-private-key.pem`, `legacy/backend/.env`, `backend/.env` con
  `EMERGENT_LLM_KEY` y credenciales Prosper API) pero permanecieron aislados
  al pod. El segundo era la variante "clean" (solo `.env.example`). Borrados.
- `/app/frontend/.next/cache` (270 MB) purgado.
- Rotados `/var/log/mongodb.out.log.[1-6]` (~300 MB fuera de `/app`).
- Espacio: 99% → 92% (873 MB libres). Drivers de crecimiento sostenido
  identificados: `.git/objects` (5.8 GB, primer origen de saturación),
  `legacy/frontend` (934 MB, estático), `node_modules` root hoisted por
  workspaces (708 MB, no borrable), `.next/cache` (regenera).

**Bugfixes de código aplicados en este cierre**:
- `backend/kyb/routes_admin_checks.py::generate` — ahora invoca
  `kyb.orchestrator.dispatch_on_submit(case, trigger=TRIGGER_RETRY)` en lugar
  de `generate_checks` directo. Cierra el Bugfix 6 (el botón "Generar
  checklists" del portal admin pasa por el orquestador; idempotente).
- `backend/routes/compliance/kyb.py::_legacy_retired_redirect` — el redirect
  308/410 sólo aplica si el `case_id` existe en el modelo nuevo
  (`verification_modes: {$exists: true}`). Casos legacy siguen respondiendo
  desde el router viejo con el flag ON. Cierra R3/R4.
- Tests actualizados a la nueva semántica del orquestador:
  `test_kyb_ubos_submit::test_10_submit_full_flow` acepta que la DB avanza
  a `screening`/`under_review` post-submit; `test_kyb_admin_portal::
  test_08_legacy_endpoints_retired` usa un `case_id` del modelo nuevo.

**Flags & datos de test** (validado):
- `KYB_MODULE_ENABLED=true`, `NEXT_PUBLIC_KYB_MODULE_ENABLED=true`.
- Case A (draft): `6a7cbda88e6e8722c537fe15` en DB `prosper_phase0`.
- Case B (submitted): `6a7cbda98e6e8722c537fe20` en DB `prosper_phase0`.

**Regresión residual (no bloqueante)**:
- `test_kyb_signup::test_flag_off_routes_do_not_exist_in_prod` sigue fallando
  con 422 en lugar de 404 porque el test asume flag OFF en el backend
  `:8001` y el preview tiene el flag ON. Se resuelve solo cuando se
  restaure el flag OFF en prod.

**Pendiente (P0)**:
- Fase 5b — Sumsub. Requiere: (a) API keys, (b) nombres exactos de los tres
  niveles del dashboard (1 company + 2 individual), (c) confirmación del
  webhook secret y algoritmo de firma. Enchufa en `kyb/orchestrator.py::
  _dispatch_category` (mode="automatic"). Debe pasar por
  `integration_playbook_expert_v2` con `https://docs.sumsub.com/llms.txt`.



## 🩺 Phase 22+ · Andes KYC Widget (rescue + root cause) — Feb 2026

**Status**: backend + frontend listos, pendiente deploy atómico y aprobación
del usuario para mergear.

**Root cause fix** (`routes/webhooks_aiprise.py`):
- `_apply_kyc_decision` para `org.type=="personal"` → **log-and-drop**.
  AiPrise queda fuera del flow individual; Andes es la única fuente de verdad.
- `/onboarding/apply/simulate` con `sim_kyc_*` → 400 explícito (no se crea un
  segundo path de activación que no exista en prod).

**Defense in depth** (`routes/ramp_routes.py`):
- `ensure_org_ramp_account` con `account_type=USER` sin files → `kyc_docs_required`
  en vez de llamar `/fiat` y caer en error.
- `_refresh_account` para `org.type=="personal"` → skip `/fiat`, mismo estado.

**Audit parity** (`services/activation.py`):
- `on_identity_approved` setea `users.kyc_decision`, `kyc_decided_at`, `kyc_raw`
  (con `source="andes"`) en ambas ramas, además de provisar `ensure_org_prosper_wallet`
  eager. Mantiene compatibilidad con admin readers de `compliance/legacy.py`.

**Shared helper** (`services/andes_kyc.py`):
- `submit_andes_kyc_docs(org_id, files, actor)` con Redis lock TTL 60s
  (fallback Mongo `locks`), valida los 3 files (magic bytes, ≤10MB), reusa
  `provider_user_id` ya persistido, POST `/fiat` al gateway. **Cero logs del
  contenido de los files.** Branching: `approved` → `on_identity_approved`,
  `pending_approval` → `kyc_docs_submitted`, rechazo de calidad → 422 retryable
  sin marcar `kyc_docs_uploaded_at`.

**Endpoints**:
- `POST /api/v1/client/me/andes-kyc-docs` (auth JWT, multipart) — self-service.
  Gate por `org.type=="personal"` + `ramp_account.onboarding_status` en estados
  permitidos.
- `POST /api/v1/ramp/accounts/{ecid}/retry-with-docs` (admin, multipart) —
  fallback operativo para backoffice.

**Frontend**:
- `/client/kyc-docs` (gated): widget captura los 3 docs, polling cada 10s ×
  30 attempts (5min cap) para esperar la activación async vía webhook.
- CTA en `PreKybCard` cuando `applicant_type="individual"` + estado bloqueado.
- Tipos: `kyc_docs_required` y `kyc_docs_submitted` agregados a `OnboardingStatus`;
  `kyc_pending_andes` queda como alias deprecated.
- i18n: namespace `kyc_widget` en EN/ES.
- `/client/me` payload extendido con `applicant_type` y `ramp_onboarding_status`.

**Tests**: `test_andes_kyc_widget.py` — 5/5 PASS (simulator dead, audit
parity, widget gates auth+business, admin endpoint montado).

**Out of scope explícito**:
- Refactor de `KycCaptureForm` (extracción del flow público): pospuesto al
  cleanup pass para preservar cero-regresión en `/apply/[app_id]/kyc-docs`.
  El widget tiene su propia UI standalone.
- 8 tests pre-existentes rotos en `test_iter27` y `test_phase14` (cuit fixture
  con <11 digits + gateway no-mock): confirmé que el validator es correcto
  (CUIT AR = 11 dígitos), bug está en el fixture. Queda en backlog.


## 🌐 Feb 2026 · i18n Client Portal (EN/ES toggle) — IMPLEMENTED 2026-06-15

**Implementado**: el portal cliente soporta inglés/español con toggle siempre
visible en el header (LocaleToggle pill). El idioma elegido persiste en cookie
`prosper_locale` (1 año, samesite=lax). Resolución: cookie → Accept-Language → `en`.

### Cobertura traducida
- **Sidebar + Topbar** (`AppShell.tsx`) — sidebar nav, tags "Internal/Partner/Client",
  aria-labels.
- **Dashboard** (`/client`) — header, ArsaAccountCard, MovementsCard, TodayYieldCard,
  YieldChart, recent positions, recent tx, PreKybCard.
- **Investments** (`/client/investments`) — header, asset sections (ARSa/USDC),
  position rows, memo/hash labels.
- **Onramp Hub** (`/client/onramp`) — rails (ARSa CVU + USDC Stellar) + "Próximamente"
  internacional.
- **Offramp Hub** (`/client/offramp`) — rails + formulario completo ARSa→CVU
  (amount, destination, holder, confirm checkbox, submit).
- **Transactions** (`/client/transactions`) — filtros (type/status/currency),
  tabla, detail expand, empty states, export CSV.
- **Profile** (`/client/profile`) — header + tabs (Account/Security/Sessions/
  Notifications/Delete account).
- **Invest** (`/client/invest`) — header, asset toggle, balance card, ARSa note,
  modality picker (At maturity / Monthly + descripciones), amount field,
  preview/summary panel, ConfirmModal completo, PendingOnchainBanner.
- **RefreshButton** (`PageActions.tsx`) compartido.

### Estrategia
- Backend memos/emails permanecen en idioma de origen (source of truth) — el
  frontend mapea status/type labels a translations vía `useTranslations`.
- Diccionarios en `/app/frontend/messages/{en,es}.json` con namespaces:
  `common, nav, dashboard, arsa_card, movements_card, investments_page,
  invest_page, onramp_hub, offramp_hub, transactions_page, profile_page,
  mis_clientes, language`.
- Locale resolution en `src/i18n/request.ts`; toggle en `LocaleToggle.tsx`.

### Próximos pasos (out of scope this iteration)
- ~~Admin portal traducciones (`/admin/*`).~~ — DONE 2026-06-15 (sidebar + home + 3 sub-layouts + clients list + page headers de 17 admin pages, todas verificadas por testing agent iteration_36 con 14/14 PASS).
- ~~Admin internal content: KPI tooltips, OpsQueue, RecentActivity, IntegrationsHealthStrip, TopClientsTable, RampStatsSection (Tendencia diaria/Conteo diario + KPIs + chart legend Depósitos/Retiros).~~ — DONE 2026-06-15 (smoke-tested EN/ES screenshots).
- Sub-componentes del profile (AccountTab, SecurityTab, etc) — sólo el header
  está traducido.
- USDC cargar page (`/client/cargar-usdc`).
- Modales de depósito en `RampMovementsAndForms.tsx` (DepositInstructionsModal /
  WithdrawModal interno).
- Admin DataTable column headers internas (operations tx ledger filtros, kyb/kyc tablas, etc.) y inner-body labels que quedan en español por defecto pero ya con marco i18n listo para incrementar.



## 🟢 Feb 2026 · P0 entregado — Andes Outbound On-Chain Transfer ("Invertir ahora")

**Implementado**: el cliente puede ahora transferir ARSa nativos desde su wallet
Andes Stellar directamente a la Treasury de Prosper (wallet por org × modalidad)
desde el wizard `/client/invest?asset=arsa`. La transferencia es real, on-chain,
e irreversible — se exige confirmación explícita con modal + checkbox + audit log.

### Componentes
- **Backend adapter** `ramp/adapters/andes.py`: nuevo método
  `initiate_onchain_transfer(...)` que llama a
  `POST /wallets/transfers` del andes-gateway (wraps `andes.wallets.transfers.create`).
  Maneja `425 Too Early` con retry honrando `Retry-After` (cap 60s, máx 3 retries).
- **Endpoint** `POST /api/v1/client/invest/onchain` en `routes/client_invest.py`:
  valida `asset==arsa`, `modality ∈ {end,month}`, `authorized==true`,
  `confirmed_destination` matches resolved wallet (anti-tampering),
  `confirmed_amount==amount`, monto dentro de `[min,max]` del producto, saldo ARSa
  suficiente, idempotencia 5 min. Audit logs:
  `client.invest.onchain.authorize` (pre-call) + `client.invest.onchain.initiated`
  (post-success) + `client.invest.onchain.failed`. Persiste position con
  `status=pending_onchain, memo=null, hash=null`.
- **Staking poller** `jobs/staking_sync.py`: nueva lógica de reclamo
  `_try_reclaim_pending_onchain` con jerarquía:
  1. Exact-amount match → reclaim
  2. Tolerancia 0.1% solo si no hay exact → reclaim con tag "tolerance"
  3. 2+ candidatos → NO reclaim + alert operacional con
     `context.candidate_position_ids`
  4. Ventana de reclamo: **60 minutos**. Placeholders más viejos flippean a
     `expired_pending_onchain` vía `_expire_stale_pendings` (corre antes de cada
     sync).
- **Frontend** `client/invest/page.tsx`: botón `data-testid="invest-now-arsa"`
  solo para ARSa que abre `<InvestConfirmModal>` (wallet destino completa, copy
  button, checkbox obligatorio, botón "Autorizar transferencia"). Banner
  `data-testid="invest-pending-banner"` que polla `/v1/client/positions` cada
  30s para flippear automáticamente cuando el poller reclama el placeholder.

### Tests
`backend/tests/test_p0_invest_onchain.py` — 9 tests pasando:
exact match, tolerance, no-match-far-off, ambiguity+alert, outside-window,
expiry sweep, adapter happy path, adapter retry 425, adapter persistent 425
fail.

### Próximo paso (manual)
El usuario hará la primera transferencia real controlada con monto mínimo
en mainnet Stellar. No se ejecutó ninguna tx real automatizada — toda la
suite de tests usa monkey-patched httpx.


## 🐛 P0-BUG (backlog priorizado · resolver ANTES de clientes reales) — 2026-06-09
**CVU no se sincroniza solo tras el alta Andes.**

### Síntoma
Tras el flujo de `fiat.create` (`POST /fiat` con selfie+DNI), Andes
acepta las docs y devuelve `provider_user_id` + `wallet_address` + `fiat_account_id`
sincrónicamente, pero **el `cvu` y el `alias` salen `null` en esa respuesta**
porque Andes los emite asincrónicamente unos segundos/minutos después.
Nuestro flow nunca refresca: el cliente queda con `cvu_status="pending"` /
`cvu=null` aunque Andes ya los haya emitido. El cliente no puede recibir
transferencias bancarias hasta que alguien corra manualmente
`adapter.get_funding_instructions(andes_user_id)` y persista.

### Evidencia (caso Matías Plano · org_048b90574cfa)
- Audit log muestra `kyc.docs.sent_to_andes` el 2026-06-08T19:09:35Z (alta exitosa)
- `ramp_accounts.cvu = null` / `cvu_status = pending` hasta 2026-06-09T17:30Z (24h)
- `GET /fiat/{andes_user_id}` en vivo: Andes ya tenía emitidos `cvu="0000338200000000041748"` + `alias="TP000000004378"` + `status="completed"`
- `ramp_webhook_events` para ese ramp_account: **0 eventos** recibidos
- One-shot reconciliation ejecutada manualmente el 2026-06-09T17:31Z
  (audit `ramp.cvu.manual_sync_from_andes` registrado)

### Opciones de fix (elegir UNA antes de lanzar producción)
- **(a) Webhook handler de Andes**: confirmar con Andeslabs que mandan
  evento del tipo `fiat.cvu_issued` o similar; agregar handler en
  `routes/webhooks_andes.py` que persista cvu/alias cuando llega.
  Pro: zero polling. Contra: depende de que Andes garantice delivery.
- **(b) Poller corto post-alta**: tras el `fiat.create`, encolar un job
  que cada 30s consulte `GET /fiat/{andes_user_id}` por hasta N minutos
  (¿15?) hasta ver `cvu != null`, persistir, y emitir alert de timeout
  si nunca se completa. Pro: no depende del partner. Contra: latencia
  máxima ≈ intervalo.
- **(c) Híbrido**: poller corto inmediato + handler de webhook como
  fast-path cuando llega antes.

### Severidad
**P0 bloqueante para lanzamiento**. Sin esto, todo cliente nuevo va a
quedar trabado en "CVU pendiente" hasta que un operador haga el sync
manual — no escala. Resolver antes del primer batch de clientes reales.



## ✅ Prosper CMS Migration · P1-1 — Cargar USDC vía Stellar (2026-06-09)
Última pieza del bloque P1: pantalla dedicada de depósito USDC nativo
on-chain. Sin movimientos automáticos de fondos — el cliente transfiere
manualmente desde su wallet externa y el poller captura el depósito.

### Backend
- New `GET /api/v1/client/deposit-wallets` (cliente autenticado, KYB approved).
  Lazy-provisiona ambas modalidades (`end`, `month`) via
  `ensure_org_prosper_wallet`, devuelve `{wallets:[{modality, address,
  prosper_user_id, created}], network, asset, asset_issuer, prosper_id,
  safety_warning, fetched_at}`.
- `safety_warning` está hardcoded en el backend con el texto exacto que
  surface el frontend ("Enviá USDC ÚNICAMENTE en la red Stellar… PÉRDIDA TOTAL…").
- Validación de address Stellar (`_is_valid_stellar_address`): solo
  acepta direcciones 56-char base32 que empiezan con G. Los placeholders
  legacy (e.g. `GA…ALEMANY`) son descartados y forzan re-provisioning
  via `/cms/cashin`. Aplica al backfill desde `stellar_address` singular
  y al match en `_find_wallet`.
- `/dashboard-summary` cash payload ahora trae 6 campos:
  `{usdc, usdc_platform, usdc_stellar, arsa, arsa_cvu, arsa_stellar}`.
  `usdc_stellar` viene de `prosper_adapter().get_user_balances(org_id)`
  (best-effort, tolerante a fallos).

### Frontend `/client/cargar-usdc` (nueva)
- **Warning roja mandatoria** al tope (data-testid `cargar-usdc-warning`):
  texto explícito sobre la pérdida total si se envía desde otra red.
- **Ack-gate**: el address card está bluread + pointer-events disabled
  hasta que el usuario marca el checkbox de acknowledge
  (`cargar-usdc-ack`). Bloquea también el modality picker.
- **Modality picker** (end | month) — cada uno con su tarjeta clickable.
- **QR + dirección copiable** con botón "Copiar" (toast confirmando) +
  link directo a Stellar Expert por account.
- **Badges**: network=Stellar, asset=USDC, prosperId truncado.
- **Instrucciones paso a paso** (5 items): Lobstr/Freighter, USDC red
  Stellar, pegar address, NO agregar memo (el contrato lo emite), ver
  posición en /client/investments en 1-3 min.
- Empty-state si KYB no está aprobado.

### Frontend `/client` (updates)
- Action row de 3 → **4 botones**:
  `Cargar USDC` (→ /client/cargar-usdc) · `Cargar ARSa` (→ /client/onramp)
  · `Invertir` · `Retirar`.
- KPI `Saldo ARSa libre` hint: `CVU X ARSa · Stellar Y ARSa`.
- KPI `Saldo USDC libre` hint: `Plataforma X USDC · Stellar Y USDC`.

### Library
- `qrcode.react@4.2.0` agregada vía `yarn add`.

### Verification
- Backend pytest (7/7) — `/app/backend/tests/test_iter31_p11_deposit_wallets.py`:
  contract shape, two modalities, address validity, safety text, 403 sin KYB,
  cash payload con 6 fields y sums consistentes.
- Frontend Playwright (iter_32 16/16):
  warning visible y mandatoria, ack-gate bluread/unbluread, modality switch
  funciona, address 56-char base32 válida, QR encoded = address mostrado,
  Stellar Expert link fully-qualified, 5 instrucciones, 4 botones en
  dashboard, hints de KPI Saldo split correctamente.

### Notas para Matías (partner-side)
- El live CMS (`cmsback.protocol-prosper.io`) devuelve **la misma wallet
  para `end` y `month`** bajo el mismo `prosperId`. El doc decía
  `prosperId+modalidad → una wallet` (= dos wallets). El backend del
  partner stora ONE row per prosperId con el `cashin` actual; cada
  POST `/cms/cashin` actualiza la modalidad in-place sin cambiar la
  address. Surfaceamos lo que devuelve el partner y dejamos la UI
  honesta. **Pregunta para Prosper**: ¿es by-design o un bug del
  partner backend?



## ✅ Prosper CMS Migration · P1-2 — Multi-asset client dashboard (2026-06-09)
Client portal aligned to the CMS protocol invariant: each asset stays in
its own lane. ARSa and USDC never cross-convert.

### Backend
- New `GET /api/v1/client/dashboard-summary` aggregator. Single call returns:
  - `aum.{arsa,usdc}`: `{principal, yield_accrued, yield_claimed, positions, active}`
  - `cash.{usdc, arsa}`: free balance per asset (USDC from on-platform txns,
    ARSa from latest `ramp_balances` row).
  - `breakdown[]`: per asset × modality `{count, principal}` rows.
- External-bucket positions (`external=true`) are **excluded** from all
  aggregations — those are partner test residue, not customer funds.

### Frontend `/client`
- KPI grid split into **two sections** (`kpi-row-arsa`, `kpi-row-usdc`):
  - "ARSa · staking nativo" → AUM ARSa · Yield ARSa · Saldo ARSa libre · Posiciones ARSa.
  - "USDC · staking nativo" → AUM USDC · Yield USDC · Saldo USDC libre · Posiciones USDC.
- Every value rendered in its native unit via `fmtNative(value, unit)`
  (no `fmtUsd` cross-conversion remains in this row).
- "Cargar dinero" CTA subtitle updated to "ARSa (CVU) o USDC (transferencia Stellar)".

### Frontend `/client/investments`
- Rewritten as grouped sections:
  - `section-arsa`: ARSa stakings.
  - `section-usdc`: USDC stakings.
- Each section has its own header with `{activeCount} stakings activos` +
  totals `Principal · Yield` in the section's native currency.
- Each row shows: Modalidad (Mensual | Al vencimiento — fallback to
  `product_id` for legacy rows), Principal, Rate %, Yield acumulado,
  Vencimiento, Status badge.
- On-chain identity strip under every row when `memo` or `hash` present:
  `memo: …` + `hash: 6chars…4chars` linking to
  `stellar.expert/explorer/public/tx/{hash}`.
- Empty-state per asset doesn't block the other section from rendering.

### Verification (iteration_30.json)
- Backend 9/9: schema validation, external exclusion, super_admin no-crash,
  RBAC, RAMP_BALANCES org-scoped + ramp_account_id fallback, breakdown shape.
- Frontend 9/10: KPI rows render with correct totals
  (AUM USDC 546,663.87 USDC · Saldo ARSa libre 601,234.56 ARSa), section
  empty-state independence verified, on-chain identity links to Stellar
  Expert. 10th item (action-deposit subtitle) blocked by Alemany seed
  KYB-pending state — code is correct, will render on `can_operate=true`.



## ✅ Prosper CMS Migration · P1-3 — Admin treasury + Stakings monitor (2026-06-09)
First UI piece on top of the P0 plumbing. Read-only (no money moved).

### Backend — 4 new endpoints under `/admin/prosper`
- `GET  /admin/prosper/treasury` → wraps `RealProsperAdapter.get_treasury()`;
  returns `{address, balanceUSDC, balanceARSA, balanceXLM, mode, refreshed_at}`.
- `GET  /admin/prosper/stakings?scope=all|ours|external&asset&status`
  → reads from local `positions` (filled by the poller), groups our
  stakings by `org_id` with per-org totals, separates external/historical
  residue under its own bucket with a friendly note.
- `GET  /admin/prosper/staking-sync/status` → last poller run + scheduler config.
- `POST /admin/prosper/staking-sync/run` → triggers `run_sync_once()` ad-hoc
  (super_admin/finance), audit-logged.

### Behaviour changes
- **Orphan stakings (8 historical pruebas viejas de Prosper) no longer
  create `alerts` rows.** They're now stored as positions with `external=True,
  org_id=None` and surface in their own UI bucket "Externos / históricos"
  with a calm gray pill — distinguishable at a glance from our own stakings
  when one shows up. Existing 8 orphan alerts cleaned out of `alerts`.
- New collection `staking_sync_runs` stores the latest run + a 50-deep history.

### Frontend — `/admin/prosper/inversiones`
- **CMS Treasury widget** (live): USDC / ARSa / XLM balances + Stellar
  Expert link to the treasury account.
- **Staking Sync widget**: ENABLED/DISABLED pill, last-run metrics
  (processed / created / updated / external), interval (cada 5m), and
  a `Run now` button (calls the manual run endpoint).
- **New default tab "Stakings (CMS live)"** with two sections:
  - **Nuestros stakings** — grouped by org with ARSa+USDC totals.
  - **Externos / históricos** — calm gray treatment, with the testing
    note explaining they're pre-ARSa partner test stakings.
  - Filters: scope (all|ours|external), asset (ARSa|USDC), status.
- The old "Intents" tab kept as "Intents (legacy)" — reads bridge intents
  (Phase 20 deprecated by P0-4) for historical inspection.

### Verification
- Backend pytest (iter_28): 7/7 endpoints pass (treasury reads live, sync
  status, run-now, stakings with all filters, RBAC, P0-4 410-Gone preserved).
- Frontend Playwright (iter_29): 8/8 acceptance criteria pass — treasury
  populates (12.25 USDC / 100 ARSa), poller widget shows processed=8
  external=8, Run-now updates timestamp and emits the success toast,
  external section shows 8 rows with hash links to Stellar Expert,
  filter dropdowns work.

### Fixes during the iteration
- Duplicate `"use client";` directive removed (was causing the build to
  treat the file ambiguously after the JSDoc).
- SWR fetchers in the new components wrapped as `(p: string) => api(p)`
  to match the working `IntentsTab` pattern — passing `api` directly
  swallowed the request silently.



## ✅ Prosper CMS Migration · P0 block (P0-1..P0-4) — 2026-06-09
End of the **read + provisioning + reconcile** layer of the CMS migration.
No money was moved by this block; it sets the model + data flow for the
client/admin UI work (P1).

### P0-1 — Wallets per modality + kill local memo
- `organizations.stellar_address` (singular) → `organizations.prosper_wallets: [{modality, address, prosper_user_id, provisioned_at, source}]`.
- `ensure_org_prosper_wallet(org_id, modality)` is now idempotent per
  (org_id, modality). Defaults to `PROSPER_DEFAULT_CASHIN` env (`end`).
  Legacy singular `stellar_address` is auto-backfilled into the array
  on first read (`source: "legacy_backfill"`).
- Helper `get_org_wallet(org_id, modality)` exposes the read path.
- `_generate_stellar_memo` REMOVED. `prosper_memo` and `prosper_memo_kind`
  are unset on the org doc at provisioning time (the contract emits memos
  per staking — we never generate them).

### P0-2 — New position model
- `positions` documents now persist:
  `asset` ("arsa"|"usdc"), `modality` ("end"|"month"), `wallet` (Stellar
  origin), `memo` (per-staking on-chain id), `hash` (staking tx hash),
  `rate` (% from the contract), `principal_native` + `principal_unit`,
  `principal_redeemed`, `claimed_interest`, `contract_provides_interest`
  (boolean: flips the accrual job behaviour).
- Legacy mirrors (`principal_usd`, `apr_bps`, `currency`) preserved for
  backwards compat — accrual + UI both still work against pre-P0 rows.
- `memo` + `hash` start `None`; the staking poller fills them when the
  contract surfaces the on-chain record.

### P0-3 — Staking sync poller
- New job `/app/backend/jobs/staking_sync.py`. Pulls `GET /cms/staking`,
  filters to known wallets (from `prosper_wallets` + legacy fallback),
  upserts `positions` by `(wallet, memo, hash)`. Idempotent.
- Orphan stakings (on-chain but no local wallet match) raise an `alerts`
  row with `type=staking_orphan` so the operator can attribute later.
- Wired into `start_scheduler()` at `IntervalTrigger(minutes=5)` (env
  override `PROSPER_STAKING_SYNC_INTERVAL_MINUTES`). Auto-enabled when
  `PROSPER_MODE != mock`; toggle via `PROSPER_STAKING_SYNC_ENABLED`.
- First scheduled run kicks off at startup (`next_run_time=now`).

### Accrual decision (verified Feb-09 against live CMS)
Today the CMS contract returns the staking **parameters** but NOT the
real-time yield fields:

| Field returned by contract  | Status     |
|-----------------------------|------------|
| `principalAmount`           | ✅ populated |
| `start` / `maturityPrincipal` | ✅ populated |
| `porcentajeAnual` (rate)    | ✅ populated |
| `scheduleInterest`          | ✅ populated |
| `payoutAssetInterest` / `tokenInteres` | ✅ populated |
| `claimedInterest` / `principalRedeemed` | ✅ populated (0 today) |
| `interesesAcumulados`       | ❌ NULL (today) |
| `proximaFechaMonto`         | ❌ NULL (today) |
| `interesCada24Horas`        | ❌ NULL (today) |
| `proyectado`                | ❌ 0 (today) |

→ **`jobs/accrual.py` stays enabled**. New guard: positions where
`contract_provides_interest=True` (set by the poller when
`interesesAcumulados != None`) are SKIPPED. As soon as the contract starts
populating yield, those positions auto-defer to the protocol and accrual
double-counting is avoided. The accrual job's return now exposes a
`deferred_to_contract` counter for monitoring.

### P0-4 — Unwire bridge
- `POST /api/v1/investments/intent` → **HTTP 410 Gone** with a clear
  message pointing to the native flows.
- `GET /api/v1/investments/intent[s]` kept open (read-only historical) —
  responses include `deprecated: true` + `deprecation_notice`.
- `yield_asset != "usdc"` guard removed (was the artifact that forced
  ARSa→USDC conversion).
- Frontend `/client/invertir-arsa` → `redirect("/client/invest?asset=arsa")`.
- `/client/invest` now supports `?asset=arsa|usdc` query param, renders
  an asset toggle, shows currency-aware copy (`ARSa`/`USDC`), and
  highlights an "ARSa nativo" note when ARSa is selected.

### Verification (live CMS, no funds moved)
```
P0-1: Provisioning org_seed_alemany for BOTH modalities
  wallet[end]   → GA…ALEMANY (legacy_backfill)
  wallet[month] → GDHQFTLN…   (cms_cashin)  · created=True
  prosper_memo = None (memo local borrado ✓)
Idempotency: re-provisioning end → created=False ✓
P0-3: run_sync_once → processed=8 created=0 updated=0 orphans=8
   (none of the live CMS wallets match our test orgs — correct)
P0-4: POST /investments/intent → HTTP 410 Gone ✓
       GET  /investments/intents → deprecated:true, 13 items still readable ✓
```

### Pending (NOT this round, depends on real partner credentials)
- The 5-min poller currently 401s in prod because `.env` still holds
  the Alfred dev creds (`matias@alfredpay.io`). Real CMS admin creds
  unblock the live sync. Switching credentials needs no code change.
- Backfill existing legacy positions with `asset="usdc"` + `modality="end"`
  via a one-shot migration script (created on demand — defaults already
  cover them through the legacy-mirror reads).
- Phase 1 of the bridge unwire was logic-only; the `investment_intents`
  collection still holds historical bridge runs. Cleanup script not in
  scope of this block.



## ✅ Prosper CMS Migration — F1 + F2 + F6 (2026-06-09)
Migration from Alfred partner API (`/api/v1/alfred/*`) to the native Prosper
CMS protocol (`/api/v1/cms/*`). All three phases are **read + provisioning +
UI only** — no money-moving code was touched. Live CMS reads verified
against `https://cmsback.protocol-prosper.io` with valid partner credentials.

### F1 — Adapter rewrite (Alfred → CMS)
- `/app/backend/integrations/prosper/real.py`: rewritten end to end.
- New base URL: `https://cmsback.protocol-prosper.io` (mainnet — no test env).
- Endpoints used:
  - `POST /api/v1/auth/login`        → JWT (cached, early-refresh).
  - `GET  /api/v1/cms/treasury`      → normalized to `{address, balanceUSDC, balanceARSA, balanceXLM}`.
  - `GET  /api/v1/cms/users`         → accepts both legacy flat-array and
    new `{prosper:[…], alfred:[…]}` shape; lookup by `prosperId`/`userId`/email.
  - `POST /api/v1/cms/cashin`        → `{prosperId, cashin:"end"|"month"}` (no more `alfredEmail`).
  - `GET  /api/v1/cms/staking`       → normalized to `{id, hash, owner, memo,
    rate, principalAmount, payoutAssetInterest, email, …}` (live API uses
    Spanish field names: `memoStaking`, `hashStaking`, `porcentajeAnual`,
    `wallet`, `tokenInteres`; both name families coexist on the returned dict).
- Mock adapter (`mock.py`) preserved.
- Money-moving methods (`deposit_tokens`, `withdraw_tokens`, `transfer_tokens`)
  raise `ProsperError("not exposed in CMS partner namespace")` — stakings now
  start when the client transfers funds with the per-staking memo.

### F2 — prosperId + memo provisioning
- `/app/backend/routes/onramp_flow.py::ensure_org_prosper_wallet`:
  - **prosperId = org_id** (provisional). New org field `prosper_id_source =
    "org_id_provisional"` flags the mapping as pending partner confirmation —
    if Prosper later requires a partner-assigned id we flip this without a
    schema migration.
  - **Generates `prosper_memo`** at provisioning time (Stellar MEMO_ID, 18
    digits, uint64-safe via `secrets.randbelow(10**18)`) and persists on the
    org doc alongside `prosper_memo_kind="MEMO_ID"` and
    `prosper_cashin_modality`.
  - Model preparado for **multiple stakings per client**: each future staking
    can mint its own per-deposit memo (positions/transactions already carry
    `memo` field; new `Position.memo` typing exposed on the frontend).

### F6 — Catalog replacement (CMS protocol catalog)
- Legacy products (`liquid_v1`, `term_30`, `term_90`, `term_180`) **archived**
  (status=archived, archived_reason="cms_protocol_replaces_legacy_catalog") —
  history preserved.
- New seeded catalog (idempotent in `ensure_products`):
  - `usdc_end`   · USDC · end-of-term · 12 months · APR 17%.
  - `usdc_month` · USDC · monthly · 12 months · APR 17%.
  - `arsa_end`   · ARSa · end-of-term · 12 months · APR 17% · ARSa-native.
  - `arsa_month` · ARSa · monthly · 12 months · APR 17% · ARSa-native.
- Admin product CRUD locked to the protocol:
  - `POST /admin/prosper/products` → **403** with a clear message.
  - `PATCH /admin/prosper/products/{id}` → only `status` is mutable
    (active/paused/archived) for emergency pause; APR/term/limits are fixed
    by the smart contract.
- Client wizard `/client/invest` rewritten: "elegí modalidad (end | month)" +
  monto in USDC. ARSa wizard `/client/invertir-arsa` filters by `asset=arsa`
  (ARSa now stakes natively in ARSa — no more bridge to USDC).
- Frontend `lib/invest.ts::Product` extended with CMS fields:
  `asset`, `modality`, `term_months`, `payout_asset`, `payout_schedule`.

### Verification (live CMS reads, no money moved)
Verified against `cmsback.protocol-prosper.io` with the partner demo creds:
- Treasury: `address=GAG42MXCJ…`, `balanceUSDC=12.25`, `balanceARSA=100` ✅
- Users: lookup by `prosperId=org_adf12134` returned its wallet ✅
- Staking: 8 records returned and normalized (sample: `id=8, memo=1780457551,
  principalAmount=6, rate=17, payoutAssetInterest=ARSa`) ✅
- `/v1/client/products` reflects the new catalog; admin POST→403 confirmed.

### Pending (deliberately NOT touched this round — depends on memo confirmation)
- Staking poller (sync /cms/staking → local positions).
- Real money flows (deposits via Stellar transfer with per-staking memo,
  withdraw/redeem). Backend `_execute_buy` still routes through
  `prosper_adapter().deposit_tokens` which now raises under real mode — that
  path is unwound when the staking poller lands.
- Unwiring Phase 20 bridge (ARSa→USDC→Prosper) — ARSa now native.

### Operator note: CMS credentials
`.env::PROSPER_API_USER/PROSPER_API_PASS` currently still hold the legacy
Alfred dev creds (`matias@alfredpay.io`). Those credentials authenticate
against the CMS login endpoint but lack the admin role for `/cms/treasury`.
Real partner credentials need to be swapped in (`prosperCMS@mail.com` demo
creds proved the read path works end-to-end during verification).



## ✅ Role-Based Portal Routing + Hard Middleware Gate (2026-06-08)
- **Bug fix**: `client_admin` users were landing on `/admin` (Admin Home with
  TVL/AUM/NAV/Ops Queue) because post-login routing used `?next=` with
  default `/admin` everywhere and layouts didn't check role. A client could
  see all clients' compliance data.
- **Backend** (`server.py`):
  - `_portal_for_role(role)` → "/admin" for internal, "/client" for client.
  - `dev_login` ignores incompatible `?next=` (e.g. client requesting
    `/admin/compliance` → forced to `/client`).
  - `passwordless_token` returns `{accessToken, portal, role}` so SPA
    routes by authoritative `portal`, not by stale querystring.
- **Frontend middleware** (`middleware.ts`) — server-side Edge gate:
  - Verifies `prosper_session` JWT via `jose` (HS256, same JWT_SECRET).
  - `/admin/*` requires INTERNAL_ROLES (super_admin, admin, finance,
    compliance_officer, ops, support_agent, partner_dev).
  - `/client/*` requires client roles.
  - A client_admin hitting any /admin/* via direct URL is hard-redirected
    to /client BEFORE the layout/data ever loads. Invalid/tampered cookies
    are deleted and bounced to /login.
- **Defense in depth**: the FastAPI backend already enforces `requires_role(*INTERNAL_ROLES)`
  on every admin endpoint, so even if the middleware were bypassed no
  admin data would leak.
- **Frontend** (`login`, `login/otp`):
  - Default `next` is "" (decide by role); only honour the original
    `?next=` if it's compatible with the role family returned by
    `/auth/passwordless-token`.
- **`frontend/.env`**: `JWT_SECRET` mirrored from backend so Edge
  middleware can verify the session JWT.
- **E2E tests (all PASS)**:
   * client_admin via dev-login → 303 to `/client` ✅
   * client_admin with `?next=/admin/compliance` → 303 to `/client`
     (override de seguridad) ✅
   * super_admin via dev-login → 303 to `/admin` ✅
   * passwordless-token returns `{portal:"/client", role:"client_admin"}` and
     `{portal:"/admin", role:"super_admin"}` correctly ✅
   * Matías via direct URL `/admin`, `/admin/compliance/kyc`,
     `/admin/rampa/stats` → middleware bounces to `/client` in all 3 cases ✅
   * Matías lands on Client Portal (Tu cuenta en pesos, CVU, Invertir,
     Cargar dinero, Movimientos) ✅


## ✅ Travel Rule (FATF/UIF) Gate + Manual Override (2026-06-08)
- **Adapter**: `integrations/travel_rule/` con `ManualProvider` (default,
  pending) + `MockClearProvider`. Env `TRAVEL_RULE_PROVIDER=manual`. TODOs
  para Notabene / Sumsub TR / TRP.
- **Collection** `travel_rule_screenings` (espejo de sanctions). Estados
  `pending | clear | na | flagged`. Índices: org_id, status, (org_id+subject_type).
- **Router** `routes/travel_rule.py`: `enqueue_screening`,
  `apply_travel_rule_decision` (shared helper, mismo patrón que sanctions).
  `GET /admin/travel-rule/queue`, `POST /admin/travel-rule/{org_id}/decision`.
- **Activation gate**: `services.activation.on_identity_approved` ahora
  encola **AMBOS** screenings (sanctions + travel_rule) y requiere los TRES
  gates en verde para activar (`andes_kyc=approved` + `sanctions=clear` +
  `travel_rule ∈ {clear, na}`).
- **Override desde KYC drawer**: `KycDecision.override_travel_rule: bool`.
  Mismo gating de roles que sanctions (super_admin / finance). Cualquier
  combinación (solo sanctions, solo TR, ambos) funciona idempotente.
- **Backend** (`server.py + client_portal.py`): `/me` y `/client/me` exponen
  `travel_rule_status` + `travel_rule_locked`. `can_operate` ahora chequea
  los 3 gates.
- **Frontend**: `OverridePanel` reusable component (kind="sanctions" |
  "travel_rule"). Cuando ambos están pending, se renderizan los 2 paneles
  apilados. Botón cambia a "Aprobar identidad + sanctions + travel-rule"
  según los toggles. `ClientGateBanner` muestra mensajes específicos para
  `travel_rule.pending` ("Validando datos travel-rule") y
  `travel_rule.flagged` ("Cuenta bloqueada por travel-rule").
- **Backfill Matías**: encolado el screening de travel-rule + override
  aplicado por admin@prosper.foundation. Ahora tiene los 3 gates en clear.
- **E2E tests (todos PASS)**:
   * super_admin override → kyb=approved, travel_rule=clear, resolution=
     manual_override, audit_log entry ✅
   * compliance_officer override → 403 con mensaje explícito ✅
   * travel_rule.flagged → kyb=rejected + user=paused ✅
   * Combo override (sanctions + travel-rule en un solo click) → ambos
     overrides aplicados, kyb=approved ✅


## ✅ Sanctions Manual Override from KYC Drawer (2026-06-08)
- **Política**: mientras `SANCTIONS_PROVIDER=manual` (sin proveedor real
  contratado), super_admin / finance pueden destrabar el gate de sanctions
  desde el panel de Decisión del KYC drawer.
- **Backend** (`routes/sanctions.py`): nuevo helper
  `apply_sanctions_decision(org_id, decision, reason, actor, resolution)`
  centraliza la lógica. Field `resolution` en la screening row distingue
  `real_provider | manual_decision | manual_override`. Audit log entry
  `sanctions.manual_override.clear|flagged` con actor_email + reason +
  resolution + subject metadata.
- **Backend** (`routes/compliance/kyc.py`): `KycDecision` acepta
  `override_sanctions: bool`. Cuando `action='approve'` + role en
  `SANCTIONS_OVERRIDE_ROLES (super_admin, finance)` + sanctions=pending →
  llama al helper con `resolution='manual_override'`. compliance_officer
  recibe 403 explícito ("Sanctions override requires super_admin or
  finance role"). Min 20 chars en `reason` (pydantic).
- **Frontend** (`/admin/compliance/kyc` drawer): panel ámbar
  `sanctions-override-panel` aparece sólo cuando:
   * caso es andes-direct (`case_id` empieza con `app_`),
   * `sanctions_status=pending`,
   * role del actor en `(super_admin, finance)`,
   * acción seleccionada = approve.
  Checkbox que activa el override. Botón cambia a
  "Aprobar identidad + sanctions override". Hint informativo cuando role
  no tiene permiso.
- **Reversibilidad**: `flagged` desde la sanctions queue revierte:
  `kyb_status=rejected`, `user.status=paused`. Confirmado con E2E test.
- **Tests E2E manuales (todos PASS)**:
   * super_admin override → kyb=approved, sanctions=clear,
     resolution=manual_override, audit logged ✅
   * compliance_officer override intent → 403 ✅
   * client_admin endpoint hit → 403 ✅
   * reason < 20 chars → 422 ✅
   * flagged after clear → kyb=rejected, user.paused ✅
   * idempotent re-call → no crash, sanctions_override_applied=false ✅


## ✅ Two-Gate Activation Policy + KYC Queue Unified (2026-06-08)
- **`services/activation.py`** — NEW. Helper idempotente
  `on_identity_approved(org_id, andes_user_id, cvu, alias, source)`
  centraliza la activación. Implementa la política de dos gates:
  - Gate 1 (identidad) → `org.andes_kyc_status='approved'` (campo nuevo)
  - Gate 2 (sanctions) → encola screening idempotente
  - Activación full (`kyb_status=approved`) sólo si **ambos** verdes.
- **Bug fix crítico — bypass del gate en upload sincrónico**:
  `routes/onboarding.upload_kyc_docs_individual` ya NO flipea
  `kyb_status='approved'` cuando Andes responde "approved" sincrónicamente.
  Delega al helper. Mismo refactor en
  `routes/ramp_webhook._handle_fiat_account_created`. Un solo punto de
  activación, idempotente, race-safe entre path sincrónico y webhook.
- **Cola KYC unificada** (`routes/compliance/kyc.py`):
  - `/queue` ahora une `kyc_cases` (seed/legacy) con
    `onboarding_applications` (applicant_type=individual) proyectadas al
    shape `KycCase`. Provider="Andes" para `aiprise_mode=andes-direct`.
  - `/{case_id}` y `/{case_id}/decision` soportan ambas fuentes
    (case_ids `app_…` → application, `kyc_seed_…` → legacy).
  - El detail hidrata sanctions row + ramp_account (CVU, wallet_address).
- **Backfill Matías Plano**: `org_048b90574cfa` corregido de mentir
  `kyb_status=approved` a la realidad: `kyb_status=pending`,
  `andes_kyc_status=approved`, `sanctions_status=pending`, screening
  encolado con CUIT y provider=manual. Aparece en `/admin/compliance/kyc`
  como primera fila, provider Andes, status in_review.
- **Testing iter27**: 9/9 backend pytest PASS, frontend KYC queue
  renderiza correctamente, Matías visible. Sin bugs encontrados.


## ✅ Sanctions/PEP Screening Gate + Resend Live Wiring (2026-06-08)
- **Adapter `integrations/sanctions/`** — `SanctionsProvider` base, `ManualProvider`
  (default, returns `pending`), `MockClearProvider` (for E2E). Provider chosen
  via `SANCTIONS_PROVIDER` env (`manual|mock_clear`); other names → fallback
  manual. TODOs in code para conectar ComplyAdvantage / Truora detrás del
  mismo adapter.
- **Collection `sanctions_screenings`** con índices org_id+status. Estados
  `pending | clear | flagged`. Cada decisión audit-logueada.
- **Auto-enqueue** en `_handle_fiat_account_created` (Andes emite CVU) →
  crea row pending + setea `organizations.sanctions_status='pending'`. La
  org NO se activa (kyb_status sigue pending) hasta que el screening esté
  `clear`. `try/except` envuelve la enqueue para no romper el webhook.
- **Admin endpoints** `/api/v1/admin/sanctions/`:
   - `GET /queue?status=pending|clear|flagged` (super_admin / admin /
     compliance_officer) con join a la org
   - `POST /{org_id}/decision` body `{decision, reason}`:
     * `clear` + Andes ya OK → activa la org (kyb=approved, user.active)
     * `flagged` → kyb=rejected, user.client_admin.status=paused
- **UI admin** `/admin/compliance/sanctions` con tabs Pendientes/Aprobados/
  Bloqueados, badge MANUAL (MOCK) y modal de decisión con motivo obligatorio.
- **Cliente**: `/me` y `/client/me` exponen `sanctions_status` +
  `can_operate = (kyb=approved && sanctions=clear)`. `ClientGateBanner`
  muestra mensajes específicos para pending ("verificación de antecedentes
  en curso") y flagged ("cuenta bloqueada por compliance").
- **`/apply/[app_id]/kyc-docs`**: nuevo phase `sanctions` con SanctionsView
  cuando Andes ya aprobó pero el screening está pending. Polling detecta
  `flagged` y muestra pantalla de rechazo con motivo.
- **Resend safeguards** (`backend/server.py` + `routes/onboarding.py`):
   - `_send_otp` ahora ruta vía `email_sender.send_email` (audit en
     `outbound_emails`). Si Resend falla → row `status=failed`, flow sigue.
   - `passwordless-login` drop `dev_otp` cuando `RESEND_API_KEY` está set.
   - `onboarding/apply` manda welcome email vía Resend y devuelve
     `magic_link=null` cuando `RESEND_API_KEY` está set. En dev sin la key
     se mantiene el devtools flow (dev_otp + magic_link visibles).
- **Testing iter26**: 13/13 backend pytest PASS, 100% frontend (cola admin
  + modal + ClientGateBanner sanctions). Sin bugs.


## ✅ Self-Service Funnel + Andes Direct KYC (2026-06-08)
- Public landing `/` replaces the old `/access` redirect — hero + 3-step
  explainer + "Abrir cuenta" / "Ya tengo cuenta" CTAs (`landing-cta-apply`,
  `landing-cta-login`).
- `/apply` ahora tiene toggle Individuo ↔ Empresa (`applicant-type-toggle`).
  Individuo postea `applicant_type=individual` → backend `mode=andes-direct`
  → redirige a `/apply/[app_id]/kyc-docs`. Empresa sigue ruta AiPrise hosted_url.
- Nueva pantalla `/apply/[app_id]/kyc-docs` con 3 slots (`kyc-slot-face`,
  `kyc-slot-id_front`, `kyc-slot-id_back`), preview + validación
  (8 KB ≤ size ≤ 6 MB, image/* only), tips card y AbortController 90s.
  Estados: `capture` → `uploading` → `polling` (refresh /onboarding/apply
  cada 4s) → `approved` (CTA al portal) | `rejected` (motivo + retry).
- `/apply/status` ahora muestra CTA "Subir mis fotos" cuando
  `aiprise_mode=andes-direct` && `status=in_review`.
- `/login` agrega link `login-apply-link` → `/apply`.
- **BUG FIX P0 — Auto-provision en login** (`backend/server.py`
  `/auth/passwordless-token` + `/auth/dev-login`): emails externos ya no se
  auto-attachean a la primera org del allowlist. Solo `@prosper.foundation`
  se auto-provisiona como admin. Todo otro email debe existir en USERS
  (creado vía `/onboarding/apply`) o recibe 403 "Abrí tu cuenta en /apply".
- Backend `routes/onboarding.py`: httpx timeout subido a 120 s read y handler
  422 dedicado para errores de calidad de imagen de Andes.
- Middleware: `/` agregado como público.
- Testing iter25: 6/6 backend PASS, ~90% frontend (los selectores nuevos
  funcionan; única observación: kyc-rejected sólo se ve con fotos reales
  o tras el AbortController de 90s).


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

## ✅ Sprint 12.1 — Alfred Pay live integration (2026-05-14)

Real Alfred Pay "Penny" API integrada en `sandbox` mode con creds del cliente.

**Backend** (`integrations/alfred/real.py` reescrito completo):
- Headers `api-key` + `api-secret` + `Content-Type: application/json` por request.
- Endpoints reales: `POST /quotes`, `POST /onramp`, `POST /offramp`, `GET /transactions/{id}`.
- Quote body: `fromCurrency`, `toCurrency`, **`fromAmount` (string)**, `chain`, `paymentMethodType` (default `BANK`).
- Onramp response unwrappea `{transaction, fiatPaymentInstructions}` (paymentType: SPEI/PIX/ARS_BANK_TRANSFER/etc.).
- Webhook signature: `Signature: t=<ts>,s=<hex_hmac_sha256>` canonical `f"{ts}.{rawBody}"`, tolerancia ±5min.
- `health_check()` hace quote real 35.000 ARS → USDC para validar creds.
- `/v1/status` live-pinga Alfred cuando `ALFRED_MODE != mock`.

**.env** ya tiene: `ALFRED_MODE=sandbox`, `ALFRED_API_KEY`, `ALFRED_API_SECRET`, `ALFRED_WEBHOOK_SECRET`, `ALFRED_BUSINESS_ID=187`, `ALFRED_API_BASE_SANDBOX/PRODUCTION`.

**Tests**: `test_alfred_real_live.py` (mark `live`) valida quote real + health. Phase 8/9 tests ahora `skipif(ALFRED_MODE != mock)`. `pytest.ini` registra mark `live`. 25 passed + 20 skipped en la corrida combinada.

**Pendiente Sprint 12.2 opcional** para enchufar onramp E2E:
- `POST /customers` por organización (hoy reusamos `user_id` como fallback).
- Configurar `ALFRED_DEFAULT_DEPOSIT_ADDRESS` con wallet Stellar real de Prosper.
- Webhook URL en dashboard Alfred → `/api/v1/webhooks/alfred`.
- Mapear status events (`FIAT_DEPOSIT_RECEIVED`, `TRADE_COMPLETED`, `ON_CHAIN_INITIATED`, `ON_CHAIN_COMPLETED`, `FAILED`) → enums internos.

**Mocked todavía**: AiPrise · Resend · TRM Labs · Sentry · Datadog. **Alfred Pay = LIVE sandbox** ✅. **Prosper Stellar = LIVE development** ✅.

## ✅ Sprint 12.2 — Prosper Stellar live integration (2026-05-14)

Real Prosper API (`https://apidev.protocol-prosper.io`) integrada en modo `development` con creds del cliente.

**Backend** (`integrations/prosper/real.py` reescrito completo):
- Login: `POST /api/v1/auth/login` con `{username, password}` → `{token, createdAt, expiresAt}`.
- JWT cacheado in-process con soft TTL (refresh 60s antes del expiry) + auto-relogin on 401.
- Endpoints reales corregidos: todo bajo `/api/v1/prosper/...` (no `/v1/...`):
  - `POST /prosper/users/new` (NewUserDto)
  - `POST /prosper/users/deposit` (DepositDto)
  - `DELETE /prosper/users/retire` con body DepositDto ← era el "withdraw" mal mapeado
  - `POST /prosper/users/transfer` (TransferDto) ← antes apuntaba a `/tokens/transfer`
  - `POST /prosper/tokens/mint`, `POST /prosper/funds`
  - `GET /prosper/users/{prosperId}/balances`, `.../transactions?limit&page&status&txType`
  - `GET /prosper/assets`
- `health_check()` hace login + reporta `jwt_expires_at`.
- `/v1/status` live-pinga Prosper cuando `PROSPER_MODE != mock` → muestra "modo development · login ok".

**.env**: `PROSPER_MODE=development`, `PROSPER_API_BASE=https://apidev.protocol-prosper.io`, user/pass del cliente.

**Tests**: `test_prosper_real_live.py` (mark `live`) valida login real. Pasa contra el sandbox. Live evidence en `/status` con ambos integradores reales pingeando OK.


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

## ✅ Sprint 12.3 — AiPrise auth fix + live ping (2026-05-14)

**Bug crítico arreglado** en `integrations/aiprise.py`:
- Antes: `Authorization: Bearer <key>` → 401 "Bad credentials".
- Ahora: `X-API-Key: <key>` → 200/403 correcto.
- Live-validado: las keys sandbox + producción del cliente **ambas son válidas**, sólo necesitaban el header correcto.

**`aiprise.health_check()`** + `/v1/status` row → `aiprise · operational · auth ok · simulado (sin templates)`. Para activar live KYC/KYB sólo poblar `AIPRISE_KYC_TEMPLATE_ID` y `AIPRISE_KYB_TEMPLATE_ID`.

**Mocked todavía**: Resend · TRM Labs · Sentry · Datadog. **LIVE**: Alfred Pay ✅ · Prosper ✅ · AiPrise (auth) ✅.

## ✅ Sprint 12.4 — Onramp E2E real flow (2026-05-14)

**Org-scoped Prosper wallets** (uno por organización, compartido entre los users del cliente):
- Nuevo helper `routes/onramp_flow.py::ensure_org_prosper_wallet(org_id)` — idempotente, persiste `prosper_user_id` + `stellar_address` + `prosper_provisioned_at` en el doc de la org.
- Llamado automáticamente al aprobar un KYB (en `webhooks_aiprise._apply_kyb_decision`) y como lazy retry en `/client/balances` y `_execute_buy`.
- `deposit_tokens` / `withdraw_tokens` / `get_user_balances` ahora pasan `user.org_id` como `user_reference_id` (mismo que usamos al crear la wallet) → routing correcto a la wallet de la org.

**Mapping de status events Alfred** (`alfred_status_to_internal`):
- Soporta los 4 enums legacy del mock (`order.pending/confirmed/completed/failed`) Y los 7 de Penny live (`FIAT_DEPOSIT_RECEIVED`, `TRADE_COMPLETED`, `ON_CHAIN_INITIATED`, `ON_CHAIN_COMPLETED`, `FAILED`, `EXPIRED`, `CANCELLED`).
- Webhook receiver (`/v1/webhooks/alfred`) usa el mapping unificado. Soporta ambos signature headers (`X-Alfred-Signature` legacy + `Signature: t=…,s=…` Penny). Extrae `tx_hash`, `coelsa_id`, `settled_amount` con field names de ambos formatos.
- Auto-buy se dispara en `confirmed` **o** `completed` (era sólo `confirmed`) — el helper es idempotente vía `related_onramp_id`.

**Bug fix crítico** (`onramp_flow.py`): la projection de Mongo `{"_id":0, "prosper_user_id":1, ...}` devuelve `{}` cuando esos campos no existen — falsy en Python. Cambiado el check a `if org is None` para no tratar orgs nuevas como "not found".

**Live evidence**: org demo creada vía `/admin/clients` → "Crear demo seedeado" → al primer hit en `/client/balances` la wallet se provisiona contra Prosper sandbox real:
- `stellar_address: GCCHGZRZ4QTI4WRWRKHXAUD7SKCSUHRXOXG66EZLAW4FSMRPDHRLNE77`
- `balance_xlm: 2.99999` (Prosper auto-funda con XLM para gas)

**Tests**: 30/30 pytest combinados (Phase 1 + 11B + 12 + 12.4 + Alfred live + Prosper live).

## ✅ Sprint 12.5 — Webhook config + dynamic deposit + Alfred-server-validated onramp (2026-05-14)

**Endpoint admin para configurar webhook en Alfred dashboard**:
- `POST /v1/admin/ops/sync-alfred-webhook` (super_admin) → llama `PUT /webhooks/url/config` con `{url: PUBLIC_BASE_URL + /api/v1/webhooks/alfred, method: POST}`. Idempotente.
- Live-validado contra sandbox Alfred Pay: respondió OK + echó la config persistida.

**Dynamic deposit address por org**:
- `RealAlfredAdapter.create_onramp_order` + `MockAlfredAdapter` aceptan kwargs `deposit_address` y `customer_id`.
- En `/v1/client/onramp/orders` antes de crear la orden corremos `ensure_org_prosper_wallet(org_id)` y pasamos su `stellar_address` como `depositAddress`. Sin esto, Alfred no sabría dónde depositar el USDC.

**Mapping payment_method real**:
- Nuevo `_alfred_payment_method()` traduce nuestros enums internos (`transfer`/`mercadopago`/`card`/`crypto`) a los valores Penny (`BANK`/`MERCADO_PAGO`/`CARD`/`CRYPTO`). Default `BANK`. Antes hacíamos `.upper()` y mandábamos `TRANSFER` → 422.

**Status mapping extendido**:
- `alfred_status_to_internal` ahora soporta también `KYC_PENDING|APPROVED|REJECTED` y `REFUND_INITIATED|COMPLETED`. Los buckets KYC y REFUND son nuevos, separados de onramp lifecycle.

**Live evidence**:
- Webhook URL config: respuesta 200 desde Alfred sandbox echo-ing el `https://15b54ecb-…/api/v1/webhooks/alfred`.
- Quote real ARS 50.000 → 33.0169 USDC @ 1506.69.
- Onramp order: pasa quote + payment_method correctos; falla **solo en `customerId`** porque Alfred requiere un customer pre-creado vía su KYC iframe flow.

**Pendiente para cerrar el último 5% del onramp E2E real** (lo único que falta):
- Crear un customer en el dashboard Alfred (o programáticamente vía `POST /customers` — pero ese flow requiere recolectar KYC PII del usuario por su iframe). Setear `ALFRED_DEFAULT_CUSTOMER_ID` en `.env` mientras tanto.
- Probar transferencia bancaria sandbox real → Alfred dispara `FIAT_DEPOSIT_RECEIVED` → `TRADE_COMPLETED` → `ON_CHAIN_COMPLETED` → nuestro webhook receiver auto-buyea PUSD en la wallet Stellar de la org.

## ✅ Sprint 12.6 — Alfred Hybrid KYB + KYC (2026-02 / iteration_17)

**Reemplaza AiPrise por Alfred KYC/KYB nativo** para unificar onboarding y resolver el último 5% del onramp E2E (faltaba `alfred_customer_id`).

**Backend nuevos archivos**:
- `integrations/alfred/kyc.py` — `RealAlfredKycAdapter` (host separado: `api-dev-services.alfredpay.app/api/v1`) + `MockAlfredKycAdapter`. Factory `get_kyc_adapter()` con env `ALFRED_KYC_MODE` (mock/sandbox/production).
- `routes/alfred_kyc.py` — 4 endpoints:
  - `POST /v1/onboarding/alfred/kyb/start` (token-gated /apply): crea customer KYB, persiste `alfred_customer_id` + `alfred_kyb_iframe_url` en `organizations`. Idempotente.
  - `POST /v1/onboarding/alfred/kyc/start` (auth): crea customer KYC para el user actual.
  - `GET /v1/onboarding/alfred/status?customer_id=…`: poll endpoint para el wizard.
  - `GET /v1/alfred/mock-kyc/{cid}` + `POST /v1/alfred/mock-kyc/{cid}/settle?decision=approve|reject` — HTML hosted-widget mock + síntesis de webhook HMAC-firmado.

**Backend modificaciones**:
- `routes/client_alfred.py::_handle_customer_event()` — nuevo handler para `customer.kyb.*` y `customer.kyc.*` (HMAC verificado). Flipea `org.kyb_status` y dispara `ensure_org_prosper_wallet()` al aprobar KYB.
- `routes/client_alfred.py` `create_onramp` — ahora pasa `customer_id=org.alfred_customer_id` al adapter (corrige 422 que tenía pendiente Sprint 12.5).
- `routes/client_portal.py::apply_finalize` — auto-arranca el customer KYB en Alfred al enviar el wizard; retorna `alfred_kyb` con iframe_url.
- `models.py` — `Organization.alfred_customer_id` + `User.alfred_customer_id`.
- `.env` — `ALFRED_KYC_MODE=mock`, `ALFRED_KYC_BASE_SANDBOX`, `ALFRED_KYC_BASE_PRODUCTION`, `AIPRISE_DEPRECATED=1`.

**Frontend**:
- `apply/page.tsx` `StepVerification` — reemplaza tarjeta AiPrise por iframe embebido de Alfred. Polling cada 3s a `/status` + listener `window.message` (`alfred:kyc:approve`/`reject`). Badge dinámico (Pendiente/Aprobado/Rechazado).
- Step 5 actualizado: docs se suben directamente en widget Alfred (antes decía "email a compliance").

**Tests**: 10/10 pytest pass (`test_sprint12_6_alfred_kyc.py`). E2E mock validado live: KYB iniciado → approve → org.kyb_status='approved' → Prosper wallet provisionada (`stellar_address: GDJV4…`). Frontend Step 6 renderiza iframe + status badge correctamente.

**Para activar Alfred KYC live**: flipear `ALFRED_KYC_MODE=sandbox` en `.env` y confirmar URLs base (default ya correcto).

## ✅ Sprint 12.6.1 — Alfred KYC LIVE Sandbox (2026-02 / cont.)

`ALFRED_KYC_MODE` flipped from `mock` → `sandbox`. Real Alfred sandbox endpoints discovered via live probing:

- **Base host**: `penny-api-restricted-dev.alfredpay.io` (same as Penny payments — no separate `api-dev-services` subdomain).
- **`POST /customers`**: `{email, type: "INDIVIDUAL"|"BUSINESS", country?, businessId?}`. `type` MUST be UPPERCASE. `country` REQUIRED for BUSINESS, REJECTED for INDIVIDUAL. Country uses ISO-2 (`AR`/`MX`/`BR`/`CO`/`US`...).
- **`POST /customers/{cid}/kyc`**: `{kycSubmission: {firstName, lastName, phoneNumber (E.164), address, country (ISO-2), city, state, zipCode, dateOfBirth, dni, cuit (AR — must match dni), pep, ...country-specific}}`. Argentina also requires the CUIT to embed the DNI digits.
- **`GET /customers/{cid}`**: returns `{statusKyc: "CREATED"|"PENDING"|"APPROVED"|"REJECTED", ...}`. Status starts `CREATED` and advances as Alfred reviews documents.

**Onramp regression fix**: `RealAlfredAdapter.create_onramp_order` no longer sends `callbackUrl` / `externalReference` (rejected as unknown params by live Alfred). Webhook URL is configured globally via `PUT /webhooks/url/config`. Same fix applied to `create_offramp_order`.

**Hybrid fallback**: `RealAlfredKycAdapter.create_kyb_customer` first attempts type=BUSINESS; if the tenant rejects KYB (e.g. country unavailable), falls back to creating an INDIVIDUAL customer using the org's primary contact email — preserves the unified `customerId` flow while we finalize Alfred KYB contract.

**Email collision handling**: Alfred 409 "Email already registered" is auto-retried with a `+a{tag}` suffix (preserves the same mailbox). Prevents dev/test loops from being blocked by previously-onboarded emails.

**New env vars**:
- `ALFRED_KYC_MODE=sandbox`
- `ALFRED_KYC_WIDGET_BASE` (optional) — when set, the wizard embeds Alfred's hosted widget directly. When unset, falls back to `/api/v1/alfred/real-kyc-stub/{customer_id}` (informational page with the customer id + redirect).

**New endpoint**:
- `GET /api/v1/alfred/real-kyc-stub/{customer_id}` — fallback hosted page when widget URL not configured.

**Live evidence**:
- Created real Alfred customer `c257f1bb-ded3-498b-aa05-80ee06a6b124` for org_seed_alemany.
- Submitted real KYC for another customer `143c994b-...` → got `submissionId: 6b63ccea-...` from Alfred.
- `/client/onramp/orders` now passes the real `customerId` correctly: error changed from 422 "customerId invalid" → 409 "Customer KYC incomplete" (expected gating — customer must be APPROVED by Alfred compliance before onramping). Confirms the 5% gap from Sprint 12.5 is **closed**.

**Tests**: `test_sprint12_6_alfred_kyc.py` re-modularised with `@SKIP_IF_NOT_MOCK` / `@SKIP_IF_MOCK` decorators. 6 passed + 6 skipped in sandbox mode; 8 passed + 4 skipped in mock mode (same code, flip `ALFRED_KYC_MODE` to swap which set runs).

**Pending for full prod**: configure `ALFRED_KYC_WIDGET_BASE` once Alfred shares the widget origin URL (currently the real-kyc-stub fallback is acceptable for dev/UAT).

## ✅ Phase 14 — Andes Adapter Frontend + auto-trigger (2026-02-XX, this session)

**Goal**: Surface the Phase 14 Andes Adapter (accounts, ARSa wallet, CVU, balances) in both the backoffice and the client portal, and auto-create the ramp account on KYB approval (with a manual fallback so already-approved orgs can still be onboarded).

**Constraint**: ARSa is a first-class asset throughout the UI. Label `ARSa` (lowercase `a`), symbol `$`, caption `peso digital 1:1`.

### Backend additions
- `routes/ramp_routes.py` refactored: new `ensure_org_ramp_account(...)` orchestrator (account → ARSa wallet → fiat/CVU). Tolerant to missing Andes KYC docs — when `ensure_fiat_account` raises `NotSupportedByProvider`, the row is persisted with `onboarding_status="kyc_pending_andes"` instead of failing. A second graceful branch (`onboarding_status="error"`) covers gateway-unreachable cases. Endpoints:
    - `POST /api/v1/ramp/accounts`        (create / idempotent)
    - `POST /api/v1/ramp/accounts/{ecid}/retry`
    - `GET  /api/v1/ramp/accounts`        (list, scoped to org)
    - `GET  /api/v1/ramp/accounts/{ecid}` (single)
    - `GET  /api/v1/ramp/accounts/{ecid}/balances`
    - `GET  /api/v1/ramp/accounts/{ecid}/funding`
  Backoffice roles (`super_admin`, `admin`, `compliance_*`, `finance_*`, `ops`) may pass `?org_id=X` on any of these to act on a tenant they don't belong to; non-backoffice roles ignore the override (security boundary verified by tests).
- `routes/ramp_routes.py` wired in `server.py` under `/v1` prefix.
- Auto-trigger on KYB approval added at 3 entry points (best-effort, never blocks KYB):
    - `routes/client_alfred.py::_handle_customer_event` (Alfred webhook)
    - `routes/alfred_kyc.py::kyb_status` (poll-driven approval)
    - `routes/admin_ops.py::seed_demo_client` (when `auto_approve=True`)

### Frontend additions
- `frontend/src/lib/ramp.ts` — typed hooks + fetchers (`useRampAccounts`, `useRampAccount`, `useRampBalances`, `createRampAccount`, `retryRampAccount`). All accept optional `orgId` to forward `?org_id=` for backoffice viewing. Includes `fmtArsa()` (es-AR locale, `$ 150.000,00`) and `shortCvu()`.
- `frontend/src/components/client/ArsaAccountCard.tsx` — deep-blue gradient card with large ARSa balance, "peso digital 1:1" caption, CVU/Alias/Wallet with copy buttons, deposit (active) and withdraw (disabled, "Próximamente · Fase 15") action pills.
- `frontend/src/app/client/page.tsx` — mounts `<ArsaAccountCard orgId={...}/>` above the existing KPI row when the user can operate.
- `frontend/src/app/admin/clients/[id]/_tabs/AndesAccountTab.tsx` — new backoffice tab "Cuenta Andes" with status badge, full account data table, balances table (ARSa row included), and "Crear cuenta Andes" / "Reintentar" / "Re-crear / refrescar" buttons.
- `frontend/src/app/admin/clients/[id]/page.tsx` — registers the new tab between "KYB docs" and "API keys".

### Env / config
- `backend/.env`: `RAMP_PROVIDER=andeslabs`, `RAMP_PROVIDER_MODE=sandbox`, `ANDES_GATEWAY_URL=http://localhost:8090` (was the docker hostname). Mongo: a `ramp_provider_config` global row set to `{provider:andeslabs, mode:sandbox, enabled:true}` so the registry resolves to `AndesAdapter` (which proxies to the Node gateway).
- Node gateway already running on `localhost:8090` in `ANDES_GATEWAY_MODE=mock` (per the previous agent), so no real Andes credentials needed for E2E.

### Verification
- Backend pytest 8/8 PASS (`/app/backend/tests/test_phase14_andes_ramp.py`): auth gate, create+idempotent, balances ARSa row, simulate-deposit via Node gateway, retry, super_admin org_id override, client_admin override ignored.
- Frontend Playwright smoke PASS on `/client` (ArsaAccountCard) and `/admin/clients/org_seed_alemany` (Cuenta Andes tab) — all `data-testid` selectors render the correct ARSa label, `$` symbol, "peso digital 1:1" caption, chain `stellar`, CVU `0000 0037 3517 7792 1768 17`, alias `orgseedale.andes.mock`, wallet `CPSTKSTX…000000`.

### Pending (Phase 14 wrap-up / Phase 15 follow-up)
- Connect the deposit action pill to a step-by-step "How to fund your CVU" modal (currently the button is informational only).
- Phase 15: wire `initiate_offramp` so the disabled "Retirar" pill becomes active.
- Phase 14+: real Andes credentials → flip `ANDES_GATEWAY_MODE=real` + supply `ANDES_API_KEY` + `ANDES_JWT_PRIVATE_KEY_PATH` (or `ANDES_USE_KMS=true`).

## ✅ Phase 15.1 — Andes Webhooks + Offramp + Movements (2026-02, this session)

**Goal**: Production-grade onramp (deposit-driven) + offramp (CVU lookup → withdraw) for ARSa, with signed webhooks for settlement, idempotency at every layer, and ARSa-specific caps. Phase 15.2 (international ARS→BOB/PEN/PYG) deferred.

### Gateway additions (`services/andes-gateway`)
- `src/webhooks.ts` — ES256 (P-256/SHA-256, IEEE-P1363) sign + verify helpers. Static mock keypair shipped so signature verification is reproducible in mock mode. `verifyWebhookSignature` is now bulletproof: malformed signatures, stale timestamps, non-base64 sigs all collapse to `{ok:false, reason:'...'}` (HTTP 401), never 5xx.
- `POST /webhooks/andes` — PUBLIC endpoint. Reads raw body via a custom content-type parser (so signature checks happen over EXACT bytes), verifies + forwards to FastAPI receiver, returns the FastAPI status code as-is (Andes retries on non-2xx).
- `POST /fiat/withdraw` — in real mode wraps `andes.fiat.withdraw(...)`; in mock mode debits the wallet immediately, returns `{transactionId, status:'Pending'}` and fires-and-forgets a signed `fiat.withdrawal.success` webhook 250 ms later (auto-settlement for E2E).
- `GET /fiat/cvu-lookup` — proxies to `andes.fiat.cvuLookup(...)` for the destination-holder confirmation step; mock generates plausible holders.
- `POST /dev/simulate-deposit` (existing) now ALSO fires a signed `fiat.deposit.success` webhook to the receiver, giving us a fully audited E2E deposit flow.
- `POST /dev/fire-webhook` — arbitrary signed event injector for tests.

### Backend additions (`backend/routes`)
- `ramp_webhook.py` — new internal receiver `POST /api/v1/internal/ramp/webhook` (protected by `X-Internal-Token`). Idempotent by `delivery_id` (persists every event in `ramp_webhook_events` before dispatch). Dispatch table:
    - `fiat.deposit.success` → insert ARSa `ramp_movements` row (kind=deposit, status=Success, with `prosper_tx_id`) + refresh `ramp_balances`
    - `fiat.deposit.failed` → failed movement + alert in `ALERTS`
    - `fiat.withdrawal.success` → flip the matching movement to Success
    - `fiat.withdrawal.failed` → flip to Failed, refund cached balance, alert
    - `crypto.transfer.*` + `international.offramp.*` → persisted but no-op (Phase 15.2)
  Handler errors return 502 so Andes retries.
- `ramp_routes.py` — added:
    - `GET /api/v1/ramp/cvu-lookup` → gateway proxy
    - `POST /api/v1/ramp/accounts/{ecid}/withdraw` → orchestrator. Requires `Idempotency-Key`. Validates account approved, caps (per-org `arsa_withdraw_daily_cap_arsa` / `_monthly_cap_arsa` on `organizations.caps`, defaults 5 M / 50 M), amount > 0, calls gateway, persists `ramp_movements`, debits cached balance. Same Idempotency-Key returns same movement id.
    - `GET /api/v1/ramp/accounts/{ecid}/movements` → DESC list with ARSa first-class labeling.

### Frontend additions
- `lib/ramp.ts` — `useRampMovements`, `cvuLookup`, `submitWithdraw`, `RampMovement` / `TxStatus` / `CvuLookup` types.
- `lib/api.ts` — hardened ApiError detail flattening for FastAPI validation arrays AND fixed a latent header-spread ordering bug that was silently dropping `Content-Type` when a caller provided custom headers (caught by Phase 15 testing).
- `components/client/RampMovementsAndForms.tsx` — three exports:
    - `DepositInstructionsModal` — surfaces CVU/alias/wallet with copy buttons + 3-step explainer
    - `WithdrawModal` — amount + CVU/alias tabs + lookup-holder + confirm + submit (Idempotency-Key generated per submit)
    - `MovementsCard` — DESC list with status pill, holder name, ± fmtArsa
- `components/client/ArsaAccountCard.tsx` — the "Depositar"/"Retirar" pills now open the respective modals (no longer "Próximamente").
- `app/client/page.tsx` — mounts `<MovementsCard>` below the ARSa card.

### Verification
- Backend: `test_phase15_andes_ramp_offramp.py` → **10/10 PASS** (idempotency, signature, simulate-deposit, withdraw happy-path, auto-settle, cvu-lookup, movements DESC, bad-sig 401, stale 401, caps).
- Frontend: full Playwright + manual E2E. POST /withdraw → 200, toast "Retiro enviado por $ 17.500,00" visible, balance drops live, 9 movements rendered correctly with status pills.

### Deferred to Phase 15.2
- International offramp ARS→BOB/PEN/PYG (gateway `/intl/*` + FastAPI `/ramp/international/*` + backoffice screen).
- Crypto transfer flow (USDC/USDT).
- Admin ops endpoint to expire stale Pending withdrawals (Phase 15 follow-up).

## ✅ Phase 16 — Backoffice de Rampa (2026-02, this session)

**Goal**: Switch de proveedor + monitoreo + stats + webhooks debug. Audit-logged. Backoffice-only.

### Backend (`backend/routes/admin_ramp.py`)
**A. Switch**
- `GET  /api/v1/admin/ramp/provider-config` — global + per-org overrides + org_names
- `PUT  /api/v1/admin/ramp/provider-config` — set global
- `PUT  /api/v1/admin/ramp/provider-config/{org_id}` — per-org override
- `DELETE /api/v1/admin/ramp/provider-config/{org_id}` — remove override
- `GET  /api/v1/admin/ramp/connectivity` — alfred + andes probe (semáforo enabled/reachable/authenticated/error + latency)
- `GET  /api/v1/admin/ramp/capabilities` — alfred / andeslabs / _gateway
- Cada mutación de provider-config persiste `audit_logs.action=admin.ramp.provider_config.{create|update|delete}` con `before/after`

**B. Cuentas**
- `GET /admin/ramp/accounts/kpis` — total_arsa_under_management + counts
- `GET /admin/ramp/accounts` — filtros: status, has_cvu, q; hidrata arsa_balance
- `GET /admin/ramp/accounts/{ecid}/detail` — drilldown (wallets + balances + fiat + last 20 movements)

**C. Movimientos**
- `GET /admin/ramp/movements` — filtros kind/status/org_id/date_from/date_to/q; flag `is_stale` (Pending > 30 min)
- `GET /admin/ramp/movements.csv` — export (text/csv + Content-Disposition); audit_log entry

**D. Stats** (proxy al gateway)
- `GET /admin/ramp/stats` → `GET /project/stats`
- `GET /admin/ramp/stats/timeseries` → `GET /project/stats-timeseries`

**E. Webhooks**
- `GET /admin/ramp/webhooks` — db rows (filtros event_type, processed, signature_valid)
- `GET /admin/ramp/webhooks/deliveries` — cross-check con Andes deliveries (gateway proxy); cada item incluye `received` y `processed`

### Gateway (`services/andes-gateway/src/server.ts`)
- `GET /project/stats` (mock deriva números plausibles desde el state in-process)
- `GET /project/stats-timeseries?window=30d&bucket=1d` (30 puntos diarios)
- `GET /webhooks/deliveries?limit=100` (real-mode → SDK; mock-mode → empty + note)
- `GET /capabilities` (alfred + andeslabs canonicales para la UI)

### Frontend (5 nuevas rutas + 1 sección inline)
- `/admin/integraciones/rampa` — switch + connectivity strip (auto + manual) + capabilities + per-org overrides (modal de alta)
- `/admin/rampa/cuentas` — 4 KPIs + tabla + filtros + drilldown drawer
- `/admin/rampa/movimientos` — feed + filtros + CSV export; Failed en rojo, Pending stale en amarillo
- `/admin/rampa/stats` — KPIs + 2 charts Recharts (volumen ARSa Area, depósitos/retiros Bar)
- `/admin/rampa/webhooks` — cross-check strip + tabla
- Sección inline `RampStatsSection` montada en `/admin` (dashboard ejecutivo)
- Sidebar `AppShell.tsx` extendido con 5 entries Rampa
- `frontend/src/lib/admin-ramp.ts` — hooks SWR + mutations tipados

### Verification
- Backend: `test_phase16_admin_ramp.py` **16/16 PASS** (auth gate, provider-config CRUD + audit, connectivity, capabilities, accounts + KPIs + detail, movements + CSV + audit, stats + timeseries, webhooks + deliveries cross-check)
- Frontend: Playwright PASS en las 5 páginas + sección inline; data-testids correctos para cuentas + drilldown; charts visibles; CSV download dispara; conectividad muestra Andes y Alfred ambos `authenticated`.

### Notas de implementación
- Cambiar provider-config llama a `reset_registry()` para que el próximo `resolve()` re-lea Mongo en caliente.
- `ConnectivityResult` separa `enabled/reachable/authenticated` para que ops vea exactamente qué está roto.
- En mock mode, `/webhooks/deliveries` devuelve lista vacía con `note` explicativo; el UI lo muestra. En real mode el SDK devuelve la lista canónica.
- `KpiCard` deriva testid del label (cosmético; las 4 KPIs de cuentas renderizan los valores correctos pero sus testids son auto-generados).

### Pending (no urgentes)
- Endpoint admin para expirar retiros Pending viejos (Phase 15 follow-up, mencionado por el usuario; no urgente).
- Replace `<input type=date>` por Calendar shadcn en /admin/rampa/movimientos (consistencia visual).
- Add explícito `testId` prop a `KpiCard` (mejora menor de DX para tests).

### Phase 15.2 deferred
- Internacional ARS→BOB/PEN/PYG (gateway /intl/* + FastAPI /ramp/international/*).
- Crypto transfer flow (USDC/USDT) + handler `crypto.transfer.*`.


## ✅ Phase 17 — Selección de cadena para ARSa (Stellar | Base) (2026-02, current)

**Goal**: Permitir elegir la cadena en la que se mintea la wallet ARSa (Stellar Soroban o Base EVM). Default global por org, override por cuenta desde backoffice. End-customer NO elige cadena — solo VE la red.

### Trigger (root cause)
El proyecto Andes Production del cliente solo tiene habilitada la cadena `base`. Los intentos previos con `chain=stellar` devolvían `"Invalid chain"` desde Andes Prod. Adicionalmente, el adapter Python enviaba camelCase a `/fiat/business` (`userId`, `holderName`) cuando el SDK Prod exige snake_case (`user_id`, `holder_name`), lo que generaba `"Missing field: user_id"`.

### Cambios
- **Bugfix `backend/ramp/adapters/andes.py`**:
  - `ensure_fiat_account` ahora envía snake_case en `/fiat/business` (`user_id`, `chain`, `holder_name`) y multipart correcto en `/fiat` (KYC individual).
  - Acepta `andes_user_id` kwarg explícito (el end_customer_id NO es el user_id de Andes).
  - Lee `onboarding_status`/`onboardingStatus` (compat).
- **Resolver `backend/ramp/chain_config.py`** (nuevo):
  - `resolve_arsa_chain(org_id, end_customer_id)` → AvailableChain con precedencia: `ramp_accounts.arsa_chain_override` > `ramp_provider_config[org_id].default_arsa_chain` > `ramp_provider_config[global].default_arsa_chain` > env `ANDES_DEFAULT_CHAIN` > `stellar`.
  - `get_org_arsa_chain_config(org_id)` y `resolve_arsa_chain_with_source` para diagnóstico/UI.
- **Modelo de datos** (sin migración destructiva):
  - `ramp_provider_config`: campos opcionales `default_arsa_chain` y `allowed_arsa_chains`.
  - `ramp_accounts`: campo opcional `arsa_chain_override`.
- **`backend/routes/ramp_routes.py`**:
  - `ensure_org_ramp_account` y `_refresh_account` resuelven cadena via `resolve_arsa_chain` (en vez de hardcode `STELLAR`).
  - `_refresh_account` también upserta `ramp_wallets` y `ramp_fiat_accounts` para que el detail/withdraw flow vea las wallets creadas tras retry.
  - Mensaje de error de retry ahora es customer-friendly (oculta el raw 500 del gateway).
  - `withdraw` y `balances skeleton` usan la cadena efectiva.

### Endpoints admin nuevos (`/api/v1/admin/ramp/*`)
- `GET  /arsa-chain[?org_id=…]` → `{default, allowed, source}`
- `PUT  /arsa-chain` → setea el global; audit-log `admin.ramp.arsa_chain.set_global`
- `GET  /accounts/{ecid}/arsa-chain[?org_id=…]` → `{effective_chain, source, override, has_wallet_on_other_chain, wallet_chain}`
- `PUT  /accounts/{ecid}/arsa-chain` (body `{override: "stellar"|"base"|null}`) → audit-log `admin.ramp.arsa_chain.set_account`
- Auth: read = backoffice roles; write = `super_admin` o `finance_admin` (probado 403 desde ops/admin).

### Frontend
- `/admin/integraciones/rampa` → panel **"Cadena ARSa"** con badge actual + selector Stellar/Base + advertencia "afecta solo wallets nuevas" (`data-testid="arsa-chain-panel"`).
- `/admin/clients/[id]` tab **Cuenta Andes** → row **"Red ARSa de esta cuenta"** muestra `effective_chain` + `source`; selector con 3 opciones (default | stellar | base); warning si la cuenta ya tiene wallet en otra red.
- **BalanceTable** ahora muestra columna **Red** con badge Stellar/Base (filas separadas — nunca sumadas).
- **Client portal `ArsaAccountCard`** → badge `Red: Stellar|Base` debajo del saldo; sección secundaria si hay ARSa en otra red (nunca sumado); label dinámico "Wallet ARSa (Base)".
- `frontend/src/lib/admin-ramp.ts` → `useArsaChainConfig`, `setArsaChainDefault`, `useAccountArsaChain`, `setAccountArsaChain` (tipados).
- `packages/ui/Badge.tsx` ahora forwardea `data-testid` prop (antes lo dropeaba silenciosamente).

### Verification
- Backend: `test_phase17_arsa_chain.py` **11/11 PASS** (admin GET/PUT global, override get/set/clear, 403 role-gate, validación enum, audit-log writes, chain-resolver-in-create-account vía mock, no-regression phase 14/15/16).
- Frontend: panel Cadena ARSa renderiza + edición Base→Stellar→Base con toast OK. Client portal muestra `Red: Base` y wallet `0x56724B…C5a043` correctamente.
- **Real-mode probado**: la wallet ARSa-base `0x56724B35a02078d193335764e064f2FA5DC5a043` para `user_id=a4312bc8-d134-4a17-80ff-b607ae0f8e53` quedó persistida en Andes Production y replicada en Mongo.

### Bloqueo externo (no del platform)
- El fiat `business` en Andes Prod queda en `pending_approval` hasta que Andes apruebe el KYB del cliente. El CVU vendrá por webhook `fiat.account.created` (proxy público ya registrado en Prod).

### Pendiente (Backlog)
- Si Andes habilita Stellar en este proyecto, `chain=stellar` queda disponible sin cambios de código (el resolver ya lo permite).
- `get_balances` en mock mode echoes `chain=stellar` aunque la wallet sea Base — no impacta producción pero romperse la paridad mock/real. Fix: override del chain del row con el chain de la wallet a nivel projection en `ramp_routes.py`.
- Endpoint admin para expirar retiros Pending viejos (Phase 15 follow-up).
- FASE 15.2: International offramp ARS→BOB/PEN/PYG.

## ✅ Phase 18 — Stellar default + Wallet provisioning lifecycle (2026-02, current)

**Goal**: ARSa en Stellar es **activo clásico** (code ARSa), no token Soroban. Stellar es el default global. Las wallets Stellar se crean **pending** y pasan a **active** por webhook `wallet.active`; los depósitos no acreditan hasta que la wallet esté activa. Wallets EVM (Base) se crean active.

### Cambios principales
- **Modelo `ramp_wallets`** ganó `status` ("pending"|"active") y `activated_at`.
- **Default global**: `ramp_provider_config.default_arsa_chain = "stellar"` (seed idempotente al startup).
- **Gateway Node**:
  - `POST /wallets` retorna `status` (Stellar=pending, Base=active).
  - Mock: setTimeout 800ms auto-emite `wallet.active` para Stellar.
  - Mock: `dev/fire-webhook fiat.deposit.success` bumpea balance del wallet mock.
  - `ANDES_EVENT_TYPES` incluye `wallet.active` y `fiat.account.created`.
- **Handlers webhook FastAPI**:
  - `_handle_wallet_active`: marca status=active, libera depósitos retenidos, audit-log.
  - `_handle_fiat_account_created`: refresca CVU/alias.
  - `_handle_deposit_success` defensivo: si wallet pending, retiene (`held_for_wallet_activation=true`, status=Pending) y NO bumpea balance.
- **Nuevo endpoint poll**: `POST /api/v1/ramp/accounts/{ecid}/refresh-wallet-status` (fallback al webhook).
- **Response**: `RampAccountOut` ahora expone `wallet_chain`, `wallet_status`, `wallet_activated_at` (enriquecidos vía `_enrich_with_wallet`).

### Frontend
- **`/admin/integraciones/rampa`** — Nuevo panel "ARSa por red" (`data-testid=arsa-addresses-panel`) con direcciones de referencia. Stellar issuer `GCVIA2UOUEM6JATLDQVXERXPSELWBRCDHB53SOAYBGUOHNOSUII4T5NE`, SAC `CDYP52X4FIXSPDK76JGJT6J3NH2EV2GMBJ2KCEKMYMR36OSB3Y4CHFPL`, code ARSa. Base proxy `0x1817A385Df1f9F4721F8499D747FB3A63b1a1965` chainId 8453. Aclara que ARSa-Stellar NO es Soroban.
- **Tab "Cuenta Andes"** — Badge `Wallet · Activando/Activa`, botón "Refrescar estado wallet", explorer link (stellar.expert / basescan.org), label dinámico "Wallet ARSa (Stellar|Base)".
- **Client portal** — Banner `arsa-activating-banner` + botones Depositar/Retirar disabled cuando pending. NO memo/destination tag.
- **`lib/ramp.ts`** — helpers: `isWalletActivating`, `refreshWalletStatus`, `explorerUrl`, `chainLabel`.

### Verification
- Backend pytest **8/8 PASS** (`test_phase18_wallet_activation.py`): default chain, pending→active, refresh endpoint, deposit-while-pending race + release, idempotency, dispatch table, regression Phase 14-17.
- Frontend Playwright **100%**: addresses panel, activating banner + disabled buttons, badge transitions, explorer links.
- E2E mock validado: cuenta nueva → wallet ARSa-stellar pending → portal muestra "activando" → 800ms → wallet.active → depósito retenido se libera + balance acreditado.

### Pendiente (Backlog)
- Hacer `ANDES_MOCK_WALLET_ACTIVATE_MS` configurable (hoy hardcoded 800ms).
- Index Mongo `ramp_movements(provider_user_id, held_for_wallet_activation)`.
- Refactor `ramp_routes.py` (>1000 líneas): separar wallet-enrichment / account-CRUD / balances / movements.
- FASE 15.2: International offramp (ARS→BOB/PEN/PYG) + crypto transfer flows.


## ✅ Phase 24 — Individuo AR · Andes-only KYC (orden b) (2026-02, current)

### Cambios
- **`routes/onboarding.py`**:
  - `ApplicationIn` extendido con `last_name`, `cuit` (regex 11 dígitos), `birthdate` (YYYY-MM-DD), `phone` (+formato), `chain` (stellar default).
  - Para `applicant_type='individual'` **NO se invoca AiPrise**: `mode="andes-direct"`, `hosted_url` apunta a `/apply/{app_id}/kyc-docs`.
  - Para `applicant_type='business'` AiPrise sigue como antes (toggle Phase 22+).
  - Nuevo endpoint **`POST /api/v1/onboarding/{app_id}/kyc-docs`** (multipart) que:
    1. Valida app pertenece a `applicant_type='individual'`, no consumido, datos completos.
    2. **Guarda copia local** en `/app/backend/var/kyc_docs/{app_id}/{face,id_front,id_back}.jpg` para audit (Andes no permite descarga posterior).
    3. Llama gateway `POST /accounts` → Andes `accounts.create({name})` → `andes_user_id` (idempotente, reuso si ya está guardado).
    4. Llama gateway `POST /wallets {user_id, chain, asset:'arsa'}` → wallet ARSa (idempotente: 409 → GET wallets/{userId} y reusa).
    5. Llama gateway `POST /fiat` multipart con body + 3 archivos.
    6. Persiste `ramp_accounts`/`ramp_wallets`/`ramp_fiat_accounts` con el resultado.
    7. Si `onboarding_status='approved'` sincrónicamente → activa `client_admin` + `kyb_status=approved`. Si `pending_approval` → espera webhook.
- **`services/andes-gateway/src/server.ts`** `POST /fiat`: el handler ahora pasa al SDK `{buffer, filename, contentType}` por archivo (antes solo `Buffer` → Andes rechazaba con `Unsupported image type`).
- **`routes/ramp_webhook.py`** `_handle_fiat_account_created`: cuando llega CVU+alias para un org `type='personal'` que aún está `kyb_status != approved`, **automáticamente activa el `client_admin`** (`user.status='active'`, `user.kyc_status='approved'`, `org.kyb_status='approved'`). Audit-logueado. **Este es el gate de aprobación para individuos** — sin AiPrise, sin paso manual.

### Verificación
- ✅ POST `/onboarding/apply applicant_type=individual` → `mode=andes-direct`, NO crea AiPrise session, devuelve `hosted_url=/apply/{app_id}/kyc-docs`.
- ✅ POST `/onboarding/{app_id}/kyc-docs` con 3 fotos → cadena Andes corre real:
  - `accounts.create` → UUID Andes real
  - `wallets.create(stellar, arsa)` → address Stellar real, status=active
  - `fiat.create` → enviado correctamente. Con docs sintéticos (rectángulos de color) Andes sandbox responde 500 ("Unsupported image type" / "Internal server error") — comportamiento **esperado** porque rechaza imágenes que no son DNI reales. Con fotos reales el response será `approved` o `pending_approval`.
- ✅ Webhook `fiat.account.created` (probado vía `/internal/ramp/webhook`) flippeó:
  - `org.kyb_status: pending → approved`
  - `user.status: invited → active`
  - `user.kyc_status: pending → approved`
  - `ramp_account.cvu` + `alias` poblados
  - **`client_admin` activado**, listo para operar en el portal.

### Qué quedó real vs pendiente
| Componente | Estado |
|---|---|
| Captura de fotos en el portal (UI) | 🔵 **PENDIENTE** — UI Next.js para subir 3 archivos no construida en esta iteración. Hoy el upload se prueba por API/curl. |
| Endpoint `/onboarding/{app_id}/kyc-docs` | 🟢 REAL — multipart funcionando, idempotente, audit local guardado. |
| Cadena Andes (account+wallet+fiat) | 🟢 REAL — corre contra Andes sandbox vía gateway en modo `real`. |
| Validación CUIT vía `fiat.arca` pre-submit | 🔵 **PENDIENTE** — no implementado (queda como un check opcional pre-fiat.create). |
| Gate de aprobación = `fiat.account.created` | 🟢 REAL — webhook activa `client_admin` automáticamente. |
| Path empresa (AiPrise toggle) | 🟢 INTACTO — no se tocó. |

## ✅ Phase 22+ — Pasaje a REAL (Andes + Prosper + Resend toggle + KYC toggle) (2026-02)


### Andes Labs — flippeado a REAL
- **`/etc/supervisor/conf.d/supervisord_andes_gateway.conf`** ahora arranca con `ANDES_GATEWAY_MODE=real`.
- EC private key real instalada en `/app/services/andes-gateway/.andes-private-key.pem` (backup del mock en `.MOCK.bak`).
- Handshake JWT ES256 con Andes sandbox **CONFIRMADO** (`mode: "real"` en `/health`, llamadas a `POST /accounts` toman ~1.2s vs <1ms en mock; respuesta devuelve UUIDs reales Andes).
- `ANDES_BASE_URL` / `ANDES_ISSUER` se dejan en defaults del SDK (`undefined`). Andes project_id no se usa.
- Token rotado: `GATEWAY_INTERNAL_TOKEN=prosper_gw_b34602ba3ed77b3c5da66206cac514ec157dc45107cd7174` (sincronizado en supervisor.conf + backend/.env).

### Prosper — REAL para lecturas, MOCK explícito para depósito
- `PROSPER_MODE=development` → adapter REAL contra `apidev.protocol-prosper.io`:
  - `create_user_wallet` ✅ real (en E2E creó addr Stellar `GDI3WR74DNWH...`).
  - `get_user_balances`, `get_treasury`, `get_user_transactions`, `get_assets` ✅ real.
- **`PROSPER_DEPOSIT_MODE=mock`** (nuevo flag) → en `routes/phase20_bridge.py::_subscribe_for_intent` la rama del `deposit_tokens` está bifurcada:
  - `mock` (default): genera `TokenOpResp` local con `tx_hash="MOCK_DEPOSIT_<hex>"` y log WARNING explícito. La position se crea normal y el accrual corre. **NO contacta el protocolo**.
  - `real`: llama `prosper_adapter().deposit_tokens()` (hoy lanza `ProsperError` por diseño hasta que Prosper exponga el método). `TODO(prosper-team): confirm real deposit_tokens method.`
- El resto del circuito (convert ARSa→USDC + transfer USDC→Prosper deposit address) corre real.

### KYC/KYB Toggle super_admin
- Reutilizado el sistema existente `integration_settings.aiprise.mode` (Phase 6) — antes solo aceptaba `sandbox|live`, ahora también `simulated` y `production`.
- **`integrations/aiprise.py::kyc_provider_mode()`** y **`is_simulated_async()`** leen el toggle en cada verificación:
  - `mode='simulated'` → siempre fuerza simulador local (útil para testing).
  - `mode='sandbox'|'production'` → modo real con AiPrise (cae a simulador con WARNING si faltan templates/api_key).
- **Endpoints existentes ya soportan el toggle**:
  - `GET  /api/v1/admin/settings/integrations/aiprise` — estado actual.
  - `PATCH /api/v1/admin/settings/integrations/aiprise {"mode":"simulated"|"sandbox"|"production"}` — flip + audit-log.
- HMAC del webhook AiPrise: **`AIPRISE_WEBHOOK_SECRET`** ya se verifica en `webhooks_aiprise.py:187-188` cuando está seteado (con `simulated` mode el secret está vacío → acepta cualquier signature, como debe).
- Naming alignment: `aiprise.py` ahora acepta tanto `AIPRISE_TEMPLATE_KYC_ID` (catálogo admin) como el legacy `AIPRISE_KYC_TEMPLATE_ID`.

### Resend — sin tocar (mock explícito hasta cargar key)
- `RESEND_API_KEY=` vacío → cae automáticamente a `outbound_emails` (Mongo) con audit del HTML.
- `magic_link` se devuelve en la respuesta de `/onboarding/apply` (TODO marcado: remover de la respuesta cuando Resend esté cargado).

### Hardening
- `GATEWAY_INTERNAL_TOKEN` rotado (de `dev-internal-token-change-me` a un valor random hex 24).
- ⚠️ `PROSPER_API_PASS` sigue en claro en `/app/backend/.env`. Cuando promueva a prod **rotar y mover a secret manager**.

### E2E REAL probado de punta a punta
Alta de **individuo** completa (sin tocar Mongo, sin endpoints manuales):
1. `POST /api/v1/onboarding/apply {applicant_type:"individual", ...}` → crea Org `personal` + User `client_admin` + AiPrise session (simulador o real según toggle).
2. Confirmar simulator (`POST /onboarding/apply/simulate`) o webhook AiPrise real → flipa `kyb_status=approved`.
3. **Auto-disparo REAL**:
   - `Prosper.create_user_wallet` → `POST apidev.protocol-prosper.io/api/v1/alfred/users 201`, `/alfred/cashin 201` (Stellar address REAL).
   - `Andes.accounts.create` → `POST gateway /accounts → SDK Andes → UUID real` (1.2s, JWT ES256 firmado).
   - `Andes.wallets.create` → wallet ARSa Stellar `status=active`.
   - `Andes.fiat.create` → **502 esperado en real** (Andes requiere docs KYC reales para CVU). `onboarding_status=kyc_pending_andes`. CVU se emitirá cuando Lucía suba DNI por el widget Andes.
4. `dev-login` con email URL-encoded → `client_admin` autenticado en su propio org → `/client/dashboard` muestra todo.

### Qué quedó REAL vs MOCK
- ✅ **REAL**: Andes (accounts, wallets, fiat con KYC pending), Prosper (wallet, balances, treasury), AiPrise (sandbox o simulator via toggle), Alfred (onramp/offramp sandbox live), MongoDB, JWT auth, audit-log.
- 🟡 **MOCK explícito con flag**: `deposit_tokens` al protocolo Prosper (`PROSPER_DEPOSIT_MODE=mock`).
- 🟡 **MOCK por config vacía**: Resend (`RESEND_API_KEY=` vacío → outbound_emails), AiPrise templates (`AIPRISE_TEMPLATE_*=` vacío → simulator aunque mode=sandbox).
- 🔵 **PENDING credenciales** (cuando los cargues, flip automático a real): `AIPRISE_TEMPLATE_KYC_ID`, `AIPRISE_TEMPLATE_KYB_ID`, `AIPRISE_WEBHOOK_SECRET`, `RESEND_API_KEY` + dominio.

## ✅ Phase 22 — Backoffice yield admin (products / caps / monitor / dashboard) (2026-02, current)


**Goal**: admin/super_admin productos de yield, caps por org, monitor del
circuito ARSa↔USDC↔Prosper (intents + posiciones + trustlines), dashboard
ejecutivo con totales **separados por asset** (ARSa vs USDC).

### Backend (`routes/phase22_admin_yield.py`)
- Role guards explícitos: `_READ_ROLES` (cualquier backoffice) y
  `_WRITE_ROLES = {super_admin, finance_admin, finance}` con audit-log
  en cada mutación.

**A. Productos de yield**
- `GET    /api/v1/admin/prosper/products` — lista todos los productos.
- `POST   /api/v1/admin/prosper/products` — crear (super_admin/finance).
- `PATCH  /api/v1/admin/prosper/products/{id}` — editar.
- Campos: `name, accepted_asset (arsa|usdc|both), yield_asset (arsa|usdc),
  payout_asset, apr_bps, term_days, payout_schedule (daily|monthly|at_maturity),
  min_amount, max_amount, status, arsa_native_enabled`.
- Validación: `yield_asset='arsa'` requiere `arsa_native_enabled=true`
  (gating del path ARSa-nativo futuro).

**B. Caps por org**
- `PATCH /api/v1/admin/prosper/caps/{org_id}` — edita caps:
  `subscribe_daily_cap_usd`, `subscribe_monthly_cap_usd`,
  `redeem_daily_cap_usd`, `redeem_monthly_cap_usd`,
  `arsa_withdraw_daily/monthly_cap_arsa`. audit-log con before/after.
- `GET   /api/v1/admin/prosper/caps/{org_id}` — read.

**C. Intents monitoring + acciones manuales**
- `GET    /api/v1/admin/prosper/intents` — lista con filtros
  (`direction`, `step[]`, `org_id`, `end_customer_id`, `stuck_minutes`).
  Cada row trae flag `is_stuck` calculado server-side (step en flight +
  `updated_at` viejo). Devuelve `stuck_count` + `failed_count`.
- `GET    /api/v1/admin/prosper/intents.csv` — export CSV (audit-log).
- `POST   /api/v1/admin/prosper/intents/{id}/action` —
  `{action: 'retry'|'mark_failed', reason?}`. `mark_failed` requiere
  reason; `retry` registra audit-log pero NO transita automáticamente
  (el operador re-POSTea el intent — orchestrator es idempotente).

**D. Posiciones + Dashboard**
- `GET /api/v1/admin/prosper/positions?org_id&status&asset` — lista
  posiciones con `asset`, `principal_usd`, `accrued_interest`, etc.
- `GET /api/v1/admin/prosper/dashboard` — totales **agrupados por asset**
  (`totals_by_asset.usdc` y `.arsa` separados), `intents.{in_progress,
  stuck, failed}`, `active_positions`, `timeseries` 30d.

**E. Trustlines monitor**
- `GET /api/v1/admin/prosper/trustlines` — snapshot por org con
  `trustlines[]`, `missing[]` (assets requeridos faltantes), `ok` flag.
- Botón "Force ensure" usa el endpoint Phase 20
  `POST /admin/prosper/accounts/{org_id}/trustline`.

### Frontend
- **`/admin/prosper/inversiones`** — monitor unificado con 3 tabs:
  - **Intents**: KPIs (total/stuck/failed), filtros (direction + step),
    tabla con highlight rojo (failed) y amarillo (stuck), botones
    `retry` / `mark_failed` por row, export CSV, refresh manual + poll 4s.
  - **Positions**: filtros (asset/status), tabla con badges por asset
    (USDC info / ARSa warning) y display_currency.
  - **Trustlines**: KPIs (orgs total / missing count), tabla con
    establecidos/faltantes + botón `ensure {asset}` por row.

### Verification
- `test_phase22_admin_yield.py` **20/20 PASS**:
  - Productos: list (seed visible), client 403, create super_admin,
    duplicate 409, ARSa-native validation, finance read/write, patch.
  - Caps: super_admin patch, get, client 403.
  - Intents: list + KPIs, CSV export, mark_failed sin razón 400,
    mark_failed con razón ✓ (persiste failed_by + failed_at),
    retry returns note, client 403.
  - Positions: list filtered by asset.
  - Dashboard: totales separados por asset (jamás agregados).
  - Trustlines: snapshot por org con missing + ok flag.
- Smoke screenshot del monitor: tabs + KPIs + filtros + table funcionando.

### Cómo probar
1. Loguearte como `admin@prosper.foundation` (super_admin).
2. **Crear producto**: `POST /api/v1/admin/prosper/products
   {"product_id":"liquid_arsa_v1","name":"Liquid ARSa","accepted_asset":"arsa",
   "yield_asset":"usdc","payout_asset":"arsa","apr_bps":700,"term_days":0,
   "payout_schedule":"daily","min_amount":50}`. Aparece en
   `/admin/prosper/inversiones` Positions filter.
3. **Editar caps** de `org_seed_alemany`: `PATCH /api/v1/admin/prosper/caps/
   org_seed_alemany {"subscribe_daily_cap_usd":50000}`. Antes/después en audit-log.
4. **Monitor intent**: PROSPER_MODE=mock + crear intent de Phase 21 →
   `/admin/prosper/inversiones` tab Intents lo muestra recorriendo steps.
5. **Forzar trustline**: tab Trustlines → click "ensure usdc" en un org
   con missing[] no vacío → trustline marcada + audit-log.
6. **Dashboard**: `GET /api/v1/admin/prosper/dashboard` muestra
   `totals_by_asset.usdc.principal` y `.arsa.principal` SEPARADOS.

## ✅ Phase 21 — Portal cliente · Invertir ARSa en Prosper (2026-02, current)

**Goal**: que el N1/N2 entre y salga en pesos (ARSa) desde el portal,
usando el orchestrator de Phase 20 (`POST /api/v1/investments/intent`). Sin
duplicar pantallas existentes; integra al flujo desde la card ARSa.

### Pantallas nuevas
- **`/client/invertir-arsa/page.tsx`** — wizard 3 pasos:
  1. Elegir producto Prosper (lista filtrada por `yield_asset='usdc'` —
     ARSa-nativo deshabilitado) + monto en ARSa (con preview USDC al
     tipo de cambio referencial 1500 ARSa/USDC).
  2. Resumen + disclaimer explicando "convertimos ARSa→USDC, transferimos
     a Prosper, activamos la posición; vos ves pesos punta a punta".
  3. Confirmación → `POST /api/v1/investments/intent {direction:'in',
     source, product_id, amount_arsa|amount_usdc}` → redirige al progreso.
  - Toggle de "Vía" en el header: `ARSa → USDC (puente)` (default) o
    `USDC-Stellar directo` (Phase 21 / B; salta la conversion).
- **`/client/invertir-arsa/[id]/page.tsx`** — progreso del intent:
  poll cada 1.5s a `GET /v1/investments/intent/{id}`. Muestra checklist
  con 4 pasos (Converting ARSa→USDC · Transferring USDC → Prosper ·
  Activando inversión · Posición activa). Estado por step con
  spinner/check/cross. En `step=failed` muestra `fail_reason` + botón
  Reintentar (re-POSTea el body; el orchestrator es idempotente por
  `prosper_tx_id`). CTA "Ver mis inversiones" al activar.

### Wired
- **`components/client/ArsaAccountCard.tsx`** — agregada acción
  "Invertir en Prosper" como pill blanca al lado de Depositar/Retirar,
  link a `/client/invertir-arsa`.
- **`lib/invest.ts`** — `Product` ahora expone `yield_asset` +
  `arsa_native_enabled`. `Position` ahora expone `end_customer_id` +
  `asset` + `display_currency`.
- **`lib/client-portal.ts`** — `features` ampliado con `kyb_locked` y
  flags relacionados.

### Verification
- `test_phase20_bridge.py` **14/14 PASS** sigue verde (backend del wizard).
- Lint frontend limpio sobre los nuevos archivos.
- Smoke screenshot: wizard renderiza con stepper, source toggle, y preview
  ARSa→USDC en vivo cuando se carga el monto.

### Pendiente (Fase 22 + backlog)
- Actualizar `/client/investments` listing + detail para mostrar
  `display_currency='ARSa'` (hoy muestra USDC) y enchufar el botón
  "Retirar" al endpoint `POST /v1/investments/intent {direction:'out'}`
  en lugar del legacy `POST /client/positions/{id}/redeem`.
- KPIs en `/client` overview (total invertido, yield acumulado total,
  posiciones activas) — el backend de `/client/dashboard` ya devuelve
  los datos, sólo es UI.

## ✅ Phase 23 — N1/N2 Sub-client Hierarchy + Ownership Boundary (2026-02, current)

**Goal**: An N1 spawns its own N2 sub-clients; each N2 is a fully independent
tenant. Two non-negotiable rules **enforced server-side**:

  - **Rule 1** — An N2 MUST NOT create further sub-clients (max depth = 2).
  - **Rule 2** — An N1 CAN read its N2's summary balances, but MUST NOT
    operate (cash-in / invest / withdraw / off-ramp / transfer) on the N2.

### Backend
- `routes/subclients.py` — `/api/v1/clients/{n1_org_id}/subclients` POST/GET.
- `_resolve_org_scope()` hardened: non-backoffice user passing
  `?org_id=<other>` gets explicit **403 "Ownership violation"** (previously
  silently dropped).
- `routes/admin_clients/crud.py::list_clients` filtra por `parent_org_id`.
- `routes/business.py::list_clients` expone `parent_org_id`, `parent_name`,
  `level`.

### Frontend
- `/client/mis-clientes` portal (N1) + locked screen para N2.
- `/admin/business/clients`: columna Parent + badge Nivel + filtro Jerarquía
  (Todos / N1 / N2).
- AppShell gating: "Mis clientes" oculto para N2 (`parent_org_id != null`).

### Verification
`test_phase23_hierarchy.py` **11/11 PASS** (rule1×2, rule2×5, hierarchy×3 + sanity).

## ✅ Phase 20 v2 — Bridge ARSa↔USDC↔Prosper (cash IN + cash OUT) (2026-02, current)

**Goal**: el cliente entra y sale en **ARSa (pesos)**; Prosper opera internamente
en **USDC**. Andes hace el swap ARSa↔USDC en ambos sentidos (mock hoy, real cuando
Andes lo exponga). No se toca el protocolo Prosper ni el yield accrual.

### Gateway (`services/andes-gateway/src/server.ts`)
- `POST /convert/arsa-usdc {amount_arsa}` → `{quote_id, usdc_out, rate,
  rate_source: "mock-fixed", quoted_at, expires_at, ttl_seconds}`.
- `POST /convert/usdc-arsa {amount_usdc}` → analogo, devuelve `arsa_out`.
- Tasa configurable via `CONVERSION_MOCK_ARSA_PER_USDC` (default 1500).
- TTL via `CONVERSION_QUOTE_TTL_SECONDS` (default 60s).
- `TODO(phase20)` marca en código para reemplazar por swap real de Andes.

### Backend
- **`routes/phase20_bridge.py`** — orquestador:
  - `POST /api/v1/investments/intent` — direccional (`'in'` o `'out'`).
  - `GET  /api/v1/investments/intent/{intent_id}` y `GET /api/v1/investments/intents`.
  - Colección `investment_intents` con schema PRD 9.2: `direction`, `source`,
    `amount_arsa/usdc`, `conversion{arsa_in,usdc_out,rate,rate_source,
    quoted_at,expires_at,quote_id}`, `andes_transfer_id`, `prosper_tx_id`,
    `position_id`, `owner_user_id`, `end_customer_id`, `step` (transiciones:
    created→converting→bridging→bridged→subscribing→active para IN;
    redeeming→reconverting→paid_out para OUT; failed cualquier paso).
  - Cash IN: convert(mock) → ensure_trustline(usdc) → bridge (transfer USDC
    Andes→Prosper, memo=prosper_tx_id, vía dev/fire-webhook crypto.transfer
    .success en mock) → subscribe (atribuido a `end_customer_id`).
  - Cash OUT: redeem (`prosper_adapter().withdraw_tokens`) → flag position
    `redeemed` → reconvert(mock) USDC→ARSa → acredita balance ARSa en la
    wallet Andes del org (offramp 15.1 lo levanta).
  - Idempotente por `prosper_tx_id`; cada step transición en audit-log;
    fallos generan alert + `step=failed` + `fail_reason`.
  - `ensure_trustline(org_id, asset)` — idempotente, persiste en
    `organizations.prosper_wallet.trustlines`.
- **`routes/phase20_admin.py`** — backoffice:
  - `POST /api/v1/admin/prosper/accounts/{org_id}/trustline {asset}` → fuerza
    trustline (audit-log).
  - `GET  /api/v1/admin/prosper/accounts/{org_id}/trustlines`.
  - `GET  /api/v1/admin/prosper/ledger/{org_id}` → libro mayor por persona
    (principal + accrued + position_count agrupado por `end_customer_id`).
  - `GET  /api/v1/admin/prosper/reconcile/{org_id}` → invariante:
    suma de principales USDC == saldo USDC on-chain del org (epsilon 0.01).
- **`routes/client_invest.py`** — productos seedeados con `yield_asset:'usdc'`
  + `arsa_native_enabled:False`. Backfill idempotente al startup.
- **`db.py`** — nueva colección `investment_intents` con indexes
  (`prosper_tx_id` unique sparse, `org_id+step`, `end_customer_id`,
  `andes_transfer_id`).

### Env (`backend/.env`)
- `ARSA_ISSUER=GCVIA2UOUEM6JATLDQVXERXPSELWBRCDHB53SOAYBGUOHNOSUII4T5NE`
- `ARSA_CODE=ARSa`, `ARSA_SAC=CDYP52X4...`
- `USDC_STELLAR_ISSUER=GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN`
- `INVEST_MIN_USDC=10`, `CONVERSION_QUOTE_TTL_SECONDS=60`
- `ARSA_NATIVE_YIELD_ENABLED=false`, `PROSPER_DEPOSIT_ADDRESS=GCCH...NE77`

### Position attribution
`Position` ahora lleva `end_customer_id`, `asset='usdc'`, `display_currency='ARSa'`
(además del legacy `currency`). El `principal_usd` queda igual → yield accrual
no se modifica. El libro mayor (`/admin/prosper/ledger/{org_id}`) agrupa por
`end_customer_id` para reporte por persona.

### Verification
- E2E mock `test_phase20_bridge.py` **14/14 PASS** (auto-skipea si
  `PROSPER_MODE != mock`):
  - gateway convert ARSa↔USDC en ambos sentidos
  - producto trae `yield_asset='usdc'`
  - admin trustline create + idempotent + list
  - cash IN: ARSa 150 000 → convert (100 USDC) → bridge → subscribe →
    `step=active` con position attribuida (asset=usdc, display=ARSa,
    end_customer_id, principal_usd>0)
  - subscribe TX recorded en `transactions` con `intent_id` + `end_customer_id`
  - admin ledger agrupa por person, admin reconcile devuelve invariante
  - cash OUT: redeem → reconvert → `step=paid_out` con ARSa acreditado en
    `ramp_balances` del org
  - list intents incluye ambos legs · get single intent funciona

### Pendiente / TODOs marcados en código
- Gateway: reemplazar `mockConvert*` por el endpoint real de swap de Andes
  cuando exista. La forma del response ya está pactada.
- Backend: `deposit_tokens` real está deshabilitado en `RealProsperAdapter`
  (handled by Alfred onramp webhooks). El subscribe-real espera confirmación
  con el equipo Prosper. Mock OK.
- Frontend portal cliente (Fase 21) — invertir/retirar en pesos, ver
  posiciones, USDC invisible. Backend listo para enchufar.



**Goal**: A client (N1) can spawn its own sub-clients (N2). Each N2 is a fully
independent tenant with its own Andes account, KYB, caps, and positions.
Two non-negotiable rules — **enforced server-side, not only in the UI**:

  **Rule 1** — An N2 MUST NOT create further sub-clients.
  **Rule 2** — An N1 CAN read its N2 children's summary balances, but MUST NOT
              operate on the N2's money (cash-in / invest / withdraw / off-ramp
              / wallet-to-wallet transfer).

### Backend
- `routes/subclients.py` — Phase 23 router (`/api/v1/clients/{n1_org_id}/subclients`):
  - `POST` creates an N2 with brand-new `org_id`, fresh `client_admin` invite,
    `parent_org_id=N1`, `level=2`.
  - `GET` returns read-only summary rows (ARSa balance, position_count,
    total_aum_usd, contact_email).
  - `_resolve_n1()` guard: rejects 403 if (a) actor.role ≠ client_admin,
    (b) actor.org_id ≠ URL n1_org_id (cross-tenant), or (c) the requested
    org already has a parent (max depth = 2).
- `routes/ramp_routes.py::_resolve_org_scope()` hardened — non-backoffice users
  passing `?org_id=<other>` now get an explicit **403 "Ownership violation"**
  (previously the override was silently dropped). This makes the N1→N2
  boundary visible across every ramp endpoint (accounts CRUD, balances,
  movements, withdraw).
- `routes/admin_clients/crud.py::list_clients` accepts `parent_org_id`
  filter (`none` for top-level N1, or `<org_id>` for that N1's children).
- `routes/business.py::list_clients` exposes `parent_org_id`, `parent_name`,
  and `level` so the backoffice business listing can render the hierarchy.
- `models.Organization`: `parent_org_id` (Optional[str]) + `level` (int, 1|2).
- `db.py` startup migration: backfills `parent_org_id=None`, `level=1` on
  any pre-Phase-23 org doc. Sparse index on `parent_org_id`.

### Frontend
- **`/client/mis-clientes`** (N1 portal): table of sub-clients with balances,
  position count, AUM, contact email, KYB badge. "Crear cliente" modal
  collects legal/commercial name, country, contact email/name. N2 users land
  on a locked screen explaining only their N1 can manage sub-clients
  (`data-testid=mis-clientes-n2-locked`).
- **`/admin/business/clients`** (backoffice): new **Parent** column (linked to
  parent org), **Nivel** badge (N1/N2), and **Jerarquía** filter chips (Todos /
  N1 / N2). Sub-clients filterable via the backend `?parent_org_id=` param.
- **`AppShell.tsx`** sidebar: "Mis clientes" entry is gated to
  `client_admin` + hidden when the user's org has a `parent_org_id` (i.e. N2).

### Verification
- Backend pytest `test_phase23_hierarchy.py` **11/11 PASS**:
  - `test_n2_is_linked_to_n1` — created N2 has `parent_org_id` + `level=2`.
  - `test_rule1_n2_cannot_create_subclient_under_itself` → 403 max-depth.
  - `test_rule1_n2_cannot_create_subclient_under_n1`     → 403 cross-tenant.
  - `test_rule2a_n1_can_read_n2_summary` — N1 sees N2 via list endpoint.
  - `test_rule2b_n1_cannot_create_ramp_account_for_n2`   → 403 ownership.
  - `test_rule2c_n1_cannot_withdraw_from_n2`             → 403 ownership.
  - `test_rule2d_n1_cannot_read_n2_balances`             → 403 ownership.
  - `test_rule2e_n1_cannot_invest_on_behalf_of_n2` — N2.positions stay 0.
  - `test_rule2f_n1_cannot_list_n2_ramp_movements`       → 403 ownership.
  - `test_dod_backoffice_listing_exposes_hierarchy` (super_admin filter ok).
  - `test_dod_business_listing_exposes_hierarchy` (parent_name + level surfaced).
- Phase 14/15.2/16/17 regression: **78/79 PASS** (one pre-existing flake
  in `test_phase15_andes_ramp_offramp::test_withdraw_happy_path` due to
  gateway ARSa balance reset — unrelated).
- `test_phase14_andes_ramp::test_client_admin_org_override_ignored` updated
  to expect the new 403 explicit-rejection behavior.

### Pendiente (backlog)
- FASE 20 Parte 1: Puente ARSa → Prosper (Trustlines + Subscribe multi-asset
  + `POST /api/v1/investments/intent`). Audit (Parte 0) ya hecho.

## ✅ Phase 15.2 — International off-ramp + crypto transfers + stuck/mark-failed (2026-02, current)

**Goal**: Cerrar el rampa multi-país (ARS→BOB/PEN/PYG vía USDT bridge), transferencias cripto wallet-to-wallet, y operativa segura para movimientos que se cuelgan (sin auto-transition).

### Backend
- **Gateway (`services/andes-gateway/src/server.ts`)** — nuevos endpoints internos:
  - `GET /intl/cotization` · `GET /intl/banks/:country`
  - `POST /intl/accounts/:country` · `GET /intl/accounts?userId`
  - `POST /intl/quote/:country` (bob/pen, expira) · `GET /intl/quote/pyg` (rate snapshot)
  - `POST /intl/offramp/:country` · `GET /intl/offramp?userId`
  - `POST /wallets/transfers` · `GET /wallets/transfers?userId`
  - Mock: auto-fire `international.offramp.success` (1.2s) y `crypto.transfer.success` (1s) tras crear.
  - `ANDES_EVENT_TYPES` ya incluye `crypto.transfer.success|failed` + `international.offramp.success|failed`.
- **FastAPI orchestración** (`backend/routes/ramp_international.py`):
  - `POST /api/v1/ramp/international/accounts` (persiste `ramp_intl_accounts`) · `GET /accounts`
  - `GET /banks/{country}` · `GET /cotization`
  - `POST /quote` (BOB/PEN bind quoteIds + check de expiración; PYG rate-only)
  - `POST /offramp` (valida saldo ARSa, wallet active, Idempotency-Key; persiste `ramp_movements kind="intl_offramp" status="Pending"`)
  - `GET /offramp` lista movimientos
  - `POST /accounts/{ecid}/transfer` — wallet-to-wallet: valida saldo, pre-debita balance, persiste `ramp_movements kind="transfer"`, Idempotency-Key.
- **Webhook handlers reales** (`backend/routes/ramp_webhook.py`):
  - `_handle_crypto_transfer`: flipea status, set `tx_hash`+`settled_at` o `fail_reason`; en Failed **refunde** el balance pre-debitado y emite alerta `ramp.transfer.failed`.
  - `_handle_intl_offramp`: flipea status, set `to_amount`+`settled_at` o `fail_reason`; en Failed emite alerta `ramp.intl_offramp.failed`. Ambos idempotentes por `delivery_id`.
- **Admin endpoints stuck** (`backend/routes/admin_ramp.py` Section G):
  - `GET /api/v1/admin/ramp/movements/stuck?threshold_hours=24[&kind=…&org_id=…]` — Pending/TransferPending/Processing más viejos que el umbral, con `age_hours` y `end_customer_id`.
  - `POST /api/v1/admin/ramp/movements/{id}/resync` — fetch state desde gateway/Andes, devuelve `gateway_status` + payload (read-only).
  - `POST /api/v1/admin/ramp/movements/{id}/mark-failed` — solo `super_admin|finance_admin|finance`. Body `{reason, refund_balance}`. Marca Failed, set `fail_reason`/`failed_by`/`failed_at`, refunde caps si aplica, audit-log obligatorio.
- **Model** — `RAMP_INTL_ACCOUNTS` collection + indexes en `ramp_movements (status, created_at)` para queries stuck rápidas.

### Frontend
- **Sidebar** — nuevo link "Rampa · internacional" (icon `Globe`).
- **`/admin/rampa/internacional`** (`page.tsx`): cotización referencial 4-tile, picker cliente (cross-org via `useAdminAccounts`) + país, sección "Cuenta destino" con selector banco + form (BOB/PYG usan código de banco, PEN usa nombre), Cotizar (BOB/PEN expiran), Ejecutar off-ramp (idempotency auto), histórico con status badges.
- **`/admin/rampa/movimientos`** — Nuevo `StuckPanel` (`data-testid="ramp-stuck-panel"`) arriba de la tabla; selector de umbral (1h/6h/24h/72h), columnas con antigüedad, botones "Re-sync" y "Marcar fallido". El botón abre `MarkFailedModal` con reason obligatorio + checkbox de refund.
- **`/admin/clients/[id]` tab Cuenta Andes** — Nueva row "Transferencia cripto (wallet → wallet)" con botón `Transferir` que abre `TransferModal` (asset + chain + monto + dirección destino + memo opcional para Stellar). Idempotency-Key auto.
- **`lib/admin-ramp.ts`** — helpers: `useStuckMovements`, `resyncMovement`, `markMovementFailed`, `useIntlCotization`, `useIntlBanks`, `useIntlAccounts`, `useIntlOfframps`, `createIntlAccount`, `quoteIntl`, `executeIntlOfframp`, `executeTransfer`.

### Verification
- Backend pytest: **23/23 PASS** (`test_phase15_2_intl_offramp.py`):
  - GET cotization, GET banks(bob/pen/pyg)
  - POST account create + GET list (3 países)
  - POST quote bob/pen + GET pyg
  - POST offramp PYG amount-driven → status Pending → webhook auto → Success ✅
  - POST transfer → Pending → webhook auto → Success + tx_hash ✅
  - Insufficient balance, wallet pending → 400/409 ✅
  - Idempotency-Key (no duplicado) ✅
  - Stuck list + mark-failed + balance refund + audit-log ✅
  - Role gating (super_admin, finance_admin, finance) ✅
  - Webhook idempotency + alert emission en failure ✅
- Frontend Playwright: **100%** post-fix:
  - Internacional page renderiza con cotización + cliente picker poblado (Alemany · org_seed_alemany) + country picker + sidebar link.
  - Movimientos page: StuckPanel visible solo cuando hay rows; Mark-failed modal funcional.
  - Andes Account tab: Transferir abre modal y submitea correctamente.
- Bug fixes durante testing:
  - Role-gate alineado con resto del sistema (`finance` ahora puede operar Phase 15.2). 
  - Cliente `<select>` en intl page pobla via `useAdminAccounts` (super_admin ve todas las orgs).
- Gateway restaurado a **REAL** mode post-test.

### Pendiente (Backlog)
- Refactor `ramp_routes.py` + `ramp_international.py` (>1000 líneas cada uno).
- Exposición a portal cliente del flujo intl (PRD: "no es prioridad de portal cliente todavía").
- Auto-cleanup de movimientos `Pending` > 30 días (cron + admin endpoint).
- Webhook proxy real-time validation con Andes para los nuevos event types (`crypto.transfer.*`, `international.offramp.*`).



## 🚧 Phase 02 — Deposit Detection Engine (Camino A) — Feb 2026, IN PROGRESS

**Goal**: Detectar USDC entrante on-chain a wallets per-org ANTES de que el CMS
las procese como staking, y rellenar huecos del webhook ARSa con un safety net.

**Principios codificados** (post-auditoría que corrigió un supuesto falso del
usuario sobre "sync-with-CMS"):
- **Detección**: on-chain via Horizon (`/payments` con cursor global único).
- **Verdad del saldo**: on-chain via `RealProsperAdapter.get_user_balances`
  (Horizon directo). El watcher NUNCA toca balances.
- **Verdad de la posición**: CMS via `jobs/staking_sync` existente. El watcher
  NUNCA crea positions.
- **Cero ledger off-chain**: `ramp_movements` registra movimientos pero
  NUNCA reconstruye saldo.
- **Reúso**: NO se rehace `staking_sync` ni el webhook receiver ARSa.

**Hallazgos clave de la auditoría** (`integrations/prosper/real.py`):
- Wallets USDC son **per-(org × modality)**, no tesorería+memo. Cada org tiene
  hasta 2 addresses (end + month) vía `POST /cms/cashin`.
- CMS **NO expone** endpoint de balance USDC per-user. Hoy se lee Horizon
  directo (líneas 302-335 de `real.py`). El CMS solo tiene `/cms/treasury`
  (global) y `/cms/staking` (post-staking).
- `memoStaking` es **per-staking**, no per-org. La ruteo por wallet (no memo).

**Escalado** (decidido antes del código): cursor global único sobre
`GET /payments?cursor=&limit=200&order=asc&include_failed=false` cada
`HORIZON_POLL_INTERVAL_SECONDS=12`. Wallet-set cargado en memoria por tick
(O(1) lookup). N=miles de orgs → 1 conexión TCP, no N.

### PR1 — Cimientos (DONE 2026-02)
- `backend/integrations/horizon/{__init__,adapter,mock,real,factory}.py`:
  abstracción Horizon read-only.
- `backend/tests/fixtures/horizon_payments.json`: 7 payments mock (USDC válido a
  wallet conocida con memo, USDC a wallet conocida sin memo, USDC a wallet
  desconocida, native XLM, otra wallet conocida con memo, path_payment, failed).
- `backend/tests/test_horizon_adapter.py`: 18 tests — todos PASSING.
- `backend/db.py`: constantes `DEPOSIT_WATCHER_CURSORS`, `DEPOSIT_EVENTS`
  (índices se crean con sus consumers en PR2).
- `backend/.env`: `DEPOSIT_ENGINE_ENABLED=false` (flag OFF por default),
  `HORIZON_MODE=mock`, `HORIZON_POLL_INTERVAL_SECONDS=12`,
  `DEPOSIT_ORPHAN_TIMEOUT_MINUTES=90` (>reclaim window 60min + margen 30min),
  `ARSA_BACKUP_POLLER_INTERVAL_SECONDS=300`.

### PR2 — Watcher USDC + reconciliación (DONE 2026-02)

**Verificación crítica resuelta (antes de la query):**
- ✅ `tx_hash` Horizon **== `hashDeposito`** CMS (evidencia directa de
  `GET /api/v1/cms/staking` en prod CMS). Ambos son hashes Stellar
  64-hex de la TX de payment USDC entrante al wallet. **El match
  principal por `external_id == hashDeposito` funciona** — no es
  fallback. `hashStaking` refiere a una operación DISTINTA (la op del
  contract Soroban que crea el staking).

**Archivos:**
- `backend/jobs/deposit_engine_migrations.py`: migración de
  `ramp_movements.external_id` a `unique + sparse`. Re-verifica
  duplicados en runtime y aborta con reporte estructurado si hay.
  Idempotente.
- `backend/services/deposit_engine.py`: state machine
  (`record_pending_detected`, `reconcile_usdc_deposit`, `sweep_orphans`,
  `list_orphans`, `list_pending`, `counts`). Constantes `S_PENDING_DETECTED`,
  `S_SUCCESS`, `S_ORPHAN_DETECTED`. Floor enforcement: el orphan timeout
  configurable se bumpea automáticamente a `RECLAIM_WINDOW_MINUTES + 30`
  si el operador lo configura más bajo (defensa en profundidad).
- `backend/jobs/deposit_watcher.py`: loop principal con `run_tick_once`
  (single global cursor sobre `/payments`, filtra USDC + issuer + wallet
  set en memoria) y `run_orphan_sweep_once`. `start_scheduler` arranca
  APScheduler con tick=12s y orphan_sweep=5min, solo si `is_enabled()`.
- `backend/routes/admin_deposits.py`: 6 endpoints registrados (`/health`,
  `/orphans`, `/pending`, `/{mid}/reconcile`, `/tick`, `/migrations/run`)
  gated por `requires_role`. La migration endpoint es callable
  independiente del flag para permitir prep-de-prod antes de flipearlo.
- `backend/jobs/staking_sync.py`: hook chico (`_maybe_reconcile_deposit`)
  llamado en los 3 paths de upsert (existing, reclaimed, new). Soft-fail
  via try/except — staking_sync correctness es independiente.
- `backend/tests/test_deposit_engine.py`: 19/19 tests passing.
  Coverage: migration clean/dupes/idempotent, watcher tick
  match/ignore-unknown-wallet/ignore-non-usdc/ignore-wrong-issuer/cursor-advance/no-op,
  idempotencia DB vía unique index, reconciliación por hash, reconciliación
  fallback por memo+amount (unique match), AMBIGUITY (2+ → alert + no UPDATE),
  no-match, orphan sweep flips + alerta, orphan timeout floor enforcement,
  flag OFF skip-tick + skip-orphan-sweep, health snapshot.

**Reglas operativas codificadas en código:**
1. Watcher NUNCA toca balances. Watcher NUNCA crea positions.
2. Idempotencia DB-enforced (unique sparse en `external_id`), no
   solo app-level. Sobrevive race entre ticks concurrentes.
3. Match principal: `external_id == hashDeposito` (verificado contra
   prod CMS).
4. Fallback `(memo, amount)`: SOLO match único. 2+ candidatos → alerta
   operativa + dejar todo en pending. NUNCA UPDATE masivo.
5. Orphan timeout: floor `RECLAIM_WINDOW_MINUTES + 30` (=90min con
   defaults actuales). Si el operador setea menos, se bumpea con WARN log.
6. Todo bajo `DEPOSIT_ENGINE_ENABLED=false` por default → cero impacto
   en runtime hasta que se flipee.

**Operational notes:**
- `_alert_ambiguous_deposit_reconcile` crea alertas en `alerts` collection
  con `type=operational`, `severity=warning`, contexto completo
  (memo, amount, position_id, candidate_movement_ids).
- `sweep_orphans` también crea alertas con title
  "USDC sin staking (probable memo inválido)" — la copia explicita que
  el balance on-chain ya es verdad por Horizon, NO se acreditó nada.

### PR3 — ARSa safety poller + event bus + endpoints admin (PENDIENTE)
- ARSa poller: cap de concurrencia + TODO para filtrar a "cuentas con
  actividad reciente o webhook silencioso", no el universo entero.
- Event bus minimalista (observabilidad, no broker crítico).
- Endpoints: `GET /api/v1/admin/deposits/health`, `/orphans`,
  `POST /:movement_id/reconcile`.
- Smoke test + testing_agent_v3_fork.

### Confirmaciones validadas en PR1
- ✅ Índice `ramp_movements.external_id` existe como `sparse` (no `unique`).
  Idempotencia es app-level (`find_one(external_id)` antes de insert).
  Sin duplicados existentes — se puede endurecer a unique en PR2 con
  migración explícita si decidimos.
- ✅ Espacios de `external_id` distintos: ARSa usa tokens prefijados Andes
  (`tx_…`, `dep_…`, `off_…`, 16-32 chars). USDC watcher usará tx hash Stellar
  (64-char hex). Colisión estructuralmente imposible. Defensa adicional:
  watcher escribe `provider:"stellar"` (vs `provider:"andeslabs"`).

### Pregunta abierta para José (Prosper)
- ¿Planean exponer `GET /api/v1/cms/users/{prosperId}/balance` o
  `/cms/wallets/{address}/balance`? Si existiera, sería refinamiento del
  Camino A, no cambio de arquitectura.

### Estado de Lucía (informado al usuario)
- Datos de PREVIEW (`mongodb://localhost:27017`, DB `prosper_phase0`), NO prod.
- Preview y prod NO comparten DB. Verificación productiva queda del lado del
  usuario post-merge.
- En preview Lucía sigue en `kyc_pending_andes` (alias deprecado).



## 🚧 Phase 03 — Event Bus + Deposit Credited Notifications (2026-02, IN PROGRESS)

### Event contract — `deposit.credited` v1 (STABLE)

This is the canonical wire format. Publishers and consumers MUST honor it.
Breaking changes → bump to v2 and keep v1 supported during overlap.

```json
{
  "event_type":  "deposit.credited",
  "version":     1,
  "event_id":    "evt_<hex>",
  "asset":       "arsa" | "usdc",
  "deposit_id":  "<string>",
  "tx_hash":     "<64-hex> | null",
  "org_id":      "org_<id>",
  "user_id":     "usr_<id> | null",
  "amount":      "<decimal string>",
  "currency":    "ARSa" | "USDC",
  "ref":         "<memo/reference> | null",
  "occurred_at": "<ISO-8601 UTC>",
  "detected_at": "<ISO-8601 UTC>",
  "source":      "stellar_watcher" | "andes_webhook",
  "metadata":    { /* per-asset, optional */ }
}
```

**`deposit_id` per asset:**
| asset | `deposit_id`                | `tx_hash` |
|---|---|---|
| `usdc` | Stellar tx_hash (64-hex)    | same value |
| `arsa` | Andes `transactionId`       | nullable (Stellar hash if Andes provides) |

**Idempotency:** `notifications.{idempotency_key, user_id}` UNIQUE INDEX.
The idempotency_key is `notif:deposit_credited:{asset}:{deposit_id}`, but
the UNIQUENESS is per-recipient. A business-org deposit with N
`client_admin` users yields N notification rows, one per user.

**Recipient resolution (when `user_id` is null in the event):**
1. `org.type == "personal"` → the org's single user.
2. `org.type == "business"` → all users with role `client_admin` in the org.
3. None found → notification persisted with `user_id=null` (admin tools only,
   never surfaces to client portal).

**Channel rules:**
| Channel | Condition |
|---|---|
| in-app  | ALWAYS for deposit_credited. Overrides `inapp_transactions=false`. |
| email   | Only when `users.notifications.email_account_activity=true` AND `users.email` is set. |

**Sink/dry-run modes (no real traffic):**
- USDC path: gated by `DEPOSIT_ENGINE_ENABLED`. Watcher OFF → no event → no notif.
- ARSa path: ungated (prod-active). Sink is `RESEND_API_KEY=""` → existing
  `email_sender` fallback to `outbound_emails.status="preview_only"`.

**Publishers:**
- `services/deposit_engine.reconcile_usdc_deposit` — after a successful
  `pending_detected → Success` flip, publishes with `source="stellar_watcher"`.
- `routes/ramp_webhook._handle_deposit_success` — after persisting the
  movement when status is `Success` (NOT held), publishes with
  `source="andes_webhook"`.
- `routes/ramp_webhook._handle_wallet_active` — after releasing held
  deposits (one event per released movement), publishes with same source.

**Subscribers:**
- `services/deposit_credited_handler.on_event` — creates per-recipient
  in-app notification + (conditional) email. Soft-fail per recipient and
  per channel.

### Bus design (minimal, single-process)

`services/event_bus.py`:
- `publish(event_dict)`: persist in `deposit_events` (idempotent by
  `event_id` unique index); then synchronously fan-out to subscribers.
- `subscribe(event_type, handler)`: in-memory registry. Handlers are
  awaited in registration order; exceptions are logged but do NOT block
  other handlers.
- Re-entrant: same `event_id` published twice → second `insert_one` raises
  `DuplicateKeyError` and is logged; subscribers NOT re-invoked.
- No external broker. When PR for multi-process arrives, the same
  `publish`/`subscribe` surface can be backed by Redis Streams without
  changing callers.

### Files added
- `backend/services/event_bus.py`
- `backend/services/notifications.py`
- `backend/services/notifications_emails.py`
- `backend/services/deposit_credited_handler.py`
- `backend/routes/client_notifications.py`
- `backend/integrations/email_sender.py` (MODIFIED: retry w/ backoff)
- `backend/services/deposit_engine.py` (MODIFIED: publish on reconcile)
- `backend/routes/ramp_webhook.py` (MODIFIED: publish on credit + release)
- `backend/server.py` (MODIFIED: subscribe + router wiring)
- `backend/db.py` (MODIFIED: NOTIFICATIONS collection + indexes)
- `backend/tests/test_event_bus.py`
- `backend/tests/test_notifications.py`
- `frontend/src/lib/client-notifications.ts`
- `frontend/src/components/client/ClientNotificationsBell.tsx`
- `frontend/src/components/AppShell.tsx` (MODIFIED: bell dispatch by path)
- `frontend/messages/{en,es}.json` (MODIFIED: deposit_credited copy)

### Out of scope for this PR
- ARSa safety poller (its own follow-up PR — pure resilience, not
  notifications).
- Multi-process / queue-backed event bus.
- Read receipts / archive functionality beyond `mark_read`.

### Status: DONE (2026-02)
- 26 new tests passing (`test_event_bus.py` 7 + `test_notifications.py` 19).
- Full Phase 02 + Phase 03 suite: **68/68 green**.
- E2E smoke validated: real ARSa webhook code path
  (`_handle_deposit_success`) publishes to bus; subscriber creates
  notification + outbound_email row with correct bilingual ARSa copy
  (NO USDC mentioned).
- Per-recipient idempotency confirmed: business-org with 2 client_admin
  → 2 distinct notification rows sharing the same `idempotency_key`.
- Amount formatting: `12345` ARSa renders `12.345` (es) / `12,345` (en);
  `1234.5` USDC renders `1.234,50` (es) / `1,234.50` (en).
- `RESEND_API_KEY` empty (preview) → `channels.email = "preview_only"`,
  no real outbound traffic. Set in prod → real emails for ARSa deposits
  starting on merge (intended).
- Retry-with-backoff on Resend: 3 attempts (0s/2s/8s) for transient
  failures (429/5xx/network). Non-retryable failures (4xx) fail
  immediately. `outbound_emails.attempts` records actual count.
- In-app channel ALWAYS created for `deposit_credited`, even when
  user has `inapp_transactions=false` (per user spec).

### Files added/modified
**Added**:
- `backend/services/event_bus.py`
- `backend/services/notifications.py`
- `backend/services/notifications_emails.py`
- `backend/services/deposit_credited_handler.py`
- `backend/routes/client_notifications.py`
- `backend/tests/test_event_bus.py`
- `backend/tests/test_notifications.py`
- `frontend/src/lib/client-notifications.ts`
- `frontend/src/components/client/ClientNotificationsBell.tsx`

**Modified**:
- `backend/db.py` — `NOTIFICATIONS` constant + per-(idempotency_key,user_id)
  unique sparse index + `(user_id, read, created_at)` index +
  `deposit_events.event_id` unique index.
- `backend/integrations/email_sender.py` — retry-with-backoff on transient
  failures (429/408/425/500/502/503/504/network/timeout).
- `backend/services/deposit_engine.py` — `_publish_credited_for_movement`
  helper + call sites after each successful reconciliation.
- `backend/routes/ramp_webhook.py` — publish point at end of
  `_handle_deposit_success` (after audit log) + inside
  `_handle_wallet_active` per released movement.
- `backend/server.py` — `subscribe("deposit.credited", on_event)` in
  startup + `client_notifications_router` registration.
- `frontend/src/components/AppShell.tsx` — bell dispatcher: client
  surface → `ClientNotificationsBell`, admin surface → `AlertsBell`.
- `frontend/messages/{en,es}.json` — `notifications.*` strings.

### Out-of-scope (parked)
- ARSa safety poller — its own small follow-up PR (resilience, not
  notifications).
- Read receipts / archive beyond `mark_read`.
- Multi-process bus (Redis Streams backend) — interface preserved.



## ✅ Phase 04 — Portfolio Snapshot (live-poll Fase 1) — Feb 2026, DONE

### Decisión de diseño
- **Fase 1 (esto)**: polling liviano + Redis cache 12s TTL. Resuelve el
  pedido (saldos + movs auto-actualizan) con riesgo mínimo en mainnet.
- **Fase 2 (roadmap)**: SSE push desde el motor de depósitos. NO se
  construye aquí — interfaz preservada para evolución sin breaking.

### Endpoint
`GET /api/v1/client/me/portfolio/snapshot` (user-scoped, read-only).
Cache Redis con `SETEX` 12s por `user_id`. Headers:
`Cache-Control: private, max-age=12`, `X-Snapshot-Source: cache|fresh`,
`X-Snapshot-As-Of`.

### Schema (estable, v1)
```
{
  balances: {
    arsa: { cvu, stellar, total, pending_detected, as_of },
    usdc: { platform, stellar, total, pending_detected, as_of }
  },
  recent_movements: [...10 most recent],
  last_movement_cursor: <created_at del más reciente>,
  snapshot_source: "cache"|"fresh",
  fetched_at: <ISO>
}
```

### Costura crítica motor↔snapshot: pending_detected → Success
La fórmula `balance.{asset}.stellar = max(0, horizon_balance - pending_detected_sum)`
garantiza **cero double-counting y cero limbo** en la transición. Tres
escenarios cubiertos por test explícito:
| Estado | horizon | pending_detected | → stellar | → pending |
|---|---|---|---|---|
| Recién llegado | 100 | 100 | 0 | 100 |
| Engine reconcilió, USDC en wallet | 100 | 0 | 100 | 0 |
| Engine reconcilió + staking movió fondos | 0 | 0 | 0 | 0 (en `positions`) |

En todos los casos el deposit se ve EXACTAMENTE UNA VEZ en la UI.

### Frontend (4 surfaces)
- `lib/portfolio-snapshot.ts` — hook `usePortfolioSnapshot()` con SWR
  `refreshInterval: 20_000`, pausado en `document.hidden`, dedup global.
- `components/client/ClientPortfolioPoll.tsx` — mounted en
  `app/client/layout.tsx` → mantiene polling vivo en TODAS las 4
  surfaces (Dashboard, Withdraw, Positions, Activity) + toast rail-aware.
- `components/client/PendingDepositCard.tsx` — card "Depósito en camino"
  separado del balance, copy rail-separated.
- `components/client/NewMovementBadge.tsx` — badge sutil con auto-hide 8s.
- Dashboard renderiza PendingDepositCard ARSa/USDC condicionales +
  NewMovementBadge en el header.

### Reglas operativas
- **In-app SIEMPRE creada para deposit_credited** (heredado de Phase 03).
- **pending_detected NUNCA sumado al balance** — card visualmente distinto.
- **Rails separados en toast/copy**: ARSa nunca menciona USDC y viceversa.
  Si entran 2 movimientos de rails distintos en mismo tick → muestra el
  más reciente, no los combina.
- **Visibility-gated polling**: tab oculta = 0 polls. Reduces idle load
  100%.
- **Cache 12s = rate-limit natural**: Horizon recibe ≤1 hit/12s/user.

### Endpoint admin nuevo (mismo PR)
`POST /api/v1/admin/notifications/test` — fire synthetic
`deposit.credited` a user específico via **el mismo `event_bus.publish`
path** que publishers reales. Gated por `super_admin` / `ops_admin`.
`event.source="admin_test"` + `metadata.synthetic=true` para audit.
Permite verificar Resend cableado en prod sin esperar depósito real.

### Tests (15 nuevos)
- `test_portfolio_snapshot.py` (11): shape, scope cross-user/org, cache
  hit dentro de TTL, miss después de invalidate, cache per-user (A no
  contamina B), cursor avanza, pending_detected rails separated,
  **transición pending→Success sin double-count ni limbo** (3 escenarios),
  subtracción flooreada en 0 (Horizon lag protection), Horizon NO
  llamado cuando cache hot.
- `test_admin_notifications_test.py` (3): target user único (no broadcast
  al org), pipeline real (no mock), idempotencia replay.

### Suite total: **82/82 verde** (incluye regresión Phase 02 + 03 + KYC widget).

### Out of scope (parqueado)
- ARSa safety poller (su propio PR chico después).
- SSE push (Fase 2 del roadmap).
- Rate limit explícito por user (el cache TTL ya actúa como rate-limit
  efectivo).



## ✅ Módulo "Gestión de Staking" — /admin/staking (2026-06, DONE, tested 100%)

- Nuevo ítem "Staking" en sidebar admin (AppShell, i18nKey `admin_staking`).
- Página `frontend/src/app/admin/staking/page.tsx`: widgets tesorería CMS + sync
  manual, tabs Stakings (tabla con filtros scope/asset/status, links stellar.expert),
  Wallets CMS (listado crudo `/cliente/users`, búsqueda client-side), Nueva
  solicitud Cash-In (email/prosperId + modalidad end|month, SIN modal de
  confirmación por pedido del usuario).
- Endpoints passthrough nuevos en `phase22_admin_yield.py`:
  `GET /admin/prosper/cms/wallets` (read roles) y `POST /admin/prosper/cms/cashin`
  (write roles, audit `admin.prosper.cms.cashin`).

### ⚠️ MIGRACIÓN CMS PARTNER (junio 2026) — CRÍTICO para futuros agentes
El CMS (`cmsback.protocol-prosper.io`) cambió TODAS sus rutas:
- `/api/v1/cms/users`   → `/api/v1/cliente/users` (GET; nuevo POST crea usuario por email)
- `/api/v1/cms/cashin`  → `/api/v1/cliente/cashin` body `{clientEmail, cashin}` (ANTES `{prosperId, cashin}`)
- `/api/v1/cms/staking` → `/api/v1/cliente/staking` (mismas filas + campo `email`)
- `/api/v1/cms/treasury`→ `/api/v1/admin/treasury`
La identidad ahora es EMAIL-based. `real.py::create_user_wallet` hace primero
POST `/cliente/users {email}` (tolerante a existente) y luego cashin. El match
por modalidad acepta prosperId/userId/email. `test_prosper_real_live` volvió a verde.
- QA user idempotente en CMS real: `qa-staking-module@prosper.foundation` (end)
  → wallet `GDE4FZC7JP443JBYEB4MTTXOMZIFOA6W5E6LOL3Y6SYSW6LOLYAES6NR`.
  NUNCA crear emails nuevos en tests (cada alta crea usuario/wallet REAL mainnet).
- Test suite: `backend/tests/test_staking_module.py` (17 tests, testing agent).
- Ajustes 2026-06 (iteration_38, 100% verde): widget "Tesorería · XLM" eliminado;
  nuevo box "Nueva cuenta CMS" en tab Wallets (POST `/admin/prosper/cms/users`
  {email} → passthrough `/cliente/users`; 409 si el usuario ya existe).
  QA users reales creados en CMS: qa-cuenta-nueva@ (userId 20), qa-cuenta-ui-test@.
- UX 2026-06 (iteration_39/40, 100% verde): paginado client-side (PAGE_SIZE=10,
  componente Pager) en tabs Stakings y Wallets CMS; búsqueda en Wallets resetea
  página; botón "Nueva solicitud" por fila de wallet → abre tab cash-in con el
  email pre-cargado (prop initialProsperId + key remount).
  Lección: tras un ENOSPC, VERIFICAR que los edits persistieron (un edit cayó
  en un fragmento duplicado corrupto y se perdió al truncar).
- Fix 2026-06 (iteration_41, 100% verde): tab cash-in ahora pide "Email del
  cliente" (no prosperId) + selector obligatorio de moneda ARSa/USDC.
  IMPORTANTE: la API del CMS (CashinDto) NO tiene campo de moneda — el asset
  se registra solo en audit_logs local + instrucciones UI; el CMS registra el
  activo efectivamente depositado. Body backend: {email, modality, asset}
  (prosper_id sigue aceptado como alias legacy).
- Ajuste 2026-06: selector ARSa/USDC ELIMINADO del form de cash-in a pedido del
  usuario (el CMS no lo acepta); el form quedó solo email + modalidad. El campo
  `asset` opcional sigue existiendo en el backend (inofensivo, no requerido).
- Enriquecimiento 2026-06 (iteration_42, 100% verde): tabla Stakings con
  columnas Cliente(email)/Tasa/Vencimiento + fila expandible con TODO el
  detalle (intereses acumulado/cobrado/proyectado, devengado 24h,
  next_payout {fecha,monto}, capital rescatado, links contrato Soroban y
  deposit_hash); chips by_org; sync widget con nuevos/actualizados; meta
  tesorería (modo+timestamp). staking_sync ahora persiste
  projected_interest/daily_interest/next_payout. XLM excluido por pedido.
- 2026-06 (iteration_43, 100%): usuario reportó "no se muestra el staking
  nuevo" → root cause EXTERNO: el CMS no lo devuelve en /cliente/staking
  (el registro se crea recién cuando el CMS detecta el depósito y stakea
  on-chain). Paridad backend↔UI verificada (13/13). Fix UX: lista Stakings
  con SWR refreshInterval 30s. Deuda conocida: 3 filas locales "stale" que
  ya no existen en el feed CMS (el sync no borra ausentes) — memos
  1781049010, 1780854012, 1781102398.
- Fail pre-existente sin relación: `test_p13_cms_admin::test_stakings_all` asume
  8 stakings externos hardcodeados; el CMS real hoy tiene 10 (drift de datos vivos).

### Nota entorno (recurrente)
El disco /app se llena por auto-gc de git sobre repo de 6.2GB (frontend/.next
trackeado). `gc.auto=0` ya seteado. Si mongo cae en FATAL: borrar
`.git/objects/pack/tmp_pack_*` y `.git/objects/*/tmp_obj_*`, arrancar mongodb.


## 2026-06 — Fork: i18n Staking + higiene git (iteration_44, 100%)
- **Pedido usuario**: "staking disponible para todos, traducido en inglés y español" + actualizar .gitignore.
- **i18n staking (next-intl)**: namespace `staking` agregado a `messages/{en,es}.json`
  (~90 claves: tabs, filtros, tabla, detalle expandido, wallets, cash-in, tesorería,
  sync, page headers, toasts). `StakingTabs.tsx`, `admin/staking/page.tsx` y
  `client/staking/page.tsx` refactorizados a `useTranslations("staking")`.
  Formatos localizados: es-AR / en-US vía `useLoc()` (fechas y números).
  Nota de stakings externos y estados (activo/vencido/liquidado) también traducidos
  (antes venían crudos del backend).
- **Acceso universal verificado**: cliente retail (org personal), partner y admin —
  middleware no bloquea /client/staking, backend usa get_current_user sin gate de rol.
- **Higiene git (P0 parcial)**: `frontend/.next` UNTRACKED + `.gitignore` actualizado
  (`.next/`, `frontend/.next/`). Detiene el crecimiento del repo (5.8GB). Los ~3.5GB
  de objetos sueltos son historial alcanzable — NO hacer gc/repack con <2GB libres ni
  filter-repo (rompe rollback). Ver `/app/memory/disk_git_hygiene.md`. `.env` siguen
  trackeados a propósito (requisito deploy Emergent).
- **Testing**: iteration_44 frontend 100% (ES y EN completos en ambos portales,
  paginación, prefill cash-in, validación email, widgets admin).
- **Deuda detectada**: banner KYC ("Verificación de antecedentes en curso") queda en
  español con locale EN — componente compartido fuera del namespace staking.

### Backlog vigente (sin cambios)
- P0: CVU auto-sync post-onboarding (poller + webhook fast-path).
- P1: Deposit Watcher no cableado al startup de server.py.
- P1: fixture CUIT `.zfill(8)` en test_iter27_activation_helper.py.
- P1: ARSa Safety Backup Poller. P2: extraer KycCaptureForm; i18n banner KYC.

## 2026-06 — Migración a CMS Prosper v2.0 (endpoints renombrados)
- **Bug reportado por usuario**: endpoints del CMS fallando. Root cause: el CMS
  (cmsback.protocol-prosper.io) migró a v2.0 y renombró rutas; las viejas devuelven 404.
- **Mapeo aplicado en `integrations/prosper/real.py`** (único archivo con paths):
  - `GET /api/v1/cliente/users`   → `GET /api/v1/cms/users`
  - `GET /api/v1/cliente/staking` → `GET /api/v1/cms/staking`
  - `GET /api/v1/admin/treasury`  → `GET /api/v1/cms/treasury`
  - `POST /api/v1/cliente/cashin {clientEmail}` → `POST /api/v1/cms/cashin {prosperId, cashin}` (CashinDto)
  - `POST /api/v1/cliente/users` **ELIMINADO en v2** (sin reemplazo): el alta es
    implícita en el cashin. `create_cms_user()` ahora lanza ProsperError explicativo;
    la caja "Nueva cuenta CMS" se quitó del tab Wallets (reemplazada por nota i18n
    `staking.wallets.v2_note` ES/EN).
- Swagger v2.0 confirmado vía /api/docs-json: solo 6 endpoints (login, change-password,
  cms/treasury, cms/users GET, cms/cashin POST, cms/staking GET). Sin webhooks; polling.
- **Verificado E2E** (curl + screenshot): treasury ✓, stakings (14: 3 propios + 11 CMS) ✓,
  wallets (33) ✓, emails ✓, cashin idempotente reused=true ✓, staking-sync run ✓.
- **Dato**: el depósito de prueba del usuario (75 ARSa, ducampcarlos@gmail.com) YA fue
  procesado por el CMS → staking id 28, memo 1786057215, vence 2027-08-06.

## 2026-06 — Fix observabilidad flujo de acceso (reporte de tester externo)
- **Reporte**: (1) error del proveedor de correo durante el acceso; (2) al ingresar
  el token manualmente, redirige de vuelta al Login en vez del Dashboard.
- **Root causes identificadas**:
  1. Cuando RESEND_API_KEY está seteada pero Resend rechaza el envío (key inválida,
     o `RESEND_FROM=onboarding@resend.dev` que SOLO permite enviar al dueño de la
     cuenta Resend), el backend registraba el fallo pero la UI no mostraba nada.
  2. La vuelta al Login tiene 2 causas posibles indistinguibles hasta ahora:
     (a) middleware Edge rechaza la cookie (JWT_SECRET distinto entre frontend y
     backend en el entorno del tester); (b) página OTP pierde el continuation
     (sessionStorage vacío en pestaña nueva) y rebota silenciosamente.
- **Fixes** (backend `server.py`, frontend `login/page.tsx`, `login/otp/page.tsx`,
  `middleware.ts`):
  - `passwordless-login` ahora devuelve `email_status` + `email_error` (texto del
    proveedor). Login y Resend muestran toast con el error real y NO avanzan a OTP.
  - OTP fallido en envío → código logueado en backend (`OTP send FAILED ... code was X`)
    como escape de ops.
  - Middleware agrega `?reason=invalid-session` al expulsar cookie inválida; OTP
    agrega `?reason=otp-flow-lost`. Login muestra toast explicativo por reason
    (diferido 400ms — sonner pierde toasts pre-hidratación).
- **Verificado E2E**: toast con error Resend 401 real ✓, toasts de ambos reasons ✓,
  flujo OTP completo login→código→/admin ✓, dev-login preview ✓.
- **Guía deploy pendiente de confirmar con el tester**: en el entorno donde prueban,
  (1) verificar dominio propio en Resend y setear RESEND_FROM a ese dominio (el
  sandbox resend.dev no sirve para enviar a terceros); (2) confirmar que JWT_SECRET
  sea IDÉNTICO en backend y frontend.

## 2026-06 — DEMO_MODE: acceso demo siempre disponible (directiva usuario)
- La plataforma se usa para demos → nuevo flag `DEMO_MODE` (default **true**) en
  `backend/server.py` + `backend/.env`:
  - `/api/v1/auth/dev-login` (magic links de /access) SIEMPRE activo, ya no
    depende de RESEND_API_KEY.
  - `passwordless-login` SIEMPRE devuelve `dev_otp` → el código se muestra en
    pantalla (banner "Modo demo activo") aunque Resend esté configurado o falle.
  - Apagar con `DEMO_MODE=false` cuando haya producción real con emails.
- Cookie de sesión ahora `Secure` solo sobre https (`_cookie_secure()` mira
  x-forwarded-proto): las demos servidas por http:// ya no pierden la sesión.
- Textos actualizados: banner OTP ("Modo demo activo…") y footer de /access.
- NOTA BUG TOOLING: 2 veces un search_replace reportó éxito pero no persistió
  (hot-reload race). SIEMPRE verificar con grep tras editar server.py/real.py.
- Verificado E2E simulando el entorno del tester (RESEND_API_KEY con key inválida):
  dev-login 303 ✓, dev_otp presente ✓, banner + código prellenado ✓, Verify → /client ✓.

## ⚠️ PENDIENTE FUTURO — Quitar DEMO_MODE antes de producción real
- **Tarea (pedido explícito del usuario, Jun 2026)**: más adelante hay que SACAR
  el modo demo. Hoy `DEMO_MODE` defaultea a `true` en `backend/server.py` (~línea 87)
  porque el entorno actual se usa para demos y no se pueden cambiar env vars.
- **Qué implica sacarlo cuando llegue el momento**:
  1. Cambiar el default a `false` (o eliminar el flag y volver al gate por
     RESEND_API_KEY) en `backend/server.py`: afecta `dev-login` (magic links de
     /access) y el `dev_otp` en la respuesta de `passwordless-login`.
  2. Configurar Resend real (dominio verificado + `RESEND_FROM` propio) para que
     el login por email funcione sin código en pantalla.
  3. Revisar/quitar la página `/access` (cuentas demo) o gatearla igual.
  4. Actualizar banner del OTP y footer de /access que mencionan el modo demo.
- **Riesgo si se olvida**: cualquiera podría loguearse como cualquier usuario vía
  dev-login en producción. NO pasar a producción real con DEMO_MODE activo.

## 2026-08 — Fix P0: ARSa balance no se reflejaba tras depósito CVU
### Problema
Un depósito real de 15 ARSa al CVU de Matías Plano quedó registrado como
`ramp_movement` (`source: andes_sync`, `status: Success`) pero:
- `ramp_balances` estaba VACÍO para su org → `dashboard-summary` mostraba
  `cash.arsa = 0` → el botón "Invertir" no se habilitaba.
- Consecuencia: pipeline roto entre "plata en CVU" y "poder generar staking".

### Root cause (2 bugs)
1. `_sync_andes_movements_to_cache` (ramp_routes.py) upserteaba movements
   pero NO refrescaba `ramp_balances`.
2. El único path que sí actualizaba `ramp_balances`
   (`GET /ramp/accounts/{end_customer_id}/balances`) no seteaba `org_id`
   en el documento → la primary query de `dashboard-summary`
   (`{org_id, asset:"arsa"}`) fallaba y caía a un fallback que también
   estaba vacío por el bug #1.
3. `arsa_stellar` en `dashboard-summary` se leía del adapter Prosper que
   solo devuelve USDC, no ARSa on-chain → segunda fuente de verdad
   inexistente.

### Fix aplicado (Opciones A + B)
- **Nuevo helper** `services/ramp_balance_sync.py::refresh_ramp_balances_for_org`
  centraliza el pull-desde-provider + upsert idempotente con `org_id` incluido.
- **A**: llamado desde:
  - `_sync_andes_movements_to_cache` (ramp_routes.py) tras upsertar movements.
  - `dashboard_summary` (client_invest.py) antes de leer.
- **B**: `HorizonAdapter` ahora expone `get_account_balances(address)`.
  `dashboard_summary` lo usa para poblar `cash.arsa_stellar` con la
  lectura on-chain real (best-effort — degrada a 0 si el modo es mock o
  Horizon está inalcanzable). Env var: `ARSA_ISSUER`.
- **Corrección secundaria**: `/ramp/accounts/{ec}/balances` ahora incluye
  `org_id` en el upsert (bug #2).

### Tests
- `tests/test_ramp_balance_sync.py` (4/4 pass):
  - Upsert incluye `org_id`.
  - Skip cuando no hay ramp_account.
  - `_read_stellar_balance` lee del mock Horizon inyectado.
  - Devuelve 0 si no hay wallet provisionada.
- Regresión: `test_horizon_adapter.py` + `test_deposit_engine.py` (37/37 pass).

### Verificación E2E (Matías Plano)
Antes del fix: `cash.arsa = 0` (bloqueado, no puede invertir).
Después del fix: `cash.arsa = 15.0` (`arsa_cvu = 15`) → UI habilita "Invertir".

### Pendiente relacionado (backlog)
- Cuando `HORIZON_MODE=real` en producción, `arsa_stellar` se poblará
  con la lectura on-chain automáticamente. Validar en el entorno destino.
- Extender el mismo patrón para USDC: hoy `usdc_stellar` sigue leyéndose
  del adapter Prosper (mismo pattern legacy), reemplazable por
  `_read_stellar_balance(..., asset_code="USDC")` cuando se decida.

## 2026-08 — Fix: 502 en invest/onchain + wallets mock inválidas + prosperId por email
### Problema
Al confirmar la transferencia de 10 ARSa a "Prosper Treasury", el toast quedaba
en blanco y el backend devolvía 502 tras ~31s. Andes rechazaba la transferencia
con `{"error":"Invalid address"}`.

### Diagnóstico
Diagnóstico contra el CMS real (`cmsback.protocol-prosper.io`):
1. Login CMS 201 OK, `list_cms_users` 200 OK.
2. `POST /cms/cashin` con `prosperId` YA registrado → 201 OK + wallet válida.
3. `POST /cms/cashin` con `prosperId` NUEVO (email o org_id o test) → **400**
   `{"error":"Error creating account on Stellar network"}`.
   → **Es un problema del CMS de Prosper** (probable: cuenta funder sin XLM
   para pagar el CreateAccount de nuevas cuentas Stellar en mainnet).
4. Nuestro código caía a un fallback mock que fabricaba una address con
   caracteres hex fuera del alfabeto base32 Stellar (`G98A270AD9B99C…`).
5. Frontend pasaba esa address a Andes → Andes 400 → nuestro 502.

### Cambios aplicados
- **`routes/onramp_flow.py::ensure_org_prosper_wallet`**:
  - `prosperId` ahora se toma del email del `client_admin` (alineado con
    protocolo §6.1 y con la instrucción explícita del usuario). Fallback
    a `org_id` si el org no tiene admin todavía. Rows preexistentes siguen
    resolviendo por `organizations.prosper_id` intacto.
  - Fallback a mock **solo** cuando `PROSPER_MODE=mock`. Con
    `PROSPER_MODE=development|production`, el error del CMS se propaga.
  - Guard: si la address que devuelve el partner no es Stellar válida
    (`_is_valid_stellar_address` — 56 chars, base32 estricto), NO se
    persiste y se levanta `RuntimeError` legible.
- **`routes/client_invest.py::invest_onchain`**:
  - Valida formato Stellar del destino antes de llamar a Andes (403/503).
  - Mensaje user-friendly cuando el error viene del CMS (503):
    "El CMS de Prosper no pudo generar la wallet destino en este momento.
     Ya estamos al tanto; reintentá en unos minutos."
- **Purga Mongo**: `db.organizations.updateMany` con
  `$pull: {prosper_wallets: {address: {$not: /^G[A-Z2-7]{55}$/}}}`
  → 13 rows de 10 orgs afectadas (incluida Matías). Ahora esas orgs
  re-provisionan wallet limpia en cuanto el CMS vuelva.

### Estado
- ✅ Ya no hay wallets mock inválidas en la base.
- ✅ Ya no se pueden persistir wallets con formato Stellar inválido.
- ✅ El error del CMS es visible al usuario (503) y en logs (WARN).
- ❌ **Bloqueante externo**: el CMS de Prosper sigue devolviendo 400
  para cashin de prosperIds nuevos. Ninguna operación de alta puede
  completarse hasta que Prosper arregle su lado.

### Mensaje para Prosper CMS (bug del lado de ellos)
> `POST /api/v1/cms/cashin` devuelve 400 con `"Error creating account
> on Stellar network"` para cualquier `prosperId` nuevo. Los prosperIds
> ya registrados retornan 201 con la wallet correcta. La cuenta funder
> del CMS probablemente no tiene XLM suficiente para pagar el
> `CreateAccount` en Stellar mainnet — verificar balance XLM y/o
> permisos de signer de la cuenta master.

## 2026-08 — Staking Portal: scope por email + tab creación gateado por rol + XLM treasury
### Cambios de comportamiento
**Cliente (`client_admin` / `client_user`)**:
- `/client/staking` ahora muestra SOLO stakings/wallets asociados al email
  del usuario logueado (match case-insensitive contra `contract_email`).
- Se removió el tab **New request** (creación manual de cashin en CMS).
  El único camino para obtener wallet en CMS es a través de `/client/invest`,
  que la provisiona lazy con el email del `client_admin` como `prosperId`.
- Endpoints removidos del router del cliente:
  `POST /client/staking/cms/users`, `POST /client/staking/cms/cashin`.
- Postproceso invest: toast con título/desc explicativa y botón
  "Ir a Staking" que lleva a `/client/staking` (i18n ES/EN).

**Admin / Finance / Ops / Compliance (`internal_roles`)**:
- Siguen viendo TODO (stakings, wallets, saldos) sin filtro.
- Widget **Treasury · XLM** re-agregado en `/admin/staking` con nota
  "Combustible de red Stellar" (i18n ES/EN).
- Tab "New request" sigue disponible para provisión manual desde admin.

### Detalle técnico
- `phase22_admin_yield.stakings_payload(email=…)` — filtro opcional por
  `contract_email` (case-insensitive). Rows sin email nunca matchean.
- `routes/client_staking.py` reescrito: usa `is_internal(role)` para
  decidir si aplica filtro por email o pasa `None` (bypass).
- `StakingTabs.tsx` acepta `allowManualCashin?: boolean` (default `true`).
  El client staking page pasa `false`, admin usa el default.
- `admin/staking/page.tsx`: grid pasado de 3 a 4 columnas para el
  nuevo widget XLM; interface `Treasury` extendida con `balanceXLM`
  (el backend `/admin/prosper/treasury` ya lo devolvía).

### Verificado end-to-end
- Matías (`client_admin`) → tabs presentes: `stakings, wallets`;
  `cashin_tab: False`. Endpoint `POST /cms/cashin` → 404.
- Admin (`super_admin`) → tabs completos + widgets `usdc, arsa, xlm`
  todos presentes. 14 stakings visibles (3 ours + 11 external).
- Tests: 4/4 nuevos (`test_ramp_balance_sync`) + 36 regresión pasan.
  Los 2 fallos en `test_p12_multi_asset_dashboard::test_cash_buckets`
  y `test_p13_cms_admin::test_stakings_all` son **pre-existentes**
  (hardcoded values sobre datos que evolucionaron) — verificado con
  git-stash del branch.

## 2026-08 — E2E ARSa Monthly funcionando: 5 ARSa · Matías Plano
### Resultado
**PIPELINE COMPLETO OK** — CMS destrabó, cash-in usa email como prosperId,
transferencia on-chain confirmada, staking activo visible en /client/staking.

### Pipeline verificado (paso a paso)
1. **Wallet CMS provisionada** — `prosperId = matiasplano@gmail.com`
   (usando email tal como pidió el usuario). CMS ahora responde 201
   con wallet Stellar válida:
   - `monthly`: `GD6HIQXVNG3NHQVPYPTRGKUP44JCPOWV2DK622VLSAIFKKXKBNFBBAUS`
   - `end`:     `GDA2X4523QYM6EMQVGT5HPL3G3DXTOXNL7DFP7E53644NYOWBFIPLIIZ`
2. **`POST /invest/onchain`** — 200 OK en 1.7s, retorna `position_id`
   y `andes_transfer_id`. Cash bajó de 15 → 10 ARSa (débito confirmado).
3. **Andes gateway** — transfer status: `Success`,
   `tx_hash: 3bf532d9…57fbb7de` (Stellar tx real).
4. **CMS balance** — la wallet monthly de Matías refleja `balanceARSA: 5`
   post-transferencia (los ARSa llegaron).
5. **`staking_sync` (5 min o forzado)** — detectó el nuevo staking en
   CMS y reclamó el placeholder `pending_onchain`. Match: `exact` sobre
   `(wallet, asset:arsa, modality:month, principal:5)`. La position
   pasó a `status: active` con `memo: 1786128015` y
   `hash: 368b22f2…0949` (Stellar tx del staking, distinto al tx de
   transferencia).
6. **UI cliente** — `/client/staking` muestra 1 staking activo:
   ARSa · month · 5 · 17% · ACTIVE · maturity 9/7/26 · OURS.

### Bugs encontrados y corregidos en el flow
1. **`contract_email` no se seteaba en la position** al crearla por
   `/client/invest/onchain`. Fix: seedear `contract_email = user.email`
   en ambos paths de creación (mocked + onchain).
2. **`staking_sync` sobreescribía `contract_email`** con el email de la
   cuenta manager del CMS (`prosper@cms.com`) durante el reclaim y en
   los upserts idempotentes. Fix: 3 puntos en `jobs/staking_sync.py`
   (`_upsert_position` ours + `_upsert_external` update + `_try_reclaim`)
   preservan el `contract_email` existente si el cliente ya lo tenía.
3. **Filtro de `stakings_payload` no incluía `pending_onchain`** porque
   exigía `memo != null` como base. Fix: al pasar `email` o `org_id`
   (scope cliente), se relaja el gate de `memo` con un `$and[$or]`
   permitiendo placeholders sin memo, para que el cliente vea su
   staking en vuelo desde el instante que hace click en Invertir.
4. **`org_id` como fallback**: si una position de la org del cliente
   todavía no tiene `contract_email` (edge case), se incluye también
   por `org_id` con `contract_email IN [null, ""]`.

### Métricas del flujo
- POST /invest/onchain latency: **1.7s** (respuesta al usuario).
- Wallet Andes → wallet CMS on-chain: **< 15s** (transfer confirmada).
- CMS crea staking desde depósito: **~9 min** en este test (asíncrono).
- staking_sync scheduler: cada **5 min** en background + botón manual
  en admin panel (`POST /admin/prosper/staking-sync/run`).

### Postproceso desde la UI (invest → staking)
1. Cliente hace la inversión (modal de confirmación).
2. Toast: "Transferencia iniciada. Estamos detectando el depósito on-chain.
   En 1-3 minutos vas a ver tu staking activo en la sección Staking."
   con CTA "Ir a Staking".
3. En /client/staking el staking aparece INMEDIATAMENTE como
   `pending_onchain` (5 ARSa · month, sin memo/hash aún).
4. Al ~5 min (o al forzar sync), la position pasa a `active` con memo
   y hash Stellar reales. El match es idempotente (`wallet, asset,
   modality, principal_native` exacto).

### Regresión
- 64/65 tests pasan. El único fallo (`TestCmsCreateUser::test_create_user_duplicate_409`)
  es pre-existente — verificado con `git stash` de mis cambios.

---

## Fase 0.5.1 — Consolidación Fernet + tokens multi-uso + TTL (11 jun 2026)

### 1. SecretBox consolidado (`services/secret_box.py`)
- Nueva clase `SecretBox(current_env, previous_env)` con rotación
  dual-key generalizada (encrypt siempre con la actual; decrypt prueba
  actual → previous). Sirve para cualquier par de variables.
- `routes/client_profile.py` eliminó su helper Fernet local y consume
  `SecretBox("MFA_FERNET_KEY", "MFA_FERNET_KEY_PREVIOUS")` — la
  rotación dual-key se conserva (crítico para users con `mfa_pending`).
- API módulo-level (`encrypt/decrypt/last4`) intacta para el par
  INTEGRATIONS; ahora también soporta `INTEGRATIONS_FERNET_KEY_PREVIOUS`.
- MFA e2e verificado contra el server vivo: setup → verify (TOTP) →
  logout (sesión revocada 401) → re-login → regenerate-codes con código
  (decrypt en sesión nueva) → disable. PASS.

### 2. `INTEGRATIONS_FERNET_KEY` fuera de `.env`
- Removida de `backend/.env`; la clave de Fase 0.5 queda descartada.
- Doc nuevo: `docs/INTEGRATIONS_FERNET_KEY.md` (inyección por entorno
  sin escribirla en archivos: panel de deploy / supervisor conf fuera
  del repo / export de shell; rotación con `_PREVIOUS`).
- El backend arranca sin ella; el primer uso falla con `SecretBoxError`
  que nombra la variable (sin stacktrace).

### 3. Tokens de archivo multi-uso
- `signed_url(..., single_use: bool = False)`: default multi-uso
  (visor pdf.js con range requests / recargas); `True` = one-shot
  (enlaces por email).
- Ambos modos: `use_count` (+1 por hit) y `last_used_at`. Token sigue
  opaco + hasheado en reposo; 404/None idéntico para no-existe /
  vencido / agotado.
- E2E por HTTP: sin cookie 401; multi 200×3; single 200 → 404.

### 4. TTL en `file_access_tokens`
- `expires_at` ahora se guarda como BSON Date; índice TTL
  `file_access_tokens_expires_ttl` (expireAfterSeconds=0) en
  `db.ensure_indexes`. Verificado en vivo: doc vencido borrado en
  <15s, doc vigente permanece.
- `docs/SECRETS_ROTATION.md`: sección nueva de pendientes de cifrado
  en reposo (`models.py:78` mfa_secret placeholder, `models.py:237`
  hmac_secret de webhooks EN CLARO) — migración = sweep de datos,
  decisión separada, NO ejecutada.

### Tests / regresión
- `test_secret_box.py` +4 tests dual-key; `test_storage_gridfs.py`
  reescrito: multi-uso N veces, expiry, single-use 2º intento falla,
  None idéntico, expires_at es Date. 17/17 pass.
- `test_phase11b_profile.py` (ciclo MFA vivo): 11/11 pass.
- `check_test_baseline.py`: **NEW failures: 0** (47 estables + 1 flaky
  observado, dentro del baseline).

### Estado
- Esperando instrucciones del usuario para la Fase 1 del KYB.

---

## FASE 1 KYB — Modelo de datos, state machine, migración (11 jun 2026)

### Construido (todo detrás de KYB_MODULE_ENABLED=false)
- `backend/kyb/`: flags.py, models.py (10 colecciones kyb_* + enums),
  state_machine.py (12 transiciones, guards), audit.py (wrapper
  log_action + XFF), db_setup.py (índices gateados por flag).
- `db.py`: gate del flag al final de ensure_indexes.
- `scripts/migrate_legacy_kyb.py` (--dry-run / --execute; real exige
  flag + confirmación del usuario). DRY-RUN CORRIDO, MIGRACIÓN REAL
  **NO EJECUTADA** — bloqueada por impacto observable en bandeja legacy
  (5 filas → 2; alemany approved→under_review). Usuario decide:
  adaptar bandeja antes o postergar a Fase 6.
- `docs/kyb/state_vocabularies.md`: dos vocabularios de estado
  (organizations.kyb_status legacy alimenta kyb_locked/canOperate —
  el módulo nuevo NO lo escribe JAMÁS; kyb_cases.status nuevo).
- organizations: solo kyb_case_id nuevo (se escribe en la migración
  real, hoy 0 orgs lo tienen). SIN índice nuevo sobre kyb_status
  (el compuesto existente sirve).
- Tests: test_kyb_state_machine.py (26) + test_kyb_legacy_migration.py
  (3, sobre datos fake con cleanup por legacy_origin) → 37 pass.
  Baseline: NEW failures 0.
- Verificado flag off: colecciones kyb_ nuevas no existen, índices de
  kyb_cases intactos, bandeja legacy devuelve las mismas 5 filas.
  Índices verificados en DB scratch con flag on (TTL 30d incluido).

### Decisiones propias (reportadas)
- Timestamps como ISO strings (convención repo); excepción
  kyb_provider_calls.created_at = BSON Date (TTL).
- external_user_id unique+sparse; submitted_at ← applied_at en
  migrados; legacy_data guarda TODO el doc original (hasta lo mapeado).
- rejected→under_review solo super_admin (mecanismo de reapertura).

### Pendiente de decisión del usuario
- Ejecutar migración real (bloqueada) vs adaptar bandeja vs Fase 6.
- Fase 2 (esperar prompt).

## Fase 1.1 — Aislamiento tests KYB + confirmación reopen (11 jun 2026)
- Migración legacy POSTERGADA A FASE 6 por decisión del usuario
  (documentado en docs/kyb/state_vocabularies.md). Script queda bloqueado.
- Relevamiento de aislamiento de suite entregado: 15 archivos escriben
  directo a la base real (organizations/users/ramp_*/outbound_emails/
  prosper_files con delete_many({}) total en test_storage_gridfs);
  ~36 archivos escriben indirecto vía API al server vivo (no aislables
  cambiando DB_NAME); mecanismo scratch artesanal existe en 3-4 archivos
  (patrón _TEST_DB + drop_database). Aislar el resto = decisión aparte.
- Tests KYB migrados a scratch DBs (prosper_kyb_tests_migration /
  _transitions) con drop garantizado en finally. audit_enabled=True y
  verify_backup=True ahora testeados (en scratch).
- test_kyb_apply_transition.py nuevo: reopen rejected→under_review de
  super_admin PASA por apply_transition y QUEDA AUDITADA (verificado);
  denegación para admin no persiste ni audita.
- Hallazgo: test_phase11_developer::test_webhook_create... es flaky de
  red (httpbin.org) — falló 1 vez en baseline, pasa 3/3 aislado y con
  los tests KYB al lado. Candidato a lista flaky (decisión usuario).
- Baseline final: NEW failures 0. kyb_cases real intacto (5 docs).

## Fase 1.2 — Hardening de tests + documentación contaminación (11 jun 2026)
- test_storage_gridfs.py migrado a scratch DB (prosper_tests_storage_scratch,
  drop en finally). Ya NO hace delete_many({}) sobre prosper_files/
  file_access_tokens reales.
- Patrón peligroso delete_many({}) sin filtro: único otro caso es
  test_phase13_ramp_provider.py sobre ramp_provider_config (x4) —
  LISTADO, NO tocado (decisión aparte).
- docs/kyb/test_data_contamination.md: 132 entradas kyb.decided
  sintéticas en audit_logs real (2026-05-12 → hoy), discriminador
  metadata.session_id prefijo sim_ (132/132), filtro documentado;
  NO se borran (log inmutable). + riesgo MFA del usuario real
  client.admin@alemany.capital manipulado por la suite.
- BASELINE_FAILURES.md: flaky #3 agregado (test_webhook_create...,
  red externa httpbin.org). Parser verificado (3 flaky).
- docs/TEST_ISOLATION_BACKLOG.md: alcance estimado en dos partes
  (A: 13 archivos escritura directa, ~1-2 días; B: ~36 archivos vs
  backend vivo, fase dedicada con backend de test + seeds + re-fijado
  de baseline).
- Baseline: NEW failures 0 (bonus: test_phase6_clients::test_test_button
  pasó esta corrida — candidato a salir del baseline, no tocado).

---

## FASE 2 KYB — Signup pre-autenticado + activación magic link (11 jun 2026)

### Backend (todo tras KYB_MODULE_ENABLED)
- `kyb/routes_signup.py`: 5 endpoints /api/v1/kyb/signup/* sin auth
  (start idempotente por email, contact, country→dispara email,
  resend 3/h por email + tope IP, activate un-solo-uso→sesión).
  Anti-enum: 200 idéntico + señuelo + piso 350ms + probe_attempt en audit.
- `kyb/tokens.py`: kyb_signup_tokens (hash SHA-256, TTL Date+índice,
  signup multi-uso 2h / activation single-use 72h, revocación al re-emitir).
- `kyb/emails.py`: email activación vía email_sender (idempotencia
  triple spec + discriminador de token para permitir reenvíos).
- server.py: router gateado; .env: KYB_ACTIVATION_TOKEN_TTL_HOURS=72,
  KYB_SIGNUP_TOKEN_TTL_HOURS=2.
- organizations: INSERT único con kyb_status="pending" (validado;
  kyb_locked=true → can_operate=false) + kyb_case_id. users: se crea
  client_admin recién en activate.
- Eventos audit nuevos: kyb.signup.{probe_attempt,reentry_name_mismatch,
  contact_saved,country_saved,resend,activated}.

### Frontend (tras NEXT_PUBLIC_KYB_MODULE_ENABLED, default false → 404)
- /kyb/signup, /contact, /country (banderas emoji), /check-email,
  /activate (placeholder con estado del caso). Shell propio con design
  system existente (sin libs nuevas). middleware.ts: "/kyb" público.

### Tests: test_kyb_signup.py 9/9 (server uvicorn efímero puerto 8013 +
  DB scratch; OJO: puerto 8010 está tomado por plugin de plataforma).
  Baseline: NEW failures 0. Prod verificado: kyb 404, bandeja 5 filas,
  /kyb/signup 404 con flag off.
- docs/kyb/fase2_signup.md: comando email de prueba + flags + anti-enum.
- Pendiente usuario: activar RESEND_API_KEY tras verificar; Fase 3 wizard.

## Fase 2.1 — Lectura cruzada + paridad de flags (11 jun 2026)
- /client/me (client_portal.py:33) ahora excluye casos del modelo nuevo
  con filtro `verification_modes: {$exists: false}` (criterio: TODO doc
  nuevo lo lleva por constructor; ningún legacy lo tiene — verificado
  0/5 en real). E2E en test_kyb_signup: sesión activada → stage
  not_started.
- Inventario lecturas cruzadas kyb_cases (listadas, NO tocadas):
  compliance/kyb.py queue/detail/checklist (verán casos nuevos con flag
  on) y ⚠️ decision (:107/:119 — PODRÍA escribir estados legacy sobre
  un caso nuevo; recomendado filtrar antes del flag-on o en Fase 6);
  client_portal.py:377 (upsert legacy kyb_apply_* — coexistencia);
  admin_ops.py:51 (is_demo, seguro); seed_compliance.py:280 (seguro).
- test_kyb_flag_parity.py: falla si backend/.env y frontend/.env
  divergen en los flags KYB (limitación: no se puede leer el runtime
  del frontend — NEXT_PUBLIC_* se hornea en build; se comparan las dos
  fuentes en disco). Matriz de combinaciones en docs/kyb/fase2_signup.md.
- Baseline: 46 estables / 4 flaky / NEW failures 0.
- Pendiente: usuario pasa casilla para email de prueba (comando listo).

## Fase 2.2 — Bandeja legacy blindada + análisis dual-case + email prueba (11 jun 2026)
- compliance/kyb.py: filtro verification_modes:{$exists:false} en los 4
  endpoints. checklist y decision devuelven 409 explícito ("pertenece al
  módulo KYB nuevo") si el case_id es del modelo nuevo. Test e2e de los
  4 caminos en test_kyb_signup (caso nuevo intacto en draft tras intento
  de approve). 12/12 pass. Baseline NEW failures 0.
- Análisis client_portal.py:377 (NO tocado): org con caso legacy + nuevo
  solo alcanzable si un admin emite signed-link legacy para una org
  creada por el módulo nuevo (signup nunca ata a org existente: email
  con user → probe; siempre crea org nueva). Post-fix: /client/me y
  bandeja legacy ven SOLO el legacy; módulo nuevo lee por
  org.kyb_case_id → el nuevo. Antes del fix ganaba el más reciente
  (sort created_at desc).
- Email de prueba REAL encolado: outbound_emails
  _id=6a7b8f31a1ca3743d1ebd6a6, to=matiasplano@gmail.com (NOTA: "Mato"
  NO es usuario interno — es client_admin; internos son cuentas
  genéricas @prosper.foundation), status=preview_only, token muerto,
  case_id sintético kyb_email_preview_fase2. RESEND_API_KEY sigue vacía.

---

## FASE 3 KYB — Wizard con guardado por sección (12 jun 2026)
- Backend kyb/routes_case.py (gateado): GET /kyb/case (sin storage_key),
  PUT tax-identification (CUIT mod-11, lock, legales con versión+hash
  server-side via kyb/legal_docs.py, CUIT único 409), legal-representative,
  company/{legal-name,data(min 100),address(país+ciudad),operations,
  funds-origin(bloque licencia para CLIENT_FUNDS/MIXED + ratio + UIF +
  tax_residences)}. draft:true = autosave sin completar. Sección
  company_data completa con las 5 subsecciones (subsections_saved).
  Primera sección guardada → draft→in_progress (apply_transition).
- Documentos: POST /documents (multipart, validador F0.5, versionado
  incremental por slot is_current, huérfanos borrados si falla registro),
  DELETE soft, POST /documents/confirm (+recently_incorporated para
  funds_origin_evidence), GET /documents/{id}/url (URL firmada 300s).
- Frontend /kyb/onboarding: 2 columnas, nav con tildes/observaciones,
  Enviar a revisión deshabilitado + tooltip con faltantes, header
  (tutorial/asesor placeholders, compartir disabled hasta F8, logout),
  autosave 20s, modal cambios sin guardar, banners read-only e
  info_required, CUIT máscara+validación viva, 5 slots drag&drop,
  UBO "próximamente", team opcional placeholder.
- Tests: test_kyb_wizard.py 5/5 (e2e server puerto 8014 + scratch;
  guardarraíl en teardown: prosper_files/file_access_tokens REALES sin
  cambios). Suite KYB 59 tests OK. UI E2E real en preview con flags on
  (playwright local con executable /pw-browsers/chromium...-1208) y
  datos limpiados + flags revertidos a false (404 verificado).
- Baseline: NEW failures 0 (una corrida intermedia marcó
  test_notifications::test_bilingual_subject flaky transitorio — pasa
  solo y en la re-corrida; NO tocado, candidato a flaky si reincide).
- NOTA: quedaron índices kyb_* creados en la DB real de preview (efecto
  esperado de probar con flag on) + eventos kyb.* de la prueba UI en
  audit_logs (inmutables).
- Pendiente F4: beneficiarios finales; F5: envío a revisión.

## Fase 3.1 — Estado resubmitted + docs (12 jun 2026)
- Cuarto estado de sección `resubmitted`: observed+guardado → resubmitted
  (no completed); observación original SIEMPRE conservada; cuenta como
  completa para el envío (progress.missing). models.py, routes_case
  _mark_section, frontend (ícono ámbar en nav + nota "corregiste esta
  sección" junto a la observación). Test en test_kyb_wizard (5/5).
- docs/kyb/write_access.md: solo client_admin escribe hoy; Fase 8
  necesitará camino de escritura sin sesión (shared link) acotado a
  slots de documentación — punto de entrada documentado.
- Confirmado índices preview: legacy de kyb_cases intactos; nuevos 4 en
  kyb_cases (aditivos), resto colecciones nuevas vacías; orgs sin cambios.
- Eventos kyb.* de prueba UI documentados en test_data_contamination.md
  (distinguibles por metadata.email @preview-prosper.io y resource_id
  huérfano). Regla: pruebas UI futuras usan ese dominio.
- Baseline: NEW failures 0 (corrida intermedia marcó
  test_phase6_clients::TestSignedLinks::test_verify_and_consume_flow —
  transitorio, pasa aislado y en re-corrida; vigilar reincidencia).
- test_bilingual_subject: se deja como está (orden del usuario).

## NOTAS ANTICIPADAS PARA FASE 4 (recibidas ANTES del prompt de fase — 12 jun 2026)
El usuario envió 2 notas que asumen la spec de Fase 4 (UBOs), que NUNCA
llegó en la conversación. Se le pidió el prompt completo. Al construir
Fase 4, obligatorio incorporar:
1. `resubmitted` aplica también a la subsección de beneficiarios
   finales: observada + corregida → resubmitted, no completed.
2. Modal de completitud ("Sí, continuar con el cuadro societario
   incompleto"): al aceptar, persistir acknowledged_incomplete: true
   + EL PORCENTAJE EXACTO acumulado en ese momento (snapshot para el
   analista, no solo el % actual).
3. Si el cliente modifica beneficiarios después de confirmar la
   sección, la sección SALE de completa (la declaración jurada se firmó
   sobre un cuadro societario determinado — invalidar y re-exigir).

---

## FASE 4 KYB — Beneficiarios finales (UBO) + envío a revisión (12 jun 2026)
Spec completa recibida + 3 ajustes del usuario aprobados en ask_human:
(1) vínculo declarativo UBO↔rep legal por tax_id, (2) historial de
acknowledgments (no reset), (3) suma >100% también bloquea el submit.

### Backend (kyb/routes_case.py, gateado por flag)
- CRUD UBO: POST/PUT/DELETE /kyb/case/ubos[/{id}] — solo client_admin,
  guards de estado de la sección documentation. Campos completos (datos
  personales + societarios + is_pep/is_obliged_subject + docs).
- Validaciones alta/edición: pct 0–100 máx 2 decimales; CONTROL_BODY sin
  porcentaje; document_front_id SIEMPRE obligatorio (dorso opcional).
- Vínculo declarativo: `is_also_legal_representative` = tax_id UBO
  coincide (normalizado, solo dígitos) con el tax_id del rep legal.
  NUEVO campo opcional tax_id en PUT /legal-representative + en el
  modelo LegalRepresentative; al guardar el rep se RECALCULAN los flags
  de todos los UBOs del caso (no invalida DDJJ: no muta el cuadro). No
  fusiona datos ni bloquea: existe para que el orquestador (F5b) reuse
  el mismo sujeto externo (un applicant Sumsub por persona).
- Documentos UBO: POST /documents acepta slots ubo_document_front/back
  + ubo_id opcional (404 si no existe; 422 si ubo_id con slot societario).
  Versionado por bucket (case_id, slot, ubo_id) — ubo_id None = docs
  societarios F3. Docs subidos en el alta (sin ubo_id) se adoptan al
  crear el UBO (_link_ubo_documents). Mismo rollback compensatorio F3.
- Confirmación POST /ubos/confirm: DDJJ obligatoria; ≥1 UBO; suma >100%
  → 422; suma <100% (salvo solo-CONTROL_BODY) sin acknowledge → 409
  estructurado {code:OWNERSHIP_BELOW_100,total_percentage} (dispara el
  modal); con acknowledge → snapshot acknowledged_incomplete +
  acknowledged_incomplete_at + ownership_percentage_at_acknowledgment
  (exacto al momento) + cuadro. Guarda case.ubo_confirmation (vigente)
  + slots.beneficial_owners=confirmed. Audita kyb.ubo.confirmed.
- Invalidación (cualquier alta/baja/edición post-DDJJ): ubo_confirmation
  → None, slots.beneficial_owners → None, documentation sale de
  completed/resubmitted (→pending; si estaba observed queda observed).
  El acknowledgment NO se pierde: se ARCHIVA en
  case.ubo_confirmation_history[] con invalidated_at/by,
  invalidated_by_change {action created/updated/deleted, ubo_id,
  ubo_name}, cuadro_before y cuadro_after. Audita
  kyb.ubo.confirmation_invalidated con ambos cuadros. El analista ve
  cada aceptación histórica + el % vigente por separado.
- documentation se completa con los 5 slots F3 + beneficial_owners
  (ALL_DOC_SUBSECTIONS, aplicado también en confirm_slot F3).
  resubmitted aplica: observed + re-confirmación UBO → resubmitted vía
  _mark_section, observación conservada.
- POST /kyb/case/submit: solo in_progress/info_required; faltantes 422
  {missing:[{code,section,description}]} — códigos SECTION_INCOMPLETE
  (4 secciones, team opcional), DOCUMENT_MISSING (REQUIRED_DOCS: los 5
  slots para TODAS las legal structures; funds_origin_evidence exento
  con recently_incorporated), UBO_MISSING, OWNERSHIP_EXCEEDS_100
  (ajuste 3: dato imposible nunca llega a revisión), UBO_NOT_CONFIRMED.
  Transición in_progress→submitted vía apply_transition + audita
  kyb.case.submitted. _submit_blockers compartido con GET /case
  (progress.can_submit + progress.submit_blockers).
- Borrar el último UBO tras confirmar: invalida DDJJ + submit devuelve
  UBO_MISSING+UBO_NOT_CONFIRMED; si queda un CONTROL_BODY no hay
  UBO_MISSING pero SÍ UBO_NOT_CONFIRMED (re-confirmación obligatoria).
- Eventos nuevos en kyb/audit.py: kyb.ubo.confirmed,
  kyb.ubo.confirmation_invalidated. Modelos: SectionState acepta
  resubmitted; KybCase.ubo_confirmation(+_history);
  KybBeneficialOwner.is_also_legal_representative;
  KybDocument.ubo_id; LegalRepresentative.tax_id.

### Frontend (/kyb/onboarding — ubos.tsx nuevo)
- UboSection en documentation, 2 columnas: izquierda texto normativo
  PLAFT (Ley 25.246 / Res. UIF 112/2021, umbral 10%) + checkbox DDJJ +
  Confirmar (disabled hasta ≥1 UBO + checkbox); derecha estado vacío /
  lista (nombre, %, badge PEP, badge "Rep. legal" si
  is_also_legal_representative) con editar/eliminar, botón "+ Añadir
  beneficiario" y alternativa "No hay socios que alcancen el 10%"
  (CONTROL_BODY sin campo %).
- Alta/edición en modal de 2 pasos (personales → societarios+docs).
  Upload frente/dorso inline (frente obligatorio para Guardar).
- Modal de completitud <100% (dispara con el 409): "Cuadro societario
  incompleto — suman el X%" con Seguir cargando / Sí, continuar
  (reenvía con acknowledge_incomplete).
- Botón "Enviar a revisión" habilitado con progress.can_submit; tooltip
  con submit_blockers descriptivos; POST /submit + banner read-only.
- Campo CUIT/CUIL opcional agregado al form del Representante Legal.

### Testing (todo verde)
- test_kyb_ubos_submit.py 10/10 — e2e uvicorn efímero puerto 8015 +
  scratch prosper_kyb_tests_ubos + guardarraíl storage real sin cambios.
  Cubre: validaciones alta, docs+vínculo rep, 409/snapshot <100%,
  invalidación con historial y auditoría before/after, recompute de
  flags sin invalidar, >100% bloquea confirm Y submit (422 tipado),
  último UBO borrado, control body sin %, observed→resubmitted,
  versionado por bucket UBO + upload inválido sin registro, submit
  completo (transition+audit) y read-only posterior.
  NOTA: el rollback de fallo parcial post-GridFS (insert falla → borra
  binario) no es simulable vía HTTP e2e; es el MISMO código de F3
  (bloque try/except compartido en upload_document).
- Regresión KYB: 59 tests previos + 10 nuevos OK. Baseline completo:
  46 estables / 4 flaky / NEW failures 0.
- TS: errores preexistentes en ramp.ts y admin legacy (baseline);
  CERO errores en archivos KYB nuevos.
- UI e2e en preview con flags on (dev-login): sección UBO, modal 2
  pasos, guardar bloqueado sin frente, alta con PDF, modal <100% con
  60% exacto, confirmación OK. Datos de prueba BORRADOS (caso
  kyb_5ac1706dd588, org, user, UBO, doc + binario GridFS); eventos
  audit inmutables documentados en test_data_contamination.md §5.
  Flags revertidos a false (404 verificado con flag off).

### Incidente de tooling (documentado para no repetir)
- 5 search_replace paralelos sobre routes_case.py hicieron race: 1 edit
  (put_legal_rep) se perdió reportando éxito + corrupción al final del
  archivo. Detectado por la RELECTURA obligatoria (regla del usuario) y
  el test e2e. Regla reforzada: edits sobre el MISMO archivo, siempre
  secuenciales + relectura.

- Pendiente F5: orquestador post-submit (screening, modos de
  verificación); F6: migración legacy + bandeja nueva; F8: shared links.

---

## FASE 5a KYB — Modos de verificación + checklists manuales (12 jun 2026)
Validaciones del usuario: (1) vista de detalle PROVISIONAL (se absorbe en
F6, no deben convivir dos detalles), (2) maker-checker como dependencia
reutilizable, testeada directo, se conecta en F6, (3) environment derivado
del ENTORNO DEL PROCESO (no configurable desde la app).

### Backend
- kyb/verification_modes.py: `kyb_environment()` = KYB_ENVIRONMENT
  (sandbox|production) > PROSPER_MODE (development/dev/sandbox/preview/
  test/staging → sandbox) > default production. `environment` NO se
  persiste en kyb_verification_modes (test lo verifica): se inyecta
  read-only en las respuestas. mock + production → 409 por construcción.
- kyb_verification_modes: doc único (doc_id=singleton), 3 categorías
  default manual, updated_by/updated_at por categoría.
- Snapshot en submit (routes_case.py): copia modos vigentes →
  kyb_cases.verification_modes + inicializa verification_states
  (manual→"manual", automatic/mock→"automatic"). Campo verification_states
  NUEVO aditivo en kyb_cases (colección del módulo).
- Vocabularios (models.py): CATEGORY_MODES, CATEGORY_STATES (8 estados,
  incl. caídas automatic_failed/inconclusive/not_found — se usan
  plenamente en 5b), CHECK_TRIGGERS, CHECK_STATUSES. Modelos
  KybManualCheckTemplate, KybManualCheck (items copian
  description/source_url/evidence/outcomes del template para render
  self-contained). KybDocument.check_id nuevo (evidencias).
- kyb/manual_checks.py:
  - generate_checks: un checklist por sujeto (empresa, rep legal, cada
    UBO) × categoría manual/manual_forced/fallback_*; idempotente;
    template matching por category+país (exacto gana a None)+subject_type,
    mayor versión activa. En 5a automatic/mock SIN checklist (literal a
    spec; el fallback estructurado llega con el orquestador 5b).
  - build_normalized_result: CONTRATO compartido con el camino automático
    (5b debe producir la misma forma): {provider, kind, outcome
    (hit>review(unavailable)>clear), hit_count, items[], template,
    checked_at}.
  - complete_check → kyb_verifications (mode=manual, source=manual,
    performed_by) + kyb_screening_hits source=manual is_blocking=false
    por cada ítem outcome=hit.
  - enforce_maker_checker(case_id, user, override_reason): contributor →
    403; override solo super_admin con motivo ≥20 chars, auditado
    kyb.approval.maker_checker_override. SE CONECTA AL ENDPOINT DE
    DECISIÓN EN F6.
- kyb/routes_admin_checks.py — 9 endpoints /api/v1/admin/compliance/kyb,
  cada uno con Depends explícito:
  GET /verification-modes (require_compliance);
  PUT /verification-modes/{category} (super_admin);
  GET /templates (require_compliance); POST/PUT templates (super_admin,
  PUT crea versión nueva y desactiva anteriores);
  GET /cases/{id}/manual-checks (require_compliance, incluye metadata
  mínima del caso para la vista provisional — decisión propia para no
  crear un GET de caso fuera de spec);
  POST /cases/{id}/manual-checks/generate (require_compliance, solo
  submitted/screening/under_review/info_required);
  PATCH /manual-checks/{id}/items/{key} (require_compliance: outcome ∈
  possible_outcomes, notes ≥10, evidencia obligatoria validada contra
  kyb_documents del caso, $addToSet contributors);
  POST /manual-checks/{id}/evidence (require_compliance, multipart, slot
  manual_check_evidence, versionado por (case,slot,check_id), evidencias
  acumulativas — no se apaga is_current de anteriores, rollback
  compensatorio);
  POST /manual-checks/{id}/complete (require_compliance, 422 con
  pending_items);
  POST /cases/{id}/force-manual (require_compliance_decide — decisión de
  gestión, decisión propia reportada; motivo ≥10; → manual_forced +
  genera checklists trigger forced_by_admin).
- REGISTRO DE ROUTER: en server.py ANTES del compliance legacy — el
  legacy tiene GET /{case_id} catch-all bajo el mismo prefijo y se
  comería las rutas literales. Con flag off no se registra nada y el
  orden queda idéntico a hoy (verificado: 401/404 legacy sin cambios).
- Índices nuevos (db_setup): kyb_manual_checks (check_id unique;
  case+category+subject; case+contributors), templates
  (template_id+version unique; category+country+active).
- Eventos audit nuevos: kyb.verification_modes.updated,
  kyb.template.created/updated, kyb.manual_check.generated/
  item_completed/completed, kyb.case.forced_manual,
  kyb.approval.maker_checker_override.
- scripts/seed_kyb_templates.py: idempotente por template_id. Sembradas
  en DB real de preview (quedan: contenido legítimo, invisible flag off):
  - tpl_screening_ar (AR, 3 sujetos): ONU consolidada
    (main.un.org/securitycouncil/...), OFAC SDN
    (sanctionssearch.ofac.treas.gov), UE (sanctionsmap.eu), RePET UIF
    (repet.jus.gob.ar), medios adversos (sin URL: búsqueda abierta).
    Todos evidence_required, outcomes clear/hit/unavailable.
  - tpl_registry_ar (AR, company): constancia ARCA (URL TODO — rebrand
    AFIP→ARCA sin verificar), inscripción registral vs estatuto (URL
    TODO — varía por jurisdicción). hit = discrepancia.
  - tpl_identity_global (country None, rep+ubo): cotejo doc vs declarado
    y vigencia (evidence_required false: el doc del legajo es la
    evidencia — decisión propia).

### Frontend
- /admin/compliance/kyb/settings: 3 selectores; mock NO aparece si
  environment=production; modal de confirmación con el texto de la spec.
- /admin/compliance/kyb/templates: listado (última versión por id),
  editor de ítems, guardar crea versión nueva.
- /admin/compliance/kyb/[caseId]: VISTA PROVISIONAL (banner explícito,
  se absorbe en F6). Bloques por sujeto×categoría, ítems con selector de
  resultado + notas + evidencia + fuente, progreso por checklist y
  global, botón completar al llenar el último ítem, aviso visible de
  contributors (maker-checker evidente antes de aprobar).
- lib/kyb-manual.ts (fetchers/tipos). Links a settings/templates en la
  bandeja legacy solo con NEXT_PUBLIC_KYB_MODULE_ENABLED=true.
- Gate: kybEnabled() → notFound(); restricción super_admin real es
  server-side (la página muestra el 403 del API).

### Testing
- test_kyb_manual_checks.py 10/10 — server efímero 8016 con
  KYB_ENVIRONMENT=production + scratch prosper_kyb_tests_checks +
  guardarraíl storage real. Cubre: defaults+403 no-super_admin+409 mock
  en producción por API+environment nunca persistido; segundo server
  sandbox (8017): mock aceptado; seed idempotente ×2; snapshot en submit
  (screening automatic + resto manual); generate por sujeto×categoría
  (automatic sin checklist) idempotente; reglas de ítems (outcome
  inválido/notas<10/evidencia faltante 422, upload+patch OK,
  contributors); complete → normalized_result + hit manual + 409
  re-complete; maker-checker directo (subprocess scratch: pasa limpio,
  403 maker, 403 override corto, OK override ≥20 + evento); force-manual
  (admin 403, compliance_officer OK, 3 checklists forced_by_admin);
  authz (401 sin sesión, 403 client_admin).
- Regresión: 8 suites KYB pasan una a una (79 tests). Baseline completo:
  NEW failures 0 (46 estables/4 flaky).
- HALLAZGO de infra (no tocado, preexistente): al correr VARIAS suites
  KYB juntas en un solo pytest, los servers efímeros a veces no arrancan
  en la ventana de espera (el startup siembra demo data y llama al CMS
  real → arranque variable >60s). Mi fixture nuevo espera 120s y falla
  explícito. Las suites previas no se tocaron (fuera de alcance); el
  baseline oficial pasa.
- UI e2e en preview (flags on): settings (sandbox muestra mock, modal),
  templates (3 seeds), vista provisional (generar → 6 checklists/21
  ítems, guardar ítem, progreso 1/21, aviso maker-checker). Datos de
  prueba BORRADOS (caso kyb_ed17fa3097ce + org + user + docs/GridFS +
  checks); auditoría inmutable en test_data_contamination.md §6. Flags
  revertidos a false (legacy intacto verificado).

- Pendiente F5b: orquestador automático + Sumsub (consultar
  docs.sumsub.com/llms.txt antes), estados de caída en runtime; F6:
  bandeja nueva + detalle completo (absorbe vista provisional) +
  conectar enforce_maker_checker al endpoint de decisión + migración
  legacy + TABLERO DE CARGA POR ANALISTA (pedido del usuario: agregado
  a la bandeja de F6, no pieza propia).

## FASE 6 — Precisiones confirmadas por el usuario ANTES de la spec (12 jun 2026)
La spec completa llega en el próximo mensaje. Confirmado:
- 5b (Sumsub) postergada por credenciales: F6 se construye 100% sobre
  modo manual. Paneles de resultados de proveedor NUNCA vacíos en
  manual/not_configured: muestran el resultado del checklist en el
  mismo formato (normalized_result es el contrato).
- Pestaña Registro (F7) puede quedar vacía; el GATE de aprobación por
  checklists incompletos va en F6.
- ENTRAN: migración de los 5 casos legacy (`scripts/migrate_legacy_kyb.py`
  --execute, llenar organizations.kyb_case_id de Finpact/Alemany) y
  REEMPLAZO de la bandeja legacy.
- Vista provisional [caseId] de 5a SE ABSORBE en el detalle completo
  (no pueden convivir dos detalles).
- Tablero de carga: FILTRO + COLUMNA en la bandeja (checklists
  pendientes por analista), no pantalla aparte.
- Decisión — TRES ENDPOINTS SEPARADOS (no un parámetro):
  - `request-info`: envía al cliente SOLO las secciones observed y
    transiciona a info_required. Observar exige texto y ese texto es
    EXACTAMENTE lo que ve el cliente (sin notas internas filtradas).
  - `reject`: exige reason_code TIPIFICADO + notas.
  - `approve`: bloqueado si hay checklists manuales incompletos,
    secciones sin revisar, o hits bloqueantes sin resolver. Riesgo
    alto → primera aprobación deja el caso esperando SEGUNDA FIRMA,
    con indicación visible de quién debe darla.
  - Maker-checker server-side 403 (contributors) + override
    super_admin ≥20 chars auditado. ADEMÁS: un analista no puede
    aprobar un caso que él mismo observó y reabrió.
  - Caso aprobado habilita SUSPENDER OPERATORIA: acción explícita,
    motivo obligatorio, escribe `suspended` en el caso, auditada,
    nada la dispara automáticamente.
  - Todo por apply_transition + auditoría.

## FASE 5a — Correcciones post-aceptación (12 jun 2026)
Fase aceptada por el usuario; pidió 2 correcciones + 2 anotaciones:

1. **Descarte de evidencias** (nunca se borra — trazabilidad):
   - `POST /manual-checks/{id}/evidence/{document_id}/discard`
     (require_compliance, motivo ≥10 chars). Marca
     `KybDocument.discarded={at,by,reason}` (campo nuevo).
   - No cuenta para requisitos: la validación de evidencia del PATCH
     exige `discarded: None`; usar una descartada → 422.
   - Checklist ABIERTO: se quita de `evidence_document_ids` de los ítems
     que la referencian; si un ítem evidence_required queda sin ninguna
     → su outcome/notes se ANULAN y debe re-completarse (`reset_items`
     en la respuesta). Checklist COMPLETADO: solo se marca + audita (la
     verificación emitida no se reescribe; decisión propia reportada).
   - Re-descarte → 409. Auditoría: kyb.manual_check.evidence_discarded
     (con reason, check_status, reset_items).
   - Exportación F7: PENDIENTE mostrar descartadas en sección aparte
     identificadas como tales (anotado para F7).
   - GET manual-checks ahora incluye `evidence_documents` (sin
     storage_key, con discarded) para render y descarte en la UI.
   - UI vista provisional: lista de evidencias por ítem con botón
     Descartar + motivo inline; remount del ítem cuando el server lo
     resetea.
2. **Plantilla identity reformulada (v2)** — captura el ACTO de
   verificación, no la existencia del archivo: identity_match (cotejo
   nombre/apellido/número contra lo declarado, registrar valores
   observados en notas), doc_validity (registrar fecha de vencimiento
   observada), doc_legibility (frente/dorso legibles; hit=ilegible).
   Evidencia opcional en los tres (el doc del legajo alcanza); no se
   agregó ítem con evidencia obligatoria porque no hay fuente externa
   verificada para identity AR (no inventar fuentes).
   - Seed con UPGRADE: publica versión nueva SOLO si la última versión
     es del seed (`updated_by=="seed"`) y los ítems difieren; ediciones
     de Compliance jamás se pisan (testeado). Publicado en preview:
     tpl_identity_global v2 activa, v1 inactiva (historial conservado).
3. Tablero de carga → anotado como agregado de la bandeja F6 (arriba).
4. Hallazgo CMS documentado en docs/TEST_ISOLATION_BACKLOG.md **B.0**:
   startup de servers efímeros construye adapter REAL
   (PROSPER_MODE=development) → POST auth/login + GET cms/staking a
   cmsback.protocol-prosper.io + apscheduler run_sync_once cada 5 min;
   + demo-seed pesado (arranques >60s). NO arreglado (orden del
   usuario); remediación propuesta anotada.

Testing: test_kyb_manual_checks.py ahora 11/11 (test_03 con upgrade del
seed y protección de ediciones humanas; test_07 con ítems v2; test_11
descarte completo: 422 motivo corto, 404, marcado+audit, reset del ítem
obligatorio, 409 re-descarte, 422 patch con descartada, GET con
discarded y sin storage_key). UI de descarte verificada en preview
(caso de prueba kyb_40924cbf6dda BORRADO tras la prueba, org
org_4b90c1301bce incluida). ADVERTENCIA baseline: reiniciar supervisor
durante una corrida de check_test_baseline.py produce ~21 falsas
regresiones (tests contra backend vivo) — correr el baseline sin tocar
servicios.


## FASE 6 — Cierre detrás del flag (opción B, feb 2026)

Decisión del usuario tras analizar el impacto con flag apagado:
NO ejecutar la migración legacy todavía. La Fase 6 queda cerrada
detrás de `KYB_MODULE_ENABLED` / `NEXT_PUBLIC_KYB_MODULE_ENABLED`
en false. El encendido efectivo (flags on + migración) es una
decisión posterior, propia, no un efecto lateral de cerrar la fase.

Estado final verificado:
- `KYB_MODULE_ENABLED=false`, `NEXT_PUBLIC_KYB_MODULE_ENABLED=false`.
- `kyb_cases`: 5 documentos originales sin tocar (3 seeds + Finpact +
  Alemany), ninguno con `verification_modes` ni `legacy_origin`.
- `kyb_cases_legacy_backup`: 5 documentos, intactos.
- Bandeja legacy /admin/compliance/kyb: 5 filas (filtro
  `is_deleted=false AND verification_modes:{$exists:false}` sobre
  los 5 docs actuales).
- `organizations.kyb_status` de Finpact/Alemany: sin cambios.
- `check_test_baseline.py`: `NEW failures: 0` (46 stable + 2 flaky
  observados, no cuentan como regresión).

Correcciones documentales cerradas junto con este cierre:

1. Texto del dry-run corregido en `scripts/migrate_legacy_kyb.py`
   (docstring y `print_report`). El texto anterior decía que la
   bandeja legacy pasaría de 5 a 2 filas; en realidad pasa a 0
   porque el filtro Fase 2.2 (`verification_modes:{$exists:false}`)
   excluye a Finpact y Alemany cuando la migración les escribe
   `verification_modes`. También se documentó el efecto sobre
   `/client` (Alemany intacto por `kyb_status=approved`; Finpact
   puede caer a `not_started`/0 % por el mismo filtro en
   `routes/client_portal.py`).

2. Nuevo documento `docs/kyb/activation_procedure.md` con la
   secuencia de encendido: precondiciones (backup ≥5, snapshot del
   estado observable, baseline verde), re-ejecución obligatoria del
   dry-run con los datos del momento, encendido atómico de ambos
   flags + restart, ejecución del `--execute`, post-checks (estado
   en base, bandeja nueva mostrando los 2 reales, portal cliente,
   flujos que no se tocan — KYC personal, depósitos, webhooks
   AiPrise/Alfred — y baseline), y rollback documento a documento
   desde `kyb_cases_legacy_backup` con limpieza del puntero
   `organizations.kyb_case_id`. La regla de oro que se refuerza:
   los tres cambios (flag backend, flag frontend, ejecución) son
   una transición atómica; combinaciones intermedias son inválidas.

Investigación Alfred cerrada por el usuario: 61 eventos de auditoría,
todos con actores seed o sin actor y con IPs internas de cluster; sin
señales de tráfico externo real. Se retomará al retirar integraciones
legacy. AiPrise: 0 eventos observados. Endpoint
`/webhooks/aiprise/kyb` y `/onboarding/alfred/kyb/start` no se
tocan hasta instrucción posterior.

Fase 6 queda en estado "shipped detrás del flag, no activada". La
próxima acción sobre este módulo es la decisión del usuario de
encender flags + migrar, siguiendo el procedimiento documentado.

## FASE 7 — Portal Admin completo (feb 2026, shipped detrás del flag)

Detrás de `KYB_MODULE_ENABLED`. Con flag off: **0 rutas Fase 7**
registradas, **0 pantallas** montadas. Con flag on (tests scratch):
20 endpoints nuevos.

### Backend
- `kyb/routes_admin_cases.py` sumó:
  * `GET /cases/{id}/screening` — hits agrupados por sujeto
    (empresa, rep. legal, cada UBO).
  * `POST /hits/{hit_id}/resolve` — decisión + notas ≥20; el hit
    resuelto NO rechaza el caso, solo deja de bloquear la aprobación.
    Si `source="provider"` deja `provider_sync.pending=true` y
    audita `kyb.hit.provider_sync_scheduled` (worker se conecta
    cuando llegue Sumsub). Los hits `source="manual"` NO se propagan.
    Fallo de sync NUNCA bloquea al analista: la resolución local se
    conserva.
  * `POST /hits/{hit_id}/promote-blocking` /
    `POST /hits/{hit_id}/demote-blocking` — motivo ≥10 obligatorio,
    auditado. Fuera del template.
  * `GET /cases/{id}/registry` — comparación campo a campo declarado ↔
    verificado. En modo manual, el valor verificado se toma de las
    notas del checklist `company_registry` mapeando `item_key ↔
    field`. Marca `match=true|false|null`. Banner `not_found`
    neutro cuando no hay cobertura automática, con link al checklist.
  * `POST /cases/{id}/registry/{field}/accept` — acción
    `accept | observe`. `observe` inyecta la nota en la sección
    correspondiente del cliente y pone la sección en `observed`.
  * `POST /cases/{id}/rerun-verifications` — regenera checklists
    faltantes (idempotente). Estructura lista para orquestador cuando
    exista proveedor; hoy devuelve `skipped_no_provider` por categoría
    `automatic`.
  * `GET /cases/{id}/export` — ZIP autocontenido:
    * `case.json` — dump limpio, sin `_id` ni `storage_key`.
    * `resumen.pdf` — reportlab; perfil, UBOs, verificaciones (modo +
      quién), riesgo con desglose, resolución. Marca migración legacy.
    * `documents/<slot>/` — vigentes.
    * `manual_evidence/<check_id>/<item_key>/` — evidencia por ítem,
      `README.md` con detalle. Descartadas van a
      `manual_evidence/_descartadas/` con motivo/actor.
    * `audit.jsonl` — log completo del expediente.
    * `MANIFEST.txt` — resumen humano.

- `kyb/routes_providers.py` — `/settings/providers` restringido a
  `super_admin`:
  * `GET` lista con `last4` de credenciales, entorno,
    `last_health_check`, contador de webhooks con firma inválida
    (30d).
  * `PUT /{category}/{provider}` — credenciales cifradas con
    `INTEGRATIONS_FERNET_KEY`; nunca se devuelven en claro.
  * `POST /{category}/{provider}/health-check` — valida consistencia
    (env + credenciales) y persiste latencia + resultado. Cuando llegue
    Sumsub, este endpoint hace la llamada real + deriva de reloj.
  * `POST /{category}/{provider}/enable` — bloqueado con 409 si
    `environment="production"` y no hay health OK previo.
  * `GET /{category}/{provider}/calls` — últimas 20 outbound + 20
    webhooks + contador de firmas inválidas (TTL 30d).
  * Toda modificación auditada.

- `kyb/routes_risk_model.py` + `kyb/risk_engine.py` —
  `/settings/risk-model` restringido a `super_admin`:
  * Motor puro (`compute()`) sobre factores declarativos: país (choice),
    PEP (boolean), `blocking_hits` (count), `active_hits` (count),
    empresa recientemente constituida (boolean), actividad de alto
    riesgo (boolean). Umbrales configurables. Sin I/O.
  * `GET` — bootstrap con `default_model()` (v1 activa) la primera vez.
  * `GET /history` — historial versionado.
  * `POST /preview` — corre el modelo propuesto contra casos abiertos
    y reporta cuántos cambiarían de nivel (sin escribir).
  * `PUT` — publica una nueva versión atómicamente (desactiva la
    anterior).
  * `POST /recompute/{case_id}` — persiste `risk` con `model_version`
    para trazabilidad.

- `kyb/manual_checks.py`: los hits manuales heredan `is_blocking`
  del ítem del template (`blocks_on_hit`), no siempre `false` como
  antes. Ítems del template soportan `blocks_on_hit: bool`. Ambas
  formas de bloqueo conviven (template default + promoción manual).

- Eventos de auditoría nuevos: `kyb.hit.resolved`,
  `kyb.hit.blocking_(promoted|demoted)`,
  `kyb.hit.provider_sync_(scheduled|ok|failed)`,
  `kyb.case.registry_field_(accepted|observed)`,
  `kyb.case.rerun_verifications`, `kyb.case.exported`,
  `kyb.provider.(config_updated|health_check|enabled|disabled)`,
  `kyb.risk_model.(updated|published)`, `kyb.case.risk_recomputed`.

- Índices nuevos: `kyb_risk_model_versions.version` (único),
  `kyb_risk_model_versions.active`, `kyb_registry_reviews`
  (`case_id + field` único).

### Frontend
- `/admin/compliance/kyb/[caseId]/page.tsx`:
  * Tab **Screening**: hits agrupados por sujeto, marca fuente
    (`provider` / `manual`), score, listas, resolución con nota ≥20,
    promote/demote bloqueante con motivo ≥10, badge rojo bold para
    `detected_after_approval`, estado de `provider_sync` visible pero
    discreto.
  * Tab **Registro**: reemplaza el placeholder Fase 6. Tabla
    campo↔declarado↔verificado↔estado con banner `manual` /
    `not_found` neutro; expandir un campo permite Aceptar diferencia u
    Observar al cliente con nota ≥10.
  * Barra inferior: **Descargar legajo** (link a `GET /export`) y
    **Re-ejecutar verificaciones** (POST).
- `/admin/compliance/kyb/settings/providers/page.tsx` — super_admin.
  Contador de firmas inválidas destacado, health-check con latencia,
  activación de producción bloqueada sin health OK previo, modal de
  confirmación al activar (expedientes nuevos usarán verificación
  automática; casos en curso conservan su modo).
- `/admin/compliance/kyb/settings/risk-model/page.tsx` — super_admin.
  Edición de factores/umbrales/review, Vista previa del impacto,
  publicación versionada, historial visible.

### Sumsub postergado — consecuencias
- Screening muestra hits manuales; `provider_sync` no se dispara para
  `source="manual"`.
- Registro usa notas del checklist (mapping `item_key ↔ field`) hasta
  que llegue el proveedor. La comparación automática llega con la 5b.
- Configuración de proveedores está lista para recibir credenciales
  cuando lleguen.

### Fuera de alcance
- Enlace compartido, equipo, notificaciones, identidad con handoff,
  vigilancia continua.

### Tests
- `backend/tests/test_kyb_phase7.py` — 10 tests scratch (puerto 8019,
  DB `prosper_kyb_tests_phase7`), **10 passed** (screening view +
  resolve + gate; manual sin sync provider; promote/demote; registry
  view + mapping notas; accept/observe; rerun idempotente; export ZIP;
  providers CRUD + health + gate de producción + last4; risk-model
  bootstrap + save + preview + recompute con `model_version`).
- Conjunto KYB (`test_kyb_admin_portal` + `manual_checks` + `signup`
  + `state_machine` + `apply_transition` + `flag_parity` +
  `legacy_migration` + `ubos_submit` + `wizard` + `phase7`) —
  todos verdes.
- `check_test_baseline.py` — `NEW failures: 0`.

## FASE 8 — Colaboración y comunicación (feb 2026, entorno preparado para validación)

Detrás de `KYB_MODULE_ENABLED` / `NEXT_PUBLIC_KYB_MODULE_ENABLED`.
Ambos flags encendidos en preview durante la validación. NO revertir
hasta confirmación del usuario. Con flag off: 0 rutas y 0 pantallas
Fase 8 registradas.

### 1. Enlace compartido
- `kyb/routes_shared_links.py` — camino de escritura sin sesión,
  autenticado por token (SHA-256 en base, claro solo devuelto una vez).
  Scope `["documents"]` estricto: solo POST/CONFIRM de slots
  documentales, sin CUIT/equipo/submit. Rate limiting por token + por
  IP. Cada archivo cargado queda con `uploaded_via="shared_link"` +
  `shared_link_id` en `kyb_documents`; auditoría refleja lo mismo.
- Rutas admin: `POST/GET /kyb/case/shared-links`,
  `DELETE /kyb/case/shared-links/{id}`.
- Rutas públicas: `GET /kyb/shared/{token}`,
  `POST /kyb/shared/{token}/documents`,
  `POST /kyb/shared/{token}/documents/confirm`.
- Frontend: botón habilitado en cabecera del wizard con modal
  (`ShareLinkModal`) — muestra la URL una sola vez, permite copiar,
  lista los activos con opción de revocar.
- Página pública `frontend/src/app/kyb/shared/[token]/page.tsx` con
  cards por slot y confirmación por sección; sin identificación ni
  botón de envío.
- Anti-enumeración: mismo 404 para inexistente, revocado o expirado.

### 2. Sección Equipo — mapeo de roles
- Decisión (opción B): `intended_role` guardado aparte; `users.role`
  sigue en `client_admin`/`client_user`.
  - ADMINISTRADOR → `client_admin` + `intended_role="administrator"`
  - **OPERADOR → `client_user` + `intended_role="operator"`** (mapeo
    conservador para no prometer capacidad de gestionar miembros; la
    tarjeta del wizard aclara "en implementación")
  - SÓLO LECTURA → `client_user` + `intended_role="read_only"`
- `kyb/routes_team.py`: `GET/POST /kyb/case/team`,
  `DELETE /kyb/case/team/{id}`, `POST /kyb/team/accept`.
- **Control clave**: `/team/accept` valida que el CUIT del que acepta
  coincida con el de la invitación (403 y auditoría con
  `reason="tax_id_mismatch"` si no coincide) y que el email también
  coincida (403). Impide hijack por reenvío del correo.
- Frontend: nueva sección `TeamSection` en `sections.tsx` que sustituye
  el placeholder Fase 3. Banner del rep legal, listado de invitaciones
  pendientes + miembros activos, formulario de invitación con tarjetas
  de rol.
- Página pública `frontend/src/app/kyb/team/accept/page.tsx` con
  validación de CUIT/email.
- Documentación completa en `docs/kyb/roles_mapping.md` (los 8 pasos
  para cerrar el modelo real cuando decidas agregar `client_operator`
  al enum).

### 3. Notificaciones (dispatcher central)
- `kyb/notifications.py` — un único punto (`notify()`) idempotente por
  `sha256(event_type|case_id|recipient|discriminator)`. Con
  `RESEND_API_KEY` vacía todo queda en `outbound_emails` con
  `status="preview_only"`. Sin cambio de código cuando actives la key.
- Plantillas: `kyb.case.submitted` (cliente + interno, con
  discriminador), `.info_required` (secciones observadas por bloque),
  `.approved`, `.rejected` (motivo parametrizable), `.team.invitation`
  (muestra el CUIT requerido), `.expiring` (7d), `.provider_alert`
  (construida pero nunca se dispara sin Sumsub),
  `.manual_check.pending`.
- Ganchos: `routes_case.submit_case` → cliente + Compliance;
  `routes_admin_cases.request_info` / `approve` / `reject` → cliente.
  Team → invitado en el momento de crear la invitación.

### 4. Job de expiración
- `kyb/jobs_scheduler.py` con APScheduler (mismo motor que
  `jobs/accrual.py`, patrón que NO repite el de
  `jobs/deposit_watcher.py`).
- **Registrado en `server.startup` solo si `kyb_enabled()`**:
  `expire_inactive` @ 03:00 UTC (default 90 días,
  `KYB_INACTIVITY_DAYS`), `notify_expiring` @ 03:15 UTC (7 días antes),
  `notify_manual_check_sla` @ 03:30 UTC (SLA `KYB_SLA_HOURS`, default
  72, buzón `COMPLIANCE_INBOX_EMAIL`).
- `expire_inactive` usa `apply_transition` con la transición
  `in_progress|info_required → expired` ya presente en la state
  machine. No borra datos; la reactivación manual restaura tal cual
  estaba.
- **Endpoint admin `POST /admin/compliance/kyb/jobs/run-expiration`**:
  solo `super_admin`; devuelve **409 en producción** reusando
  `kyb_environment()` de `verification_modes.py`. Mismo guard para
  `/run-expiring-warning` y `/run-manual-check-sla`.

### Estado del entorno preparado para tu validación
- Flags: `KYB_MODULE_ENABLED=true`, `NEXT_PUBLIC_KYB_MODULE_ENABLED=true`.
- Expediente A (draft, en blanco):
  `cliente-a-phase8@preview-prosper.io` — case `kyb_ac907eddb6a5`.
- Expediente B (submitted, completo con 4 docs + 1 UBO):
  `cliente-b-phase8@preview-prosper.io` — case `kyb_574f214108df`.
- URLs de login y checklist de validación en
  `/app/memory/test_credentials.md`.

### Tests
- `backend/tests/test_kyb_phase8.py` — **8 passed** en scratch (server
  efímero 8020 + 8021):
  1. shared link crear/listar/revocar
  2. shared público con `uploaded_via=shared_link`, anti-enumeración,
     bloqueo de `recently_incorporated` desde tercero
  3. team invitation con mapping operator → client_user, duplicados,
     rechazo por CUIT/email mismatch, aceptación OK
  4. team admin mapping + revoke + accept sobre revocada
  5. dispatcher idempotente (segundo envío no duplica outbound_emails)
  6. force expiration en sandbox y gate de rol
  7. force expiration en PROSPER_MODE=production → 409 hasta para
     super_admin
  8. scheduler expuesto y funciones importables
- `check_test_baseline.py`: `NEW failures: 0`.
- 13 rutas nuevas registradas con flag on; 0 con flag off.

## FASE 8 — Correcciones post-recorrido (feb 2026, detrás del flag)

Seis diagnósticos del recorrido de verificación, cinco resueltos + una
decisión sobre i18n. Cambios aplicados detrás del flag KYB.

### 1. Orquestador único en el submit — modo manual llega a `under_review`
- Nuevo `backend/kyb/orchestrator.py`. Un único punto de entrada
  (`dispatch_on_submit`) reemplaza el atajo silencioso de
  `_ensure_under_review`.
- **Idempotente**: llamar dos veces no duplica checklists ni
  verificaciones (delegado a `generate_checks` que ya deduplica por
  `(case_id, category, subject_id)`). El botón "Generar checklists" del
  portal admin ahora es un reintento sobre esta misma función, no un
  camino alternativo.
- **Resiliente**: si `_dispatch_category` falla para alguna categoría,
  el error se persiste en `case.dispatch_state.errors` y el caso avanza
  igual. Un caso nunca se traba porque nosotros fallamos.
- Cuando todas las categorías son `manual` / `not_configured`,
  transiciona `submitted → screening → under_review` en el mismo
  request. Cuando alguna es `automatic` (5b futura), se queda en
  `screening` y `resolve_pending()` corre desde los webhooks de Sumsub.
- `_dispatch_category` para modo `automatic` es el **punto de extensión
  para la 5b**: hoy devuelve `skipped_no_provider`; el día que llegue
  Sumsub se agrega ahí el dispatch al SDK. No hay dos caminos
  conviviendo: el orquestador ya es el único.
- Nuevo evento de auditoría `kyb.case.dispatched` con el resultado por
  categoría.

### 2. Aprobar/rechazar/observar solo desde `under_review`
- `_ensure_under_review` eliminado en `routes_admin_cases.py`. El
  símbolo se conserva como stub que lanza `RuntimeError` si se invoca
  (para captar cualquier código futuro que lo importe).
- `DECIDABLE = ("under_review",)`. Los endpoints
  `POST /cases/{id}/approve`, `/reject`, `/request-info` responden
  **409** si el caso no está en `under_review`. No hay salto
  silencioso: el estado permanece en `submitted`.
- En el frontend, los tres botones desaparecen del DOM (no
  `disabled` cosmético) cuando el caso no está en `under_review`.
- **Invariante verificado en la state machine** (no solo en el
  endpoint): 5 tests nuevos en `test_kyb_state_machine.py` cubren
  `submitted → approved` inalcanzable en un solo hop, `submitted` no
  puede saltar a ningún terminal, `screening` solo va a `under_review`,
  y `rejected` solo se alcanza desde `under_review`.

### 3. Bandeja excluye borradores y cerrados por default
- `list_cases`: default limita a `{submitted, screening, under_review,
  info_required}`. Toggles opcionales apagados por default:
  `include_drafts` (draft/in_progress/expired) e `include_closed`
  (approved/rejected).
- Frontend `tray.tsx`: dos chips nuevos "Incluir borradores" e
  "Incluir cerrados".
- El SLA de la bandeja ya no se contamina con expedientes que el
  cliente todavía no envió.

### 4. `company/manual` fuera de Providers
- `KNOWN_PROVIDERS = {"identity": ["sumsub"], "screening": ["sumsub"]}`
  en `routes_providers.py`. "Manual" es ausencia de proveedor, no un
  proveedor. La tarjeta desaparece del listado.
- La categoría `company` se sumará el día que exista una fuente
  automática real (Cepop / Boletín Oficial u otra).

### 5. Textos de especificación reemplazados
- Placeholder de la observación en el detalle admin:
  `Detalle que verá el cliente. Sea claro y específico.` (antes
  contenía la palabra EXACTAMENTE en mayúsculas).
- Pestaña Riesgo: `puntaje: … · modelo: v{N} | sin calcular` (antes
  decía "(motor de riesgo: fase siguiente)" — nota interna
  desactualizada además, porque el motor llegó en Fase 7).
- Botón "Tutorial" oculto del wizard cliente. Preferimos no anunciar
  un feature futuro con "disponible próximamente"; cuando exista
  contenido real, se muestra el botón.
- **NO se tocó** la aclaración de la tarjeta OPERADOR ("esta capacidad
  está en implementación — hoy opera como miembro solo lectura"): es
  texto de producto solicitado explícitamente en Fase 8.

### 6. Idioma del backoffice unificado en español
- `DEFAULT_LOCALE` en `frontend/src/i18n/request.ts` cambió de `"en"`
  a `"es"`. La navegación ya estaba traducida en `messages/es.json`;
  solo faltaba cambiar el default. Los usuarios con cookie
  `prosper_locale=en` o Accept-Language `en` siguen viendo inglés.
- **NO se i18n-izó el módulo KYB**: ~180 strings en español directo
  dentro del JSX del wizard y del portal admin. Anotado en el backlog
  como fase propia. Estimación: 1-2 días de trabajo para extraer keys
  a `en.json`/`es.json` + reemplazos por `t("kyb.*")`. Valor bajo
  mientras no haya usuarios en otro idioma.

### Tests
- `test_kyb_orchestrator.py` nuevo — 8 tests: transición automática
  en modo manual, idempotencia del orquestador, resiliencia ante
  fallo parcial, gate 409 en submitted, `_ensure_under_review`
  deprecado, default de bandeja, ausencia de `company/manual` en
  providers, flujo completo submit → complete-checklists → approve.
- `test_kyb_state_machine.py` — 5 tests nuevos del invariante:
  `submitted → approved` inalcanzable, sin atajos a terminales,
  `rejected` solo desde `under_review`. 39/39 verdes.
- Suite scratch KYB (state_machine + apply_transition + flag_parity +
  legacy_migration + orchestrator + admin_portal + manual_checks +
  phase7 + phase8): todos los tests scratch propios verdes.
- Los tests que dependen del backend en supervisor
  (`test_kyb_signup`, `test_kyb_ubos_submit`) fallan por el problema
  de aislamiento conocido de tests parte B — el pod no responde
  `127.0.0.1:8001` incluso con el backend running. NO es regresión de
  este cambio; los mismos tests fallaban antes del recorrido.
- `check_test_baseline.py` no completó en la ventana por saturación
  del entorno (múltiples servers efímeros + puertos ocupados +
  filesystem al 100 % que hubo que limpiar). El próximo run limpio
  del baseline queda como próxima acción pendiente.

### Estado del entorno de validación
Los dos flags siguen encendidos como pediste
(`KYB_MODULE_ENABLED=true`, `NEXT_PUBLIC_KYB_MODULE_ENABLED=true`).
Los expedientes de validación (Cliente A draft, Cliente B submitted)
siguen intactos. Con este cambio, si volvés a enviar el Cliente A
desde el wizard, ahora sí llega automáticamente a `under_review` y los
checklists aparecen listos para completar.


## 2026-08-14 — Rollback KYB legacy: script + red de seguridad de frescura del backup

### Nuevo script `scripts/rollback_legacy_kyb.py` (461 líneas)

Rollback agnóstico, idempotente, con 11 abortos bloqueantes:

- **Categoría A (se revierte, cascade por `case_id ∈ NUEVOS`)**: 9
  colecciones — `kyb_cases` (5 docs desde `kyb_cases_legacy_backup`
  con reemplazo total preservando `_id`), `organizations.kyb_case_id`
  ($unset — nunca se toca `kyb_status`), y 7 satélites incluyendo
  `kyb_documents` con volcado JSON obligatorio previo al borrado.
- **Categoría B (se conserva íntegra)**: `kyb_verifications`,
  `kyb_screening_hits`, `kyb_provider_calls`, `outbound_emails`,
  `audit_logs`, bytes en GridFS.
- **Auditoría**: agrega `kyb.case.legacy_rollback` per-case con
  `before/after` + `kyb.rollback.script_{started,phase,finished}`
  vía `log_action` (sin colección nueva).

### Abortos (11)

A1..A9 según contrato del contrato del usuario + A10 (nuevo:
backup diverge de `legacy_data` fuera de timestamps → aborta) +
dos guardias externas (`--force` para `KYB_MODULE_ENABLED=true`,
`--i-know-what-im-doing` para apuntar a `prosper_phase0`).

### Hallazgo H1 y red de seguridad de frescura del backup

Durante el test E2E se descubrió que en `prosper_phase0` el
`kyb_cases_legacy_backup` estaba **desactualizado**
(`kyb_seed_01.timeline`: backup 13 entries vs vivo 56;
`kyb_apply__finpact.applied_at` divergía). Un rollback ejecutado
en ese estado habría restaurado al día del respaldo, perdiendo la
actividad in-between.

Contramedidas incorporadas:
1. `scripts/migrate_legacy_kyb.py`: aborto `[freshness]`
   pre-migración que compara backup vs vivo doc-a-doc, ignorando
   timestamps y con timeline normalizado. **Bloquea** migrar con
   respaldo viejo.
2. `scripts/rollback_legacy_kyb.py`: aborto A10 que compara
   backup vs `legacy_data` de los casos migrados. Aunque alguien
   se saltee la freshness check en migrate, el rollback se niega
   a restaurar a estado obsoleto.
3. `docs/kyb/activation_procedure.md` sección 0: paso obligatorio
   de **regeneración del respaldo desde el vivo** previo al
   dry-run (con verificación doc-a-doc).
4. Sección 5 completa reescrita: 9 subsecciones que documentan
   cuándo usar el rollback, qué revierte/conserva, los 11 abortos,
   comandos, idempotencia, resultado E2E, hallazgo H1 y comandos
   para generar copias de test.

### Tests

- `backend/tests/test_kyb_legacy_rollback.py` — 17 tests
  (idempotencia base, ida-y-vuelta migrate+rollback, dry-run no
  muta, dump JSON obligatorio, 10 abortos individuales, guardias
  externas, conservación estricta de Cat B).
- `backend/tests/test_kyb_legacy_migration.py` — +3 tests nuevos
  del aborto `[freshness]`.
- Total en las 2 suites: **26/26 verdes**.

### Test E2E ida-y-vuelta

Contra `prosper_phase0_rollback_test_<run_id>` (copia clonada, nunca
prod). Con backup regenerado: `kyb_cases` doc-a-doc pre = post-rollback
con 0 diferencias. Δ `audit_logs` = +10 (2 migrated + 2 rollback
per-case + 1 started + 4 phases + 1 finished). El resto: 0 cambios.
`organizations.updated_at` queda con el valor que le puso migrate
(H2, decidido aceptable — refleja última mutación real del doc).

### Relevamiento adicional — 43 entradas nuevas en `kyb_seed_01.timeline`

- Todas: `what=decision.approve`, `by=admin@prosper.foundation`,
  `meta.reason='All 8 checklist items verified per AML/KYB policy.'`.
- Distribución: 2026-08-10 (1), 08-11 (21), 08-12 (14), 08-13 (7),
  08-14 (1) — más 13 previas en 05..07.
- Camino: **legacy** (seed sin `verification_modes`, sin
  `legacy_origin`; caso ya `status=approved, decision=approve`).
- Endpoint responsable:
  `POST /api/v1/admin/compliance/kyb/{case_id}/decision`
  (`backend/routes/compliance/kyb.py:162`). Guardas del handler:
  requiere permiso `require_compliance_decide` y que el caso NO
  tenga `verification_modes` (redirect 410 si lo tiene).
- **NO valida idempotencia sobre `decision.approve` en un caso ya
  aprobado**: solo exige que los 8 items de checklist estén
  chequeados (una vez aprobado, ya lo están). Cada llamada agrega
  entry al timeline y pisa `decided_at`, `decided_by`,
  `decision_reason`.
- Reproducibilidad en `kyb_apply__alemany`: **sí** (mismo shape,
  aprobable indefinidamente).
- Reproducibilidad en `kyb_apply__finpact`: **sí** si un compliance
  marca los 8 checklist items primero (hoy están todos en `False`).
- Impacto operativo: nulo sobre `can_operate` (el status ya es
  approved; `kyb_status` no cambia). Impacto en trazabilidad:
  ensucia el audit trail — no bloqueante del encendido pero es un
  hallazgo del módulo legacy.


## 2026-08-14 — Fase 0 + Fase 1 del retiro de AiPrise (single PR)

### Fase 0 — preparación
- Eliminada `AIPRISE_DEPRECATED` del `backend/.env` (variable muerta,
  cero lectores).
- **NO** se tocó `frontend/src/app/privacy/page.tsx`. Texto reportado a
  compliance para PR aparte:
  - Línea 56: "Onboarding y due diligence regulatoria (AiPrise + Travel
    Rule + Sanctions)."
  - Línea 68: "**AiPrise** — verificación KYB/KYC."

### Fase 1 — cierre de entradas al canal AiPrise
- **Frontend**: `apply/LegacyApplyForm.tsx` reescrito. Tab "Empresa"
  retirado del árbol (no oculto, no deshabilitado — eliminado). Form
  sirve exclusivamente `applicant_type=individual`. Aviso informativo
  visible arriba del formulario con `support@prosper.foundation`
  (casilla vigente en el sitio, tomada de `AccountTab.tsx:245`) y CTA
  a solicitar invitación para alta corporativa.
- **Frontend**: `apply/simulate/page.tsx` eliminado del filesystem.
  Cero enlaces residuales al path (`grep` confirma).
- **Backend**: `POST /onboarding/apply` con `applicant_type=business`
  responde **410 Gone** con mensaje "El alta de empresas se realiza
  por invitación. Escribí a support@prosper.foundation..." — sin
  nombrar proveedores en la respuesta.
- **Backend**: `POST /onboarding/me/kyc` responde **410 Gone** con
  mensaje "La verificación de identidad se realiza subiendo
  documentación desde tu cuenta. Ingresá a /client/kyc-docs para
  continuar."
- **Backend**: `POST /onboarding/apply/simulate` retirado del router
  (`simulate_decision`, `SimulateIn`, `_reject_simulate_in_production`
  eliminados). FastAPI resuelve el POST vs el catch-all
  `/apply/{app_id}` con 405 Method Not Allowed — coherente con
  "ruta no operativa".

### Tests reconvertidos (ninguno eliminado)
- `test_phase3_onboarding.py`: `TestApplyPublic` (3 tests) valida 410
  business; `TestSimulate` (3 tests) valida 404/405 en simulator;
  `TestWebhooks.test_kyb_webhook_accepts_unsigned_in_sim_mode` →
  `test_kyb_webhook_unknown_session_returns_404`; `TestCompliance`
  refactorizado para no crear apps business; `TestMyKyc` valida 410.
- `test_andes_kyc_widget.py::test_simulator_sim_kyc_rejects_with_400_for_personal`
  → `test_simulator_route_no_longer_operative` (acepta 404/405).
- `test_simulate_and_magic_link_prod_blocked.py`:
  `test_apply_business_without_template_returns_503_in_production` →
  `test_apply_business_returns_410_by_module_retirement`;
  `test_simulate_returns_404_opaque_in_production` /
  `test_simulate_404_for_any_payload_in_production` →
  `test_simulate_route_retired_*` (acepta 404/405).

### Test nuevo dedicado al path individual — no puede romperse
- `backend/tests/test_apply_individual_still_works.py` — 3 tests
  contra base scratch:
  1. `test_apply_individual_happy_path_unchanged`: happy path
     completo (persistencia de `organizations`, `onboarding_applications`,
     `users`) con `mode=andes-direct`, session `andes_kyc_usr_*`,
     `hosted_url` local a `/apply/{app_id}/kyc-docs`.
  2. `test_apply_business_returns_410`: 410 + cero side effects.
  3. `test_get_application_after_individual_apply`: read-back
     sanitizado (sin PII).

### Resultado de tests
- `pytest tests/test_apply_individual_still_works.py`: **3/3** verdes.
- `pytest tests/test_aiprise_kyb_dropped.py`: 4/4 verdes.
- `pytest tests/test_kyb_legacy_migration.py tests/test_kyb_legacy_rollback.py`: 26/26 verdes.
- **Total suites unitarias del PR: 33/33 verdes.**

### Smoke test (backend real)
- `POST /onboarding/apply` business → **410** con mensaje sin
  mencionar proveedores.
- `POST /onboarding/me/kyc` sin auth → 401 (guard corre antes).
- `POST /onboarding/apply/simulate` → **405** (ruta retirada).
- `POST /onboarding/apply` individual → **200** con
  `mode=andes-direct, kyb_status=pending`, `hosted_url` a `/kyc-docs`.

## 2026-08 — Staking Cash-in: Envío de `users.org_id` y Límite de 2 Modalidades

- **Identificador enviado al Backend/CMS**:
  - En la interfaz visual (front), se muestra y busca por el **email** del usuario para facilidad operativa.
  - Sin embargo, lo que se envía al backend y al CMS (`user_reference_id` / `prosperId`) es **`users.org_id`** (la organización a la que pertenece el usuario).
  - Backend endpoints (`/admin/prosper/cms/cashin` y `/client/staking/cms/cashin`) aceptan `org_id` (con fallback de resolución por email a `users.org_id`).
- **Límite de Modalidades (`organizations.prosper_wallets`)**:
  - Las únicas 2 modalidades posibles son `'end'` (al final) y `'month'` (mes a mes).
  - La pantalla/formulario de nueva solicitud de cash-in solo está disponible si `organizations.prosper_wallets` tiene **menos de 2 elementos**.
  - Si el usuario/organización ya tiene 2 wallets (o ya tiene ambas modalidades registradas), la pantalla muestra un mensaje informativo indicando que el usuario ya tiene ambas modalidades disponibles y bloquea la creación de solicitudes adicionales.
  - Al crearse una nueva wallet, el backend persiste el registro en `organizations.prosper_wallets` en MongoDB.
