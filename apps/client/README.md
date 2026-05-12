# Prosper · Client Portal (apps/client)

Phase 0 placeholder. The Client portal routes are currently served by the
shared Next.js app at **`/frontend`** under the App Router route group
**`(client)`** at the path `/client/*`.

This package exists so the monorepo structure matches the PRD layout
(`apps/admin` + `apps/client`). In a later phase — once production
deployment requires its own domain — this folder will be promoted to a
fully independent Next.js 14 app importing the same `@prosper/ui` and
`@prosper/types` packages.

## Routes (today, in `/frontend`)
- `/client`              → Dashboard
- `/client/deposit`      → Cargar / Retirar
- `/client/investments`  → Inversiones
- `/client/yield`        → Rendimientos
- `/client/profile`      → Perfil
- `/client/services`     → Servicios futuros

## Run
```
cd /app/frontend && yarn dev   # one server, both portals
```
