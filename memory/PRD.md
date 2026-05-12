# Prosper Platform — PRD & Status

> ⚠️ Phase 0 reset (2026-05-12) — the platform was rebuilt from scratch following
> the user's `01_PRD_Prosper_Plataforma.md`. The previous CRA demo lives in
> `/app/legacy/` for reference only.

## What is the platform
Regulated tokenized-yield platform on Stellar with two portals (Admin internal
staff + Client/Partner) + a public Developer Portal. Built in 12 phases.

## ✅ Phase 0 — Bootstrap (2026-05-12)
- pnpm monorepo: `apps/api` (FastAPI async), `apps/admin` (Next.js 14 App
  Router), `packages/ui`, `packages/types`, docker-compose, CI.
- Passwordless OTP auth (email → 4-digit code → JWT httpOnly cookie, 7d).
- Design system: IBM Plex Sans/Mono + Chivo; tokens for light/dark.
- App shell with env switcher (Sandbox/Production), alerts bell, avatar menu.

## ✅ Phase 1 — Data model & multi-tenancy (2026-05-12)
- Pydantic + TS shared types · RBAC roles · Org-scoping middleware ·
  Impersonation header · Immutable audit log · Idempotent seed CLI.

## ✅ Phase 2 — Admin Home / KPIs + Sprint A (2026-05-12)
- 6 KPI tiles with tooltips · NAV (real snapshots) / Volume / Revenue charts ·
  Top Clients table · Operations Queue (WebSocket + polling fallback) ·
  Recent Activity feed · Export PDF · 7d/30d/90d range switcher.
- Backend split under `/app/backend/routes/dashboard/`.
- 32/32 pytest cases green.

## ✅ Phase 3 — Onboarding (KYB/KYC via AiPrise) (2026-05-12)

### Integration (`/app/backend/integrations/aiprise.py`)
- Async httpx client to `api-sandbox.aiprise.com` / `api.aiprise.com`.
- Env-driven mode (`AIPRISE_ENVIRONMENT=sandbox|production`).
- **Simulated fallback**: when `AIPRISE_KYB_TEMPLATE_ID` /
  `AIPRISE_KYC_TEMPLATE_ID` are empty, the client returns a `/apply/simulate`
  hosted_url so the end-to-end flow is exercisable without real templates.
  Flipping to LIVE = just paste the template IDs into `/app/backend/.env`.
- HMAC-SHA256 webhook signature verification (`X-HMAC-Signature`).

### Backend endpoints (all under `/api/v1`)
- **Public**: `POST /onboarding/apply`, `GET /onboarding/apply/{id}`,
  `POST /onboarding/apply/simulate` (dev-only sim driver).
- **Client user**: `POST /onboarding/me/kyc`.
- **Webhooks** (HMAC-verified): `POST /webhooks/aiprise/kyb`,
  `POST /webhooks/aiprise/kyc`.
- **Compliance** (super_admin / admin / compliance_officer):
  `GET /compliance/summary`, `GET /compliance/applications[?status=]`,
  `GET /compliance/applications/{id}`,
  `POST /compliance/applications/{id}/decide`,
  `GET /compliance/kyc-cases[?status=]`,
  `POST /compliance/kyc-cases/{user_id}/decide`.
- Reverse-proxy-aware `_public_base_url` (X-Forwarded-Host/Proto) so the
  hosted_url + AiPrise callback embed the public preview origin.

### Frontend
- `/apply` — public 4-section form (Company · Contact · UBOs · Use case) →
  POST `/onboarding/apply` → redirect to `hosted_url` (real AiPrise or
  `/apply/simulate`).
- `/apply/simulate` — dev-only outcome picker (Approve / Hold / Reject) +
  prominent `DEV SIM` badge.
- `/apply/status?app_id=` — public live-polling status page with green/yellow/
  red icon by decision.
- `/admin/compliance` — 4 stat tiles + KYB/KYC tabs. KYB shows DataTable +
  review modal with full applicant data, UBO breakdown, decision note,
  3-button decision row. KYC shows inline Approve/Reject actions.
- Middleware now whitelists `/apply` for public access.

### Tests
- 22 new pytest cases (Phase 3) — all green.
- Total backend: 58/58 (after skipping the pre-existing test_phase1 module
  path quirk).
- Frontend E2E confirmed: `/apply → submit → /apply/simulate → Approve →
  /apply/status (green Approved)` works end-to-end on the preview URL.

## 🟢 Pending follow-ups (small, P3)
- Phase 2 — multi-replica safety: create `nav_snapshots` unique index BEFORE
  `insert_many` in backfill.
- Phase 2 — `recent_activity.py`: replace per-row org lookup with `$lookup`.
- Phase 3 — `_apply_kyc_decision`: persist `kyc_status='pending'` for users
  before creating any KYC session (today the DB field is only inserted at
  `/me/kyc` call time).
- Phase 3 — webhook handler should hash the offending signature header on
  `rejected_signature` events (avoid storing raw header).
- Phase 3 — production fail-fast: if `AIPRISE_ENVIRONMENT=production` AND
  `AIPRISE_WEBHOOK_SECRET` is empty → refuse to boot.
- Phase 1 test path: fix `ModuleNotFoundError: db` in
  `test_audit_helper_raises_on_mutation_calls` (PYTHONPATH quirk).

## 🟠 Sprint B — requires user input
- **Real AiPrise templates** — need `AIPRISE_KYC_TEMPLATE_ID`,
  `AIPRISE_KYB_TEMPLATE_ID`, `AIPRISE_WEBHOOK_SECRET` from Dashboard.
- **Resend real email** — `RESEND_API_KEY` + verified sender domain.
- **Stellar upstream real** — preview egress block on `horizon.stellar.org`.

## 🟡 Phase 4 — Treasury & Funds (next P1)
- Subscribe / redeem flows · NAV publication · fee accruals · reconciliation.

## Notes
- Old codebase preserved at `/app/legacy/` — do not import from there.
- Test credentials: see `/app/memory/test_credentials.md`.
