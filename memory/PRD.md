# Prosper Platform — PRD & Status

> Platform rebuilt from scratch on 2026-05-12 following the user's PRD. Legacy
> codebase preserved at `/app/legacy/`.

## Stack
- **pnpm monorepo**: `apps/admin` (Next.js 14 App Router), backend FastAPI async,
  shared `packages/ui` + `packages/types`. MongoDB via motor.
- **Auth**: passwordless OTP (4-digit) + JWT httpOnly cookie (7d). Dev magic-link
  at `/api/v1/auth/dev-login` (auto-disables when `RESEND_API_KEY` is set).
- **Brand**: Prosper official palette (`#2563FF` primary, `#0B0F19` ink, `#22C55E`
  success, `#F2F6FF` surface). 4-leaf clover logo + lowercase wordmark.

## ✅ Phase 0 — Bootstrap (2026-05-12)
Monorepo, OTP auth, design system, app shell with env switcher.

## ✅ Phase 1 — Data model & multi-tenancy (2026-05-12)
Pydantic + TS types, RBAC, org scoping, immutable audit log, seed CLI.
Seeded users: super_admin, admin (ops), compliance_officer, finance,
2× client_admin.

## ✅ Phase 2 — Admin Home + Sprint A (2026-05-12)
6 KPI tiles · NAV/Volume/Revenue charts · Top Clients · Operations Queue (WS) ·
Recent Activity · Export PDF · 7d/30d/90d range. Backend in
`/backend/routes/dashboard/`. 32/32 pytest green.

## ✅ Phase 3 — Onboarding KYB/KYC via AiPrise (2026-05-12)
Public `/apply` form · `/apply/simulate` (dev fallback) · `/apply/status` ·
`/admin/compliance` with KYB/KYC tabs, review modal, decision flow. HMAC
webhook receivers. Live/simulated mode driven by env vars. 22/22 pytest green.

## ✅ Phase 3 — Operations module (2026-05-12)
5 sub-pages under `/admin/operations`: transactions ledger, lifecycle timeline,
funds, by-client, volume-by-client. 20+1 pytest green + full data-testid coverage.

## ✅ Phase 4 — Admin Portal Negocio / Business module (2026-05-13)
4 sub-pages under `/admin/business`:
- `/clients` — Master client list with volume, revenue, APR, yield 30d,
  sparkline. **Configurable columns dropdown** (10 options, persists in
  `localStorage['prosper.biz.clients.cols.v1']`). Type chips, CSV export,
  Executive PDF export.
- `/revenue` — Revenue summary (Total / MTD MoM / YTD YoY) · donut breakdown ·
  monthly stacked bar (12m) · top-10 clients horizontal bar · MoM comparison
  table by concept.
- `/yield` — Yield-per-client table with platform-APR benchmark.
  **"Mostrar fees implícitos" toggle** that reveals Gross APR, Fee drag %,
  and 30d USD breakdown of management + performance + spread fees Prosper
  collects.
- `/cohorts` — Cohort analysis grouping orgs by first-subscribe month.
  Retention bars, retention line chart, KPI tiles, full data table.
  Range selector 6m/12m/24m.

Backend in `/backend/routes/business.py` + fee logic in `/backend/fees.py`
(daily-prorated 1% mgmt, 10% performance, 0.5% onramp / 0.3% offramp spreads).
Executive PDF generator in
`/frontend/src/components/business/ExecutivePdfButton.tsx`.

**Testing — iteration 8**: 24/24 backend pytest green · 23/24 Playwright
(1 false negative — verified working). RBAC enforced (client_admin → 403 on
all 9 endpoints). See `/app/test_reports/iteration_8.json`.

## Security hardening (2026-05-12)
- `@prosper.foundation` auto-provisioned accounts default to **admin**
  (not super_admin). super_admin only via explicit seed.

## 🟠 Sprint B — blocked on user input
- **AiPrise templates + webhook secret** — to flip onboarding from
  simulated → live.
- **Resend** — `RESEND_API_KEY` + verified sender domain.
- **Stellar upstream** — preview egress block on `horizon.stellar.org`.

## 🟢 Technical backlog (P2)
- Phase 2: unique index on `nav_snapshots` BEFORE `insert_many` (multi-replica).
- Phase 2: `$lookup` instead of per-row org lookup in `recent_activity.py`.
- Phase 2: real cron snapshot/day for NAV (currently only backfill on startup).
- Phase 3 ops: pad sparkline zeros so all sparklines share x-scale.
- Phase 3 ops: guard `retry-step` to only flip steps currently error|pending.
- Phase 3 ops: disambiguate the many "TEST Holdings" leftover orgs.
- Phase 3 ops: implement real Stellar /accounts probe once egress opens.
- Phase 4: split `routes/business.py` into clients/revenue/yield/cohorts as
  module grows (~500 lines, still under 700 threshold).
- Phase 4: tighten `list_clients` status filter (only single-value 'active'
  branch is precise currently).

## 🟡 Phase 5 — Treasury & Funds (next P1)
Real subscribe/redeem flows · NAV publication · fee accruals · reconciliation.

## 🟡 Future phases (per original PRD)
- Regulatory reporting module.
- Client portal (self-service subscribe / redeem / statements).
- Mobile companion (probably P3).

## Notes
- Old codebase at `/app/legacy/` — do not import from there.
- Test credentials: `/app/memory/test_credentials.md`.
- Latest test report: `/app/test_reports/iteration_8.json`.
