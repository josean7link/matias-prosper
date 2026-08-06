# Prosper · Phase 0 (Bootstrap)

> Regulated tokenized-yield platform on Stellar. This is the **Phase 0 monorepo**
> — no business logic yet. Just the foundation: monorepo wiring, design system,
> passwordless OTP auth, layout shells and dev infra. Business modules ship in
> Phases 1–11.

## Estructura

```
/app
├── apps/
│   ├── api/        → symlink → /app/backend     (FastAPI · Python 3.11 async)
│   ├── admin/      → symlink → /app/frontend    (Next.js 14 App Router)
│   └── client/                                  (placeholder — routes live in admin via App Router route groups)
├── packages/
│   ├── ui/                                      (KpiCard · DataTable · MetricChart · Badge · StatusDot)
│   └── types/                                   (shared TS types)
├── backend/                                     (apps/api real folder)
├── frontend/                                    (apps/admin real folder)
├── legacy/                                      (archived previous platform — preserved for reference)
├── pnpm-workspace.yaml
├── package.json
├── docker-compose.yml
├── .env.example
└── .github/workflows/ci.yml
```

> The `apps/api` and `apps/admin` paths exist as symlinks to `/app/backend` and `/app/frontend` so the monorepo layout matches the PRD spec verbatim while supervisor (which expects `/app/backend` + `/app/frontend`) continues to manage processes unchanged.

## Endpoints expuestos

| Method | Path                                  | Purpose                                              |
| ------ | ------------------------------------- | ---------------------------------------------------- |
| GET    | `/api/health`                         | Liveness probe                                       |
| POST   | `/api/v1/auth/passwordless-login`     | Request OTP   `{ email } → { code }`                 |
| POST   | `/api/v1/auth/passwordless-token`     | Exchange OTP `{ code, token } → { accessToken }` + sets `prosper_session` cookie |
| GET    | `/api/v1/auth/me`                     | Current user (cookie or `Authorization: Bearer …`)   |
| POST   | `/api/v1/auth/logout`                 | Clears the session cookie                            |

OTP delivery: Resend if `RESEND_API_KEY` is set, otherwise the OTP is logged to the API stdout (dev fallback). The `code` returned by `/passwordless-login` is an opaque continuation token — **not** the OTP itself.

## Rutas frontend

### Public
- `/login`        — email input
- `/login/otp`    — 4-digit code, paste-aware, auto-advance, 20s resend timer

### Admin portal `(admin)` — sidebar group
- `/admin`            — Home (Phase 0 status + KPI placeholders)
- `/admin/operations` — Operaciones (Próximamente)
- `/admin/business`   — Negocio (Próximamente)
- `/admin/compliance` — Compliance (Próximamente)
- `/admin/clients`    — Clientes (Próximamente)

### Client portal `(client)` — sidebar group
- `/client`             — Dashboard
- `/client/deposit`     — Cargar / Retirar (Próximamente)
- `/client/investments` — Inversiones (Próximamente)
- `/client/yield`       — Rendimientos (Próximamente)
- `/client/profile`     — Perfil (Próximamente)
- `/client/services`    — Servicios futuros (Próximamente)

## Cómo correr localmente

### Opción A — con supervisor (entorno preview / Kubernetes)
Ya está corriendo. API en `:8001`, Next.js en `:3000`.

### Opción B — Docker Compose (api + mongo + redis + mailhog + admin)
```bash
cp .env.example .env
docker compose up -d
# API:      http://localhost:8001/api/health
# Admin UI: http://localhost:3000/login
# Mailhog:  http://localhost:8025  (catches outgoing OTP emails when SMTP wired)
# Mongo:    mongodb://localhost:27017
# Redis:    redis://localhost:6379
```

### Opción C — dev local sin docker
```bash
# Terminal 1 — API
cd /app/backend && /root/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# Terminal 2 — Admin
cd /app/frontend && yarn dev   # next dev -p 3000 -H 0.0.0.0
```

### Tests
```bash
# Backend (Pytest) — 4 smoke tests
cd /app/backend && /root/.venv/bin/python -m pytest tests/test_phase0_smoke.py -q

# Frontend (Vitest) — 3 smoke tests
cd /app/frontend && yarn test
```

### Type-check + lint
```bash
cd /app/frontend && yarn typecheck && yarn lint
```

## Design system (packages/ui)

| Component   | Use                                                                  |
| ----------- | -------------------------------------------------------------------- |
| `KpiCard`   | Label + Chivo-bold value + delta % with up/down arrow                |
| `DataTable` | Sticky header, sorting, right-aligned mono columns for numerics      |
| `MetricChart` | Recharts wrapper (area or line) using Prosper palette + tooltips   |
| `Badge`     | Status pill with auto tone from common status strings                |
| `StatusDot` | Coloured dot (green/yellow/red/grey) with optional pulsing animation |

**Paleta Prosper** (full palette in `frontend/tailwind.config.js`):

| Token   | Hex       | Usage                       |
| ------- | --------- | --------------------------- |
| primary | `#2B6BFF` | Buttons, focus, active nav  |
| dark    | `#0A1F44` | Main text in light mode     |
| light   | `#EBF1FB` | Surfaces in light mode      |
| grey    | `#5B6478` | Secondary text              |
| success | `#0FA958` | Approvals / healthy         |
| warning | `#E07B00` | Pending / needs attention   |
| danger  | `#DC2626` | Failures / critical alerts  |

**Tipografía:**
- IBM Plex Sans (body)
- Chivo (titulares + KPI grandes)
- IBM Plex Mono (números / monto / status labels)

**Dark mode:** persistido en cookie `prosper_theme` (no localStorage para que SSR pinte correctamente en el primer paint).

## Variables de entorno

Ver `.env.example` en el root. Las que ya están seteadas en `/app/backend/.env`:

| Variable          | Default                       | Notes                          |
| ----------------- | ----------------------------- | ------------------------------ |
| `MONGO_URL`       | `mongodb://localhost:27017`   | Required                       |
| `DB_NAME`         | `prosper_phase0`              | Required                       |
| `REDIS_URL`       | `redis://localhost:6379/0`    | Optional (fallback to Mongo)   |
| `JWT_SECRET`      | `phase0-dev-secret-change-me` | Change in production           |
| `RESEND_API_KEY`  | (empty)                       | Optional (OTP logged if empty) |
| `RESEND_FROM`     | `onboarding@resend.dev`       | Resend sandbox sender          |
| `COOKIE_SECURE`   | `false`                       | Set `true` in prod (HTTPS)     |

## CI

`.github/workflows/ci.yml` corre en cada PR:
- **Frontend job:** typecheck → lint → vitest
- **Backend job:** pytest contra un mongo de servicios

## Próximos pasos (Phase 1 →)

Esta es la **Fase 0**. Lo que sigue, según el plan:
- Phase 1: Organisations + multi-tenant scoping + role model
- Phase 2: Onboarding (KYB/KYC), public `/apply` screen + Sumsub
- Phase 3: Funds, products, NAV history
- Phase 4: Treasury, positions, transactions, two-signer Ops
- Phase 5: Webhooks (HMAC) + API keys + idempotency
- … hasta Phase 11.
