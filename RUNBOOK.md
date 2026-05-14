# Prosper Platform — RUNBOOK

> Procedures for day-to-day operations and incident response. Audience:
> Ops + Compliance teams. Maintain this file in sync with reality — any
> deviation between the runbook and the actual flow is a bug.

Last updated: 2026-05-14 (Sprint 12).

---

## Quick links

- Admin portal: `/admin`
- Compliance dashboard: `/admin/compliance/{kyc,kyb,kyt,risk,alerts,limits}`
- Audit log endpoint: `GET /api/v1/audit-logs?limit=200`
- Status page (public): `/status`
- Dev login (preview only): `/api/v1/auth/dev-login?email=<email>&next=/admin`

---

## 1. Approve a KYB

1. Sign in as a `super_admin` or `compliance_officer`.
2. Go to `/admin/compliance/kyb` — pending cases are sorted by SLA color.
3. Click a case to open the drawer.
4. Verify: company info, documents (zoom each one), UBO ownership chart,
   provider score/flags, and the 8-item regulatory checklist.
5. **All 8 checklist items must be ticked** before the "Aprobar" button
   becomes active.
6. Decision modal: pick `Aprobar` / `Rechazar` / `Pedir info`. Write a
   motive ≥20 characters (required).
7. After approval: `org.kyb_status` flips to `approved`, the client gets
   an email and can operate immediately. An entry lands in `audit_logs`.

> ⚠️ If you reject, write a clear motive — the client sees it verbatim in
> their portal banner.

---

## 2. Approve a mint (two-signer)

Mint operations require two distinct approvers:

1. Operations submits a `mint_request` via `POST /api/v1/operations/mints`.
2. Approver A goes to `/admin/operations/approvals`, opens the request,
   clicks `Aprobar`. Status flips to `awaiting_second_signer`.
3. Approver B (must be a different user, both `super_admin` or `finance`)
   opens the same request and clicks `Aprobar`. Status flips to `approved`.
4. The mint is executed against the Stellar adapter automatically.
5. Audit trail: 2 `approval.granted` entries with both `actor_user_id`s.

> If the two-signer rule needs to be bypassed (e.g. emergency rollback),
> use the manual `POST /api/v1/operations/mints/{id}/force-execute`
> endpoint — `super_admin` only — and document the reason in audit log
> via `metadata.reason`.

---

## 3. Investigate unmatched reconciliation

1. Open `/admin/operations/lifecycle` and filter by `status=unmatched`.
2. For each unmatched tx: cross-check the `prosper_tx_id` against the
   Prosper backend `GET /v1/users/{id}/transactions` response (or the
   mock adapter's in-memory log if running in mock mode).
3. If the Stellar leg succeeded but the local doc is stuck, click
   `Retry step` to re-run the matcher.
4. If the Stellar leg failed but the local doc is `confirmed`, escalate
   to the dev oncall via `#prosper-eng` — likely a webhook drop.

---

## 4. Rotate a compromised API key

1. Identify the compromised `key_id` via `GET /api/v1/audit-logs?action=api_key.used`
   filtering by suspicious IP.
2. As `client_admin` (or via impersonation): `POST /api/v1/client/api-keys/{key_id}/rotate`.
   The response carries the new plaintext (shown once).
3. Communicate the new key to the integrating team **out-of-band** (Slack,
   Signal — NOT email).
4. The old key stops working instantly (its `secret_hash` is replaced).
5. Audit log entry: `client.api_key.rotate` with the actor + key_id.

---

## 5. Revoke a user session

1. The user can self-revoke at `/client/profile` → tab Sesiones.
2. Internal staff revoke via Mongo:
   ```
   db.sessions.updateOne(
     { session_id: "ses_…" },
     { $set: { revoked: true, revoked_at: <iso>, revoke_reason: "ops" } }
   );
   ```
3. Subsequent requests with that JWT return `401 Session revoked`.
4. The user is forced to re-authenticate via OTP.

---

## 6. Investigate webhook failing

1. `/admin/clients/{org_id}` → tab Webhooks → see `fail_count` + `last_status`.
2. Click the endpoint to see the last 100 deliveries (`GET /webhooks/{id}/deliveries`).
3. Common causes:
   - Endpoint returning 5xx ⇒ contact integrating team.
   - HMAC mismatch ⇒ they're using an old secret. Have them re-fetch via
     `POST /webhooks/{id}/reveal-secret` (audit-logged).
   - Timeout >5s ⇒ endpoint is too slow, recommend async processing.
4. After 6 consecutive failures the endpoint is auto-paused (`status=paused`).
   To re-enable: `PATCH /webhooks/{id}` with `{"status": "active"}`.

---

## 7. Restore a Mongo backup

> Production setup uses MongoDB Atlas with continuous snapshots. Preview
> environment has no backups — DO NOT promote preview Mongo to prod.

1. SSH into ops bastion.
2. List available snapshots: `atlas backups snapshots list --clusterName prosper-prod`.
3. Trigger restore to staging first: `atlas backups restores start <snap-id> --target staging`.
4. Validate row counts on key collections (organizations, users, transactions).
5. Once staging looks healthy, schedule prod restore during maintenance window.
6. Update `/status` page manually to "degraded" until restore completes.

---

## 8. Increase a client's caps

1. `/admin/compliance/limits` → search the org → click a row to edit inline.
2. Change `subscribe_daily_cap_usd`, `subscribe_monthly_cap_usd`,
   `redeem_daily_cap_usd`, or `redeem_monthly_cap_usd`.
3. Confirm — an audit log entry + an entry in `limits_history` is created.
4. The new caps take effect immediately on the next `POST /client/onramp/orders`
   or `POST /client/positions/{id}/redeem` call.

> Caps must be approved by Risk (`risk_score < 50`) for large increases
> (>2x current value). The UI enforces this via a confirm modal.

---

## 9. Add a new investment product

1. Backend: edit `routes/client_invest.ensure_products()` adding a dict
   with `product_id`, `apr_bps`, `lock_days`, `min_amount`, `max_amount`,
   `currency`, `status`. Restart backend — `ensure_products` is lazy and
   idempotent.
2. Frontend: the `/client/invest` UI auto-discovers active products via
   `GET /v1/client/products`. No frontend change required.
3. Test with a `client_admin` account: open `/client/invest`, the new
   product card should appear with its APR.
4. Audit log entry: `product.created` with the full product dict.

---

## 10. Wipe demo data (pre-launch / between sales demos)

1. Sign in as `super_admin`.
2. `POST /api/v1/admin/ops/wipe-demo` with body `{"confirm": "WIPE-DEMO"}`.
3. The response carries per-collection delete counts. Audit log entry:
   `admin.ops.wipe_demo` with the full summary.
4. Seed data (the 4 staff users + 2 seed orgs) is preserved because they
   don't carry `is_demo=true`.
5. On next backend restart, `seed_demo_transactions` will re-fill demo
   transactions unless you also set `PROSPER_DISABLE_DEMO_SEED=1`.

---

## 11. Seed a new demo client for sales

Faster than running the wizard:

1. Sign in as `super_admin`.
2. `/admin/clients` → click `Crear demo seedeado` (top right).
3. Confirm. The endpoint creates: 1 demo org (KYB approved), 1 client_admin
   user, 2 transactions (onramp + subscribe) and 1 active position with 30
   days of accrual.
4. The new org appears in the list. Click → preview the seeded data.

Programmatic: `POST /api/v1/admin/ops/seed-demo-client` body
`{"legal_name": "Demo Holdings X", "auto_approve": true, "seed_history": true}`.

---

## 12. Rotate the MFA encryption key

`MFA_FERNET_KEY` encrypts the TOTP secrets at rest. Rotate every 12 months:

1. Generate a new key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. Add it to `.env` as `MFA_FERNET_KEY_NEW`.
3. Run the migration script `python -m backend.scripts.rotate_mfa_key`
   (TODO: write this script — it decrypts with old key, re-encrypts with
   new, swaps the two env vars).
4. Drop `MFA_FERNET_KEY_NEW`.

---

## Escalation matrix

| Severity | Symptom                                | Owner                    | SLA   |
|----------|----------------------------------------|--------------------------|-------|
| P0       | API completamente caída                | dev oncall               | 15min |
| P0       | Datos de clientes expuestos            | CISO + legal             | 30min |
| P1       | Webhook delivery > 10% fail rate       | dev oncall               | 1h    |
| P1       | KYC pendiente > 24h                    | compliance oncall        | 2h    |
| P2       | Approval pendiente > 4h                | ops oncall               | 4h    |
| P2       | Cliente reporta UX bug                 | producto                 | 1d    |
| P3       | Pedido de feature                      | producto (backlog)       | n/a   |
