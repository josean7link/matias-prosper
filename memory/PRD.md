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

## What's Implemented (updated 2026-04-20)

### 2026-04-20 — Developer Portal + KYC Object Storage
- **Public Developer Portal** at `/developers` (no auth) — hero, quickstart, endpoint reference with sidebar nav for Auth / Subscribe & Redeem / Mint (two-signer) / Webhooks / Transactions, live example code toggles between curl / javascript / python, plus a copy-to-clipboard button on every code block and a direct link to `/openapi.json`.
- **KYC / KYB document upload** — integrated Emergent Object Storage (`/app/backend/storage.py`), with 4 new endpoints under `/api/documents`:
  - `POST /api/documents/upload` — multipart (file + org_id + doc_type), 10 MB max, allowed: pdf/png/jpg/jpeg/webp/csv; non-internal users cannot upload to another org.
  - `GET /api/documents` — list scoped to org.
  - `GET /api/documents/{id}/download` — streams the file with original Content-Type.
  - `DELETE /api/documents/{id}` — soft delete (is_deleted flag).
- **Frontend**: reusable `DocumentsPanel` component with drag-drop + doc_type selector + Download / Delete actions. Wired into Portal `Organization` page and Backoffice `ClientDetail` page.
- Tests: 11/11 backend pytest pass (`/app/backend/tests/test_documents_api.py`), frontend public portal + upload panel validated by testing_agent iteration_2.

### 2026-04-19 — Core MVP
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
- Two-signer Operations Queue (Approvals) for mint + critical actions
- MFA TOTP (setup / verify / disable) + challenge at approval time
- HMAC-SHA256 webhook signatures (`X-Prosper-Signature: t=…,v1=…`), delivery log, retries
- APScheduler background workers (webhook retries, SLA checks, EOD NAV snapshots)
- Global ⌘K search endpoint
- Idempotency-Key middleware for write mutations
- Auto-seeded demo data: 5 orgs, 2 funds, 5 products, 35 positions, 120 tx, 120 recon, 6 apps, 3 keys, 3 webhooks, 18 deliveries, 4 alerts, 12 reports, 40 audits, 24 end customers

### Frontend (React)
- Dark Swiss institutional theme + light mode matched to prosper.foundation brand
- Login page with Emergent Google Auth
- ProtectedRoute + AuthCallback for OAuth flow
- AppShell layout: sidebar + topbar + env switcher + surface switcher (Backoffice ↔ Portal)
- ⌘K Command Palette, Alerts Bell, pagination, CSV exports, date-range pickers
- Demo banner on every page

**Backoffice (19 screens):**
Dashboard · Clients · ClientDetail (w/ Documents) · Onboarding · Compliance · Funds · Products · Positions · Treasury · Transactions · Reconciliation · Integrations · ApiKeys · Webhooks · Alerts · Reports · UsersAdmin · AuditLog · Approvals

**Client Portal (13 screens):**
Overview · Organization (w/ Documents) · Users · Balances · Transactions · Yield · EndCustomers · Integrations · ApiKeys · Webhooks · Reports · Compliance · Settings

**Public:**
Login · Developer Portal (`/developers`)

### Tests
- 29/29 core backend pytest cases passing (iteration_1)
- 11/11 documents backend pytest cases passing (iteration_2)
- Public Dev Portal + Documents Panel UI validated by testing agent

## P1 — Next Action Items
1. Connect real Prosper Stellar Protocol APIs (blocked: firewall, returned HTTP 000 during test). Set `PROSPER_API_ENABLED=true` + creds once network unblocked.
2. Split `backend/routers.py` (~1500 lines) into `backend/routers/*.py` per domain (empty package already exists).
3. Switch `storage.py` from synchronous `requests` to `httpx.AsyncClient` or `asyncio.to_thread` (minor perf nit flagged by testing agent).
4. Seed a non-internal test user so cross-org upload guard can be exercised via automation.
5. Magic-byte sniffing on uploaded docs (in addition to extension check).
6. Production email allowlist / organization onboarding flow.

## P2 — Enhancements
- Sandbox with independent seed (fully separate from production seed)
- API Key consumption dashboard (quota, requests/day, last-used timestamps)
- Internal status page (webhook delivery p95, reconciliation lag)
- Session management UI (list active sessions / revoke)
- MongoDB indexes for scale (org_id, prosper_tx_id, created_at)
- Soroban term-staking contract integration when upstream APIs publish
- CSV/PDF export on Reports center (CSV already live; PDF pending)
- Real-time WebSocket updates for transactions + alerts
- Multi-fund support (currently only PROS is fully populated)

## Architecture Decisions Log
- Used Motor (async MongoDB) over the sync driver for FastAPI compatibility
- Single `routers.py` to accelerate MVP delivery; modularisation left for P1
- RBAC enforced via `Depends(require_roles(...))` decorator
- `prosperTxId` (UUIDv4) is the idempotency anchor stored in Stellar memo + DB
- All demo records tagged `is_demo: true` so they can be surgically removed without risk
- Session tokens issued by Emergent backend; stored in `prosper_sessions` with UTC timezone-aware expiry
- Object storage via Emergent managed storage (session-scoped key, `prosper/kyc/{org_id}/{doc_id}.{ext}` layout)
- Documents are soft-deleted (no delete API on storage)
