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
- App shell: sidebar, env switcher (Sandbox/Production), alerts bell, avatar
  menu, dark-mode toggle. Shared `PageHeader` component.

## ✅ Phase 1 — Data model & multi-tenancy (2026-05-12)
- Pydantic + TS shared types: Organization, User, Transaction, Position,
  AuditLog, Alert, Approval.
- RBAC roles (`super_admin`, `admin`, `finance`, `compliance`, `support`,
  `client_admin`, `client_user`).
- Org scoping middleware + `requires_role` decorator + impersonation header
  (`X-Acting-As-Org`).
- Immutable audit log (`POST`-only, `405` on PATCH/DELETE).
- Seed CLI (idempotent upsert by email/org_id).

## ✅ Phase 2 — Admin Home / KPIs (2026-05-12)
Backend (`/api/v1/admin/dashboard/*`):
- `/kpis` — single `$facet` returning AUM, NAV, Revenue MTD/YTD, Volume 30d,
  Active Clients, Ops Queue count, 24h deltas.
- `/nav-history?days=N` — daily NAV trajectory.
- `/volume?days=N` — daily subscribe vs redeem (stacked, fixed off-by-one).
- `/revenue?months=N` — monthly fee revenue.
- `/top-clients?limit=N` — orgs by AUM, joined to commercial_name.
- `/ops-queue` — approvals + KYB pending + alerts + webhooks + reconciliation.
- Role-gated to `super_admin / admin / finance` (401 unauthenticated, 403 other).
- Seed: 6 months of historical positions + transactions for Finpact and Alemany.

Frontend (`/admin`):
- 6 KPI tiles (AUM, NAV, Revenue MTD, Volume, Active Clients, Ops Queue) with
  24h delta arrows and hint subtitles. IBM Plex Mono numbers, Chivo headings.
- NAV area chart (90d) · Volume stacked bar (subscribe/redeem) · Revenue
  monthly bars (12mo). Recharts with Prosper-themed tooltips.
- Sortable Top Clients DataTable.
- Live Operations Queue side panel (5 rows · 30s polling · flash animation when
  counts change · status dot pulses on non-empty queue).
- 7d / 30d / 90d range switcher · Refresh button re-fires SWR.
- 23/23 pytest cases pass · all data-testids in place.

## 🟡 Phase 3 — Onboarding KYB/KYC (next)
- Public `/apply` screen (no auth) for new organization applications.
- KYB/KYC flow integrated with **AiPrise** (user-confirmed provider).
- Compliance officer review queue in `/admin/compliance`.
- Org status transitions: `pending → in_review → approved | rejected`.
- Must use `integration_playbook_expert_v2` for AiPrise.

## P2 Backlog
- Dashboard export as PDF (`@react-pdf/renderer`).
- Tooltips on KPIs explaining each calculation.
- WebSockets in place of 30s polling on the Ops Queue.
- Replace synthetic NAV in `/nav-history` with a real prior-day snapshot
  collection so 24h deltas are non-zero on fresh DBs.
- Use `dateutil.relativedelta` in `/revenue` instead of `timedelta(days=31*…)`.
- Split `routes_dashboard.py` (303 lines) into `/backend/routes/dashboard/*`.
- Real Resend transactional emails (currently dev log fallback).
- Real Stellar upstream (currently mocked due to infra egress block).

## Tests
- Backend smoke (Phase 0): 4 cases · Phase 1: 9 cases · Phase 2: 23 cases.
- Frontend smoke: KpiCard / Badge / StatusDot (vitest).
- All green as of 2026-05-12.

## Notes
- Old codebase preserved at `/app/legacy/` — do not import from there.
- Test credentials: see `/app/memory/test_credentials.md`.
