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

## 🟠 Sprint B — blocked on user input
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
- Phase 5: SAR/STR currently descargan JSON. Migrar a PDF formal con
  `@react-pdf/renderer` (similar a Executive PDF de Negocio).
- Phase 5: client-side RBAC guard en ComplianceLayout — actualmente
  client_admin ve pantallas vacías (backend rechaza con 403, pero UX engaña).
- Phase 5: tighten SEV_TONE types — importar `Tone` desde Badge.tsx para que
  TS detecte mismatch de tonos en compile-time.
- Phase 5: WebSocket o push real-time para alertas critical (actualmente
  bell-icon polling 30s).

## 🟡 Phase 6 — Treasury & Funds (next P1)
Real subscribe/redeem flows · NAV publication · fee accruals · reconciliation.

## 🟡 Future (per original PRD)
- Sumsub Web SDK integration en `/apply` (continuar prompt 1 de Fase 5).
- Audit log viewer `/admin/compliance/audit` (continuar prompt 2 de Fase 5).
- Push notifications API para alertas critical (continuar prompt 3 de Fase 5).
- Regulatory reporting module formal.
- Client portal (self-service subscribe / redeem / statements).
- Mobile companion (P3).

## Notes
- Old codebase at `/app/legacy/` — do not import from there.
- Test credentials: `/app/memory/test_credentials.md`.
- Latest test report: `/app/test_reports/iteration_9.json`.
