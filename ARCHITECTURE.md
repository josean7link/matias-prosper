# Prosper Platform — Architecture

> High-level architecture, surface map and critical flows. Maintain in
> sync with reality.

## 1. Surfaces

| Surface         | Stack                                | Users                       |
|-----------------|--------------------------------------|-----------------------------|
| Portal Admin    | Next.js 14 App Router (`/admin/*`)   | super_admin, admin, compliance_officer, finance |
| Portal Cliente  | Next.js 14 App Router (`/client/*`)  | client_admin, client_user   |
| /apply (public) | Next.js 14 (token-gated)             | new prospects               |
| /status, /terms, /privacy, /access | Next.js 14 (public) | anyone                      |
| API             | FastAPI + Motor (MongoDB)            | servers + integrations      |
| Workers         | APScheduler (in-process)             | n/a (cron)                  |

All frontend surfaces share a single Next.js app — segregation is by
route + role guards in `AppShell.tsx`.

## 2. High-level diagram

```
                         ┌───────────────────────────┐
                         │   Public Internet         │
                         │  (statuspage.io optional) │
                         └──────────────┬────────────┘
                                        │
                                ┌───────▼────────┐
                                │  K8s Ingress   │ ← TLS termination
                                │  /api → :8001  │
                                │   /*  → :3000  │
                                └───┬────────┬───┘
                                    │        │
              ┌─────────────────────┘        └──────────────────────┐
              │                                                     │
     ┌────────▼─────────┐                                  ┌────────▼────────┐
     │  Next.js 14 SSR  │                                  │ FastAPI (uvicorn) │
     │  (admin/client/  │                                  │  routes/*.py      │
     │   apply/status)  │                                  │  audit + auth     │
     └──────────────────┘                                  └────┬──────────┬───┘
                                                               │          │
                                       ┌───────────────────────┘          │
                                       │                                  │
                              ┌────────▼─────────┐              ┌─────────▼──────────┐
                              │  MongoDB (Motor) │              │  Redis (OTP cache) │
                              │  collections×25  │              │  optional          │
                              └────────┬─────────┘              └────────────────────┘
                                       │
              ┌────────────────────────┼─────────────────────────────────────┐
              │                        │                                     │
       ┌──────▼─────┐         ┌────────▼────────┐                  ┌─────────▼────────┐
       │ AiPrise    │         │ Alfred adapter  │                  │ Prosper adapter  │
       │ KYB/KYC    │         │ Onramp/Offramp  │                  │ Stellar minter   │
       │ (mocked)   │         │ (mocked)        │                  │ (mocked)         │
       └────────────┘         └─────────────────┘                  └──────────────────┘
```

## 3. Auth + session model

- **Passwordless OTP** (`/api/v1/auth/passwordless-login` + `…/passwordless-token`)
  → JWT in httpOnly cookie `prosper_session` (7d TTL).
- JWT carries `sub` (user_id), `email`, `role`, `org_id`, **`jti`** (session id).
- `sessions` collection stores the session metadata (IP, UA, last_seen_at,
  revoked). `get_current_user` validates the session is active on every
  request — revoking a session forces re-auth on the next call.
- MFA TOTP optional, enabled per-user via `/client/profile`. Secret
  encrypted with Fernet (`MFA_FERNET_KEY`). Backup codes bcrypt-hashed.
- Dev magic link (`/api/v1/auth/dev-login`) is available only when
  `RESEND_API_KEY` is empty (preview/sandbox).

## 4. RBAC

Defined in `backend/roles.py`. The 6 roles + their default permissions:

| Role               | Scope         | Highlights                                       |
|--------------------|---------------|--------------------------------------------------|
| `super_admin`      | global        | Everything. Mint approval (signer A or B).       |
| `admin`            | global        | Org CRUD, no compliance decisions, no mint.      |
| `compliance_officer` | global      | KYC/KYB/KYT/Risk decisions. Read-only on financials. |
| `finance`          | global        | Mint approval (signer A or B). Treasury.         |
| `client_admin`     | own org       | API keys, webhooks, user mgmt within org.        |
| `client_user`      | own org       | Read-only org data + own profile.                |

Cross-org reads from non-internal users return **404** (never 403) to
avoid information disclosure.

## 5. Multi-tenant invariants

- Every collection except `organizations` and `audit_logs.system_actions`
  carries `org_id`. Every list query MUST filter by `org_id` for client
  users (`org_scoped()` dep).
- Internal users can impersonate via `X-Acting-As-Org: <org_id>` header —
  the audit log records both `actor_user_id` and `metadata.acting_as_org`.
- Soft delete pattern: `is_deleted=true`. Indexes filter on it.

## 6. Critical flows

### 6.1 KYB onboarding

```
/apply?token=<jwt 72h> ──> /v1/apply/context ──> wizard 7 pasos ──>
  /v1/apply/finalize ──┬─> create KybCase (in_review)
                       ├─> flip org.kyb_status = in_review
                       ├─> alert compliance@prosper.foundation
                       └─> send mock email
```

Compliance reviews at `/admin/compliance/kyb` → approves → `org.kyb_status=approved`.
The `ClientGateBanner` reacts and unblocks the dashboard.

### 6.2 Onramp + auto-buy Prosper

```
POST /client/onramp/orders ─> Alfred adapter ─> auto-settle (mock 8s)
                                  │
                       webhook ───▼
                       /webhooks/alfred (HMAC verified)
                                  │
                       ┌──────────┴──────────┐
                       │ trigger_buy_after_onramp │ (idempotent)
                       │  - create subscribe TX  │
                       │  - Prosper deposit      │
                       │  - create Position      │
                       │  - confirm TX           │
                       └─────────────────────────┘
```

### 6.3 Daily accrual

Every day at 00:00 UTC, `jobs/accrual.run_accrual_once()` ticks every
active position: `accrued_interest += principal × apr_bps / 10_000 / 365`.
Idempotent per `last_accrued_date`. Positions whose maturity has passed
flip to `matured` and stop accruing.

### 6.4 Webhook delivery

`_deliver()` in `routes/admin_clients/webhooks.py` signs each payload
with HMAC-SHA256 using the endpoint's secret, retries with backoff on
5xx (TODO: still synchronous — move to a queue), logs every attempt
into `webhook_deliveries`.

## 7. Data model overview

Key collections (see `db.py` for the full list):

- `organizations` · `users` · `sessions`
- `kyb_cases` · `kyc_cases` · `kyt_rules` · `kyt_alerts` · `risk_scores`
- `onramp_orders` · `offramp_orders`
- `positions` · `transactions` · `products`
- `api_keys` · `webhook_endpoints` · `webhook_deliveries`
- `alerts` · `approvals` · `audit_logs` (immutable, append-only)
- `nav_snapshots` (daily)
- `outbound_emails` (preview-only when Resend not configured)
- `feature_interest` (coming-soon CTAs)
- `signed_links` (KYB invite tokens, single-use)

## 8. Background jobs

- **`run_accrual_once`** — APScheduler cron `0 0 * * *` UTC.
- **TODO**: nightly NAV snapshot job (currently backfilled at startup).
- **TODO**: hard-delete users with `deletion_effective_at < now()` once
  per day after the 7-day cooldown.

## 9. Environment matrix

| Env       | Mongo            | Redis        | Alfred  | Prosper  | Resend |
|-----------|------------------|--------------|---------|----------|--------|
| preview   | local (k8s pod)  | local        | mock    | mock     | disabled (dev OTP visible) |
| staging   | Atlas M10        | ElastiCache  | sandbox | development | sandbox key |
| prod      | Atlas M20+ replica | ElastiCache | production | production | production key |
