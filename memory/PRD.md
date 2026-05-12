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
- Pydantic + TS shared types (Organization, User, Transaction, Position,
  AuditLog, Alert, Approval).
- RBAC roles + org-scoping middleware + impersonation header.
- Immutable audit log (POST-only, 405 on PATCH/DELETE).
- Idempotent seed CLI.

## ✅ Phase 2 — Admin Home / KPIs + Sprint A enhancements (2026-05-12)

### Backend (`/api/v1/admin/dashboard/*`)
Split into one file per endpoint under `/backend/routes/dashboard/`:
- `kpis.py` — single `$facet` for AUM, NAV, Revenue MTD/YTD, Volume 30d,
  Active Clients, Ops Queue, 24h deltas.
- `nav_history.py` — reads **real snapshots** from `nav_snapshots` collection
  (synthetic curve replaced with a noise-augmented per-day backfill).
- `volume.py` — daily subscribe vs redeem (capped to `days` items).
- `revenue.py` — monthly fee revenue (exact first-of-month math).
- `top_clients.py` — orgs by AUM with `commercial_name` lookup.
- `ops_queue.py` — pending approvals + KYB + alerts + webhooks + recon
  (`build_ops_queue` shared with the WebSocket pusher).
- `recent_activity.py` — last N confirmed transactions joined to org name.
- `ws.py` — `WS /ws/ops-queue` cookie-authenticated; pushes ops-queue
  snapshots on connect + every 10s when counts change.
- `nav_snapshots.py` — idempotent backfill helper; populates 180 daily NAV
  snapshots on startup.
- Role-gated to `super_admin / admin / finance` (401 / 403 enforced).
- Tests: 23 phase2_dashboard + 9 sprint_a = **32/32 pytest cases green**.

### Frontend (`/admin`)
- 6 KPI tiles with **`info` tooltips** explaining each calculation
  (AUM = Σ(principal + accrued); NAV from snapshots; etc.).
- NAV area chart (real snapshots) · Volume stacked bar · Revenue monthly bar.
- Sortable Top Clients DataTable.
- **Operations Queue** panel — WebSocket push (with 30s polling fallback);
  status pill shows `Live · ws` / `Connecting…` / `Live · 30s`.
- **Recent Activity** panel — last 8 transactions with org name, ±amount
  (subscribe green / redeem orange), shortened `prosper_tx_id`, time-ago.
- **Export PDF** button (`@react-pdf/renderer`, lazy-loaded on click) —
  produces `prosper-admin-YYYY-MM-DD.pdf` with KPIs + top clients + revenue
  table; uses built-in Helvetica/Courier (no Font.register network fetch);
  sonner toasts on success/failure.
- 7d / 30d / 90d range switcher · Refresh button re-fires all SWR hooks.

## 🟡 Phase 3 — Onboarding KYB/KYC (next P1)
- Public `/apply` screen (no auth) for new organization applications.
- KYB/KYC flow integrated with **AiPrise** (user-confirmed provider).
- Compliance officer review queue in `/admin/compliance`.
- Org status transitions: `pending → in_review → approved | rejected`.
- Must use `integration_playbook_expert_v2` for AiPrise.

## 🔵 P2 Backlog (requires user input)
- **Resend real email** — needs `RESEND_API_KEY` + verified sender domain
  (currently DEV log fallback).
- **Stellar upstream real** — preview infra has NXDOMAIN/egress block on
  `horizon.stellar.org`; needs egress allowlist or alternative Horizon URL.

## 🟢 Smaller follow-ups
- Multi-replica safety: create the `nav_snapshots` unique index BEFORE
  insert_many in `backfill_nav_snapshots`.
- `recent_activity.py`: replace per-row org lookup with `$lookup` or a 60s
  in-memory cache.
- Clean up Next.js woff2 preload warnings (cosmetic).

## Tests
- Backend: Phase 0 (4) · Phase 1 (9) · Phase 2 (23) · Sprint A (9) = 45 cases
  all green.
- Frontend smoke (vitest): KpiCard / Badge / StatusDot.

## Notes
- Old codebase preserved at `/app/legacy/` — do not import from there.
- Test credentials: see `/app/memory/test_credentials.md`.
