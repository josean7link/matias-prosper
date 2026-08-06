# Prosper Platform — Integrations

> Reference for connecting Prosper to third-party providers. Each
> integration has a **Mock adapter** (default) and a **Real adapter**.
> Flip via env var.

## 1. AiPrise (KYB / KYC)

**Status**: Real adapter implemented, runs in `simulated` mode until
template IDs + webhook secret arrive.

| Env var                       | Required for       | Example                  |
|-------------------------------|---------------------|--------------------------|
| `AIPRISE_API_KEY_SANDBOX`     | sandbox flows       | `bdb602e5…`              |
| `AIPRISE_API_KEY_PRODUCTION`  | production flows    | `a9879e9e…`              |
| `AIPRISE_KYC_TEMPLATE_ID`     | KYC live mode       | (empty → simulated)      |
| `AIPRISE_KYB_TEMPLATE_ID`     | KYB live mode       | (empty → simulated)      |
| `AIPRISE_WEBHOOK_SECRET`      | webhook validation  | (empty → no enforcement) |

Endpoints we hit:
- `POST {base}/onboarding/v1/sessions` — create verification session.
- `GET  {base}/onboarding/v1/sessions/{id}` — poll status.
- Webhook: `POST /api/v1/webhooks/aiprise` — receives `verification.completed`.

Switch to live: populate the 3 empty vars + ensure dashboard webhook
URL points to your prod ingress.

## 2. Alfred (Onramp / Offramp)

**Status**: Mock adapter implements full lifecycle. Real adapter is a stub
ready for sandbox/production endpoints.

| Env var                  | Values                  | Default                    |
|--------------------------|--------------------------|----------------------------|
| `ALFRED_MODE`            | `mock`/`sandbox`/`production` | `mock`                |
| `ALFRED_API_KEY`         | (none for mock)          | empty                      |
| `ALFRED_API_BASE`        | provider URL             | empty                      |
| `ALFRED_WEBHOOK_SECRET`  | HMAC SHA256 secret       | `mock_secret_change_me`    |
| `ALFRED_CALLBACK_URL`    | our public webhook URL   | empty                      |

Endpoints expected from Real adapter (confirm format with Alfred docs
at switchover time):
- `POST /v1/quotes`
- `POST /v1/orders/onramp`
- `POST /v1/orders/offramp`
- `GET  /v1/orders/{id}`

Our webhook: `POST /api/v1/webhooks/alfred` validates HMAC SHA256 +
idempotent per `event_id` (collection `webhook_events`).

## 3. Prosper backend (Stellar minter)

**Status**: Mock adapter operates in-memory. Real adapter is fully
implemented with JWT auto-refresh.

| Env var              | Values                       | Default                              |
|----------------------|-------------------------------|--------------------------------------|
| `PROSPER_MODE`       | `mock`/`development`/`production` | `mock`                          |
| `PROSPER_API_BASE`   | `https://api-dev.prosper.…`  | empty                                |
| `PROSPER_API_USER`   | service username             | `prosperDevelop` (dev)               |
| `PROSPER_API_PASS`   | service password             | (set in env)                         |

Endpoints called:
- `POST /v1/Auth/Login`
- `POST /v1/users/new`
- `POST /v1/users/deposit`
- `POST /v1/users/withdraw`
- `POST /v1/tokens/transfer`
- `GET  /v1/users/{id}/balances`
- `GET  /v1/users/{id}/transactions`
- `GET  /v1/assets/`

Auto-refresh on 401 retries the request once after re-login.

## 4. TRM Labs (on-chain screening)

**Status**: Stub — `screen_wallet()` returns `status: unavailable` until
the API key arrives.

| Env var            | Required | Example                          |
|--------------------|----------|----------------------------------|
| `TRM_LABS_API_KEY` | yes      | (request from TRM)               |

Endpoint: `POST https://api.trmlabs.com/public/v2/screening/addresses`
(confirm with TRM at provisioning).

## 5. Resend (transactional emails)

**Status**: Mock-friendly — when `RESEND_API_KEY` is empty, emails are
saved into `outbound_emails` collection with `status=preview_only` + HTML
previewable from the admin client detail page.

| Env var          | Required for prod | Default                       |
|------------------|-------------------|-------------------------------|
| `RESEND_API_KEY` | live email send   | empty                         |
| `RESEND_FROM`    | from address      | `onboarding@resend.dev` (dev) |

Templates (HTML in `integrations/email_sender.py`):
- `welcome.html` — KYB approved
- `invite.html` — client_admin invitation
- `kyb_invite.html` — onboarding link
- `kyb_submitted.html` — internal notif to compliance
- `password_reset.html` — sent on password-flow signups

Switch to live: set `RESEND_API_KEY` + verified domain in `RESEND_FROM`.

## 6. Sumsub (legacy, replaced by AiPrise)

> The product brief originally specified Sumsub. The team decided to use
> AiPrise instead — Sumsub integration is **out of scope** but the
> `/apply` wizard frontend is generic enough to swap the provider.

## 7. Adding a new integration

1. Define an `Adapter` interface in `backend/integrations/<name>/adapter.py`.
2. Implement `MockAdapter` (deterministic, in-memory) + `RealAdapter`
   (HTTP/whatever).
3. Add `<NAME>_MODE` env var with values `mock` / `sandbox` / `production`.
4. Use a singleton factory: `get_adapter()` that caches the instance based
   on the mode at first call.
5. Wire the adapter into a route module (`routes/client_<name>.py`).
6. Log every external call into a `<name>_calls_log` collection — useful
   for debugging without hitting the real provider.
7. Add a pytest with both mock + real-adapter contract tests.

## 8. Outbound webhooks (we → them)

See `RUNBOOK.md` § 6 (Investigate webhook failing) for the operator side.

Developer-facing docs are at `/client/developers` (interactive curl
samples) and `/client/sdk` (Python/JS/cURL snippets).

Events we emit:
- `onramp.confirmed`, `onramp.failed`
- `offramp.completed`, `offramp.failed`
- `subscribe.confirmed`, `redeem.confirmed`
- `position.matured`
- `kyc.approved`, `kyc.rejected`
- `alert.critical`

All signed with HMAC SHA256 using the endpoint's `secret`. Header:
`X-Prosper-Signature: <hex>`. Idempotency: include the `event_id` and
de-dupe at your end.
