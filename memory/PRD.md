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
5 sub-pages under `/admin/operations`:
- `/transactions` — Global ledger with type/status/date chips, search,
  only-errors toggle, pagination, CSV export, row click → lifecycle.
- `/transactions/[id]` — Stripe-style **vertical lifecycle timeline** with
  6 steps (subscribe) or 4 steps (redeem). Step pills navigation. Collapsible
  JSON payload viewers. Super_admin retry button on error/pending steps.
- `/funds` — Quirón PyMEs fund header (NAV/supply/invested/treasury) · 90d
  NAV chart · Stellar accounts table with copy-to-clipboard + explorer link ·
  3-LED upstream semaphore (Enabled/Reachable/Authenticated).
- `/by-client` — Per-org stats with success/failure rates + 30d sparkline +
  drill-down `/by-client/[id]` for that org's tx list.
- `/volume-by-client` — Treemap + table with 24h/7d/30d/total/delta% + share bar.
Seed enriched with realistic 6-step lifecycle data (Onramp Alfred → USDC
conversion → Prosper trigger → Mint → Position → Webhook outbound), ~20% of
subscribes intentionally fail at the webhook step.
**20+1 pytest green** + full frontend data-testid coverage.

## Security hardening (2026-05-12)
- `@prosper.foundation` auto-provisioned accounts now default to **admin**
  (not super_admin). super_admin only via explicit seed.

## 🟠 Sprint B — blocked on user input
- **AiPrise templates + webhook secret** — to flip onboarding from
  simulated → live.
- **Resend** — `RESEND_API_KEY` + verified sender domain.
- **Stellar upstream** — preview egress block on `horizon.stellar.org`.

## 🟢 Small follow-ups (P3)
- Phase 2: index nav_snapshots BEFORE insert_many.
- Phase 2: `$lookup` instead of per-row org lookup in recent_activity.
- Phase 3 ops: pad sparkline zeros so all sparklines share x-scale.
- Phase 3 ops: guard `retry-step` to only flip steps currently error|pending.
- Phase 3 ops: disambiguate the many "TEST Holdings" leftover orgs.
- Phase 3 ops: implement real Stellar /accounts probe once egress opens.

## 🟡 Phase 4 — Treasury & Funds (next P1)
Real subscribe/redeem flows · NAV publication · fee accruals · reconciliation.

## Notes
- Old codebase at `/app/legacy/` — do not import from there.
- Test credentials: `/app/memory/test_credentials.md`.
