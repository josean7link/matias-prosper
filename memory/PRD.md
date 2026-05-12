# Prosper Platform — PRD & Status

> ⚠️ Phase 0 reset (2026-05-12) — the platform was rebuilt from scratch following
> the user's `01_PRD_Prosper_Plataforma.md` + `fase_00_bootstrap.md` spec.
> The previous demo (CRA + Google OAuth + 32 demo screens) lives in `/app/legacy/`.

## What is the platform
Regulated tokenized-yield platform on Stellar with two portals (Admin internal staff + Client/Partner) + a public Developer Portal. Built in 12 phases. **Phase 0 = bootstrap only** (foundation, no business logic).

## Phase 0 — Delivered (2026-05-12)

### Monorepo
- `pnpm-workspace.yaml` + root `package.json` (yarn-classic compatible)
- `apps/api` → `/app/backend` · FastAPI Python 3.11 async
- `apps/admin` → `/app/frontend` · Next.js 14 App Router + TypeScript
- `apps/client` placeholder (routes live in admin via App Router route groups)
- `packages/ui` · `KpiCard` · `DataTable` · `MetricChart` · `Badge` · `StatusDot`
- `packages/types` · shared TS interfaces
- `docker-compose.yml` · api + mongo + redis + mailhog + admin
- `.env.example` at root
- `.github/workflows/ci.yml` · typecheck + lint + tests on each PR

### Backend (apps/api)
| Method | Path                                | Purpose                          |
| ------ | ----------------------------------- | -------------------------------- |
| GET    | `/api/health`                       | Liveness                         |
| POST   | `/api/v1/auth/passwordless-login`   | `{email}` → `{code}` (4-digit OTP sent via Resend) |
| POST   | `/api/v1/auth/passwordless-token`   | `{code, token}` → JWT cookie     |
| GET    | `/api/v1/auth/me`                   | Current user from cookie         |
| POST   | `/api/v1/auth/logout`               | Clear cookie                     |

OTP storage: Redis with Mongo fallback. JWT: 7-day expiry, httpOnly cookie samesite=lax.

### Frontend (apps/admin = `/app/frontend`)
Public:
- `/login` — email input
- `/login/otp` — 4-digit code, paste-aware, auto-advance, 20s resend timer

Admin route group (5 items, 4 marked SOON):
`/admin · /admin/operations · /admin/business · /admin/compliance · /admin/clients`

Client route group (6 items, 5 marked SOON):
`/client · /client/deposit · /client/investments · /client/yield · /client/profile · /client/services`

Layout shell: collapsible sidebar, env switcher (Sandbox/Production for admin), alerts bell with dot, avatar with email + role + logout, dark mode toggle persisted in cookie (`prosper_theme`).

### Design system (packages/ui)
- Tailwind + CSS variables for light/dark theming
- Fonts: IBM Plex Sans · Chivo · IBM Plex Mono (Google Fonts via `next/font`)
- Palette: primary `#2B6BFF` · dark `#0A1F44` · light `#EBF1FB` · grey `#5B6478` · success `#0FA958` · warning `#E07B00` · danger `#DC2626`
- Border radius default 8px, 12px on large cards. Shadows soft: `0 2px 8px rgba(10,31,68,0.06)`

### Tests
- Backend: 4 pytest smoke tests (health, login OTP, invalid OTP rejection, me requires auth)
- Frontend: 3 vitest smoke tests (KpiCard, Badge auto-tone, StatusDot)
- All passing.

## Next phases (P1+)
The 12-phase plan from `01_PRD_Prosper_Plataforma.md` continues. Phase 1 = organisations + multi-tenant scoping + role model. Phase 2 = onboarding (KYB/KYC) + Sumsub. Etc.

Old demo platform is preserved at `/app/legacy/` for reference / cherry-picking patterns into the new codebase.
