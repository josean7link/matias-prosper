# Prosper Platform — Product Requirements Document

## Original Problem Statement
Build the complete Prosper software platform based on the PRD artifacts provided by the user:
- Prosper Internal Backoffice (for Prosper staff)
- Prosper Client / Partner Portal
- API-first partner integrations

Prosper is a regulated tokenized yield infrastructure platform built on Stellar.
Real backend APIs reside at `http://lb-backend-develop-1915190402.us-west-2.elb.amazonaws.com/api`
(auth: `prosperDevelop / T3st1ng_Pr0sp3r*`). The Prosper platform in this repo
includes an HTTP proxy client (`prosper_client.py`) that can call those endpoints
when `PROSPER_API_ENABLED=true` is set; otherwise responses are simulated so the
platform works end-to-end with demo data.

## Architecture (adapted to FastAPI + MongoDB + React)
- Backend: FastAPI async (Motor for MongoDB), single service with routers per domain
- Frontend: React 19 + React Router 7 + Shadcn UI + Recharts + Phosphor Icons
- Auth: Emergent-managed Google OAuth (session_token, 7-day cookie)
- Design: Dark Swiss / "Control Room" institutional theme (IBM Plex + Chivo, 1px borders, rounded-sm)
- Demo data: Auto-seeded on first backend boot (tagged `is_demo: true`)
- Environment: Sandbox / Production switcher across data queries

## User Personas / Roles
- **super_admin** — Prosper internal, full access
- **ops** — Prosper internal operations
- **compliance** — Prosper KYC/KYB reviewers
- **finance** — Prosper treasury / minting
- **client_admin** — Partner org admin
- **client_user** — Partner org user
- **developer** — Partner developer (manage API keys + webhooks)
- **viewer** — Read-only

Users with email `@prosper.foundation` are auto-flagged internal + super_admin.

## What's Implemented (2026-04-19)
### Backend (FastAPI)
- Emergent Google Auth with /api/auth/session, /auth/me, /auth/logout
- Dashboard aggregated KPIs (/api/dashboard/overview)
- Organizations CRUD + drill-down
- Onboarding cases + compliance review workflow
- Funds / Products / NAV history / Positions
- Treasury console (issuer, treasury, reward_pool, fee accounts)
- Transactions ledger with prosperTxId idempotency anchor + mint endpoint (proxied to real Prosper API when enabled)
- Reconciliation records with resolve workflow
- Integrations: API Apps, API Keys (plaintext returned once), Webhook endpoints + deliveries
- Alerts center with resolve
- Reports (NAV, audit, performance, tax)
- Audit log with filters
- Users admin with role update
- Admin seed + wipe demo endpoints
- Auto-seeded demo data: 5 orgs, 2 funds, 5 products, 35 positions, 120 tx, 120 recon, 6 apps, 3 keys, 3 webhooks, 18 deliveries, 4 alerts, 12 reports, 40 audits, 24 end customers

### Frontend (React)
- Dark Swiss institutional theme
- Login page with Google Auth
- ProtectedRoute + AuthCallback for OAuth flow
- AppShell layout: sidebar + topbar + env switcher + surface switcher (Backoffice ↔ Portal)
- Demo banner on every page

**Backoffice (18 screens):**
Dashboard · Clients · ClientDetail · Onboarding · Compliance · Funds · Products · Positions · Treasury · Transactions · Reconciliation · Integrations · ApiKeys · Webhooks · Alerts · Reports · UsersAdmin · AuditLog

**Client Portal (13 screens):**
Overview · Organization · Users · Balances · Transactions · Yield · EndCustomers · Integrations · ApiKeys · Webhooks · Reports · Compliance · Settings

### Tests
- 29/29 backend pytest cases passing (100%)
- Full frontend UI walkthrough validated by testing agent (~95%)

## P1 — Next Action Items
1. Connect real Prosper Stellar Protocol APIs (set `PROSPER_API_ENABLED=true` + credentials, validate mint/deposit/withdraw flow end-to-end)
2. Implement approval workflow modals (two-signer pattern) for critical operations (mint, fund creation, large redemptions)
3. Split `backend/routers.py` into `backend/routers/*.py` per domain for maintainability
4. Implement missing write endpoints: positions create, webhook edit/pause, fund NAV snapshot publish
5. Add pagination to large tables (currently capped at 200–500 rows)
6. Production email allowlist / organization onboarding flow
7. Real background workers (BullMQ equivalent) for webhook retries, SLA checks, end-of-day NAV snapshots
8. MFA (TOTP) for internal users — flag exists but UI not yet wired
9. Sandbox data isolation — currently `is_demo` flag only; real isolation would need per-env collection or field scoping end-to-end
10. Implement the Soroban term-staking contract integration once the upstream APIs are published

## P2 — Enhancements
- Public developer portal (docs + API explorer)
- CSV/PDF export on Reports center
- Real-time WebSocket updates for transactions + alerts
- Stellar explorer embedded drawer instead of external link
- Multi-fund support (currently only PROS is fully populated)

## Architecture Decisions Log
- Used Motor (async MongoDB) over the sync driver for FastAPI compatibility
- Single `routers.py` to accelerate MVP delivery; modularisation left for P1
- RBAC enforced via `Depends(require_roles(...))` decorator
- `prosperTxId` (UUIDv4) is the idempotency anchor stored in Stellar memo + DB
- All demo records tagged `is_demo: true` so they can be surgically removed without risk
- Session tokens issued by Emergent backend; stored in `prosper_sessions` with UTC timezone-aware expiry
