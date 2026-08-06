"""Phase 2 demo data — ~6 months of synthetic transactions, positions and accruals
so the dashboard charts have realistic shape. Idempotent: tags everything with
`is_demo: true` so it can be wiped without touching real data.

Each subscribe transaction also gets a `lifecycle` array of 6 steps mirroring
the production flow (Onramp → USDC conversion → Prosper trigger → Mint →
Position → Outbound webhook). Redeems get a shorter lifecycle (4 steps).
"""
from __future__ import annotations
import random
import secrets
from datetime import datetime, timedelta, timezone

from db import col, ORGANIZATIONS, POSITIONS, TRANSACTIONS
from models import Position, Transaction, utc_now, new_id


RNG_SEED = 20260512
DEMO_PRODUCT_ID = "prod_pros_180"
DEMO_USER_IDS = {
    "org_seed_alemany": "usr_seed_alemany_admin",
    "org_seed_finpact": "usr_seed_finpact_admin",
}
ASSET = "USDC"
STELLAR_ASSET_ISSUER = "GBPROSPERISSUER2026XYZ7K9L0M1N2O3P4Q5R6S7T8U9V0WPQR"
STELLAR_TREASURY     = "GBPROSPERTREASURY2026ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
STELLAR_REWARD_POOL  = "GBPROSPERREWARDS2026WSXEDCRFVTGBYHNUJMIKOLPQAZ234567"
STELLAR_FEES         = "GBPROSPERFEES2026QAZWSXEDCRFVTGBYHNUJMIKOLP345678"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _step(step_id, title, status, ts, details, payload=None):
    return {"step_id": step_id, "title": title, "status": status,
            "timestamp": _iso(ts), "details": details, "payload": payload}


def _hash():
    return secrets.token_hex(32)


def _build_subscribe_lifecycle(rng, *, day, amount, prosper_tx_id, position_id):
    fx = round(rng.uniform(1180, 1245), 2)
    fiat = round(amount * fx, 2)
    alfred_id = f"alf_{secrets.token_hex(6)}"
    coelsa_id = f"COE-{secrets.token_hex(4).upper()}"
    tx_hash   = _hash()
    ledger    = rng.randint(54_000_000, 56_000_000)
    fail_idx  = rng.choices([None, None, None, None, 5], weights=[80, 0, 0, 0, 20])[0]
    has_webhook = rng.random() < 0.55

    t = day
    steps = []
    steps.append(_step("onramp", "Onramp Alfred", "ok", t,
        {"provider": "Alfred", "fiat_currency": "ARS", "fiat_amount": fiat,
         "coelsa_id": coelsa_id, "alfred_id": alfred_id,
         "external_url": f"https://app.alfred.capital/tx/{alfred_id}"},
        {"alfred_response": {"id": alfred_id, "status": "credited",
                             "fiat": fiat, "fx": fx, "coelsa_id": coelsa_id}}))
    t = t + timedelta(seconds=rng.randint(45, 180))
    steps.append(_step("conversion", "Conversión a USDC", "ok", t,
        {"usdc_out": amount, "fx_applied": fx,
         "fee_alfred_usd": round(amount * 0.0035, 2),
         "destination_wallet": STELLAR_TREASURY}))
    t = t + timedelta(seconds=rng.randint(2, 8))
    steps.append(_step("trigger", "Trigger compra Prosper", "ok", t,
        {"endpoint": "POST /v1/users/deposit", "prosper_tx_id": prosper_tx_id,
         "response_status": 202},
        {"request": {"amount_usdc": amount, "product_id": DEMO_PRODUCT_ID,
                     "memo": prosper_tx_id},
         "response": {"accepted": True, "tx_id": prosper_tx_id}}))
    t = t + timedelta(seconds=rng.randint(8, 22))
    mint_ok = fail_idx != 4
    steps.append(_step("mint", "Mint token Prosper",
        "ok" if mint_ok else "error", t,
        {"tokens_minted": amount, "asset_code": "PROS",
         "asset_issuer": STELLAR_ASSET_ISSUER,
         "tx_hash": tx_hash, "ledger": ledger, "memo": prosper_tx_id,
         "stellar_url": f"https://stellar.expert/explorer/public/tx/{tx_hash}"}
        if mint_ok else {"error": "horizon timeout", "retry_in": "manual"}))
    if not mint_ok:
        steps.append(_step("position", "Posición creada", "pending", t,
                           {"reason": "Waiting for mint to confirm"}))
        steps.append(_step("webhook", "Webhook outbound",
                           "pending" if has_webhook else "skipped", t,
                           {"reason": "Waiting upstream"}))
        return steps

    t = t + timedelta(seconds=rng.randint(1, 4))
    steps.append(_step("position", "Posición creada", "ok", t,
        {"position_id": position_id, "product": "Term Staking 180d",
         "apr_bps": 850, "start": _iso(day),
         "maturity": _iso(day + timedelta(days=180))}))
    if has_webhook:
        t = t + timedelta(seconds=rng.randint(1, 6))
        wok = fail_idx != 5
        steps.append(_step("webhook", "Webhook outbound",
            "ok" if wok else "error", t,
            {"endpoint": "https://hooks.alemany.capital/prosper",
             "delivery": "delivered" if wok else "retrying",
             "response_code": 200 if wok else 504,
             "retry_count": 0 if wok else rng.randint(1, 3),
             "hmac_signature": "sha256=" + secrets.token_hex(16)},
            {"body": {"event": "position.created",
                      "prosper_tx_id": prosper_tx_id, "amount": amount}}))
    else:
        steps.append(_step("webhook", "Webhook outbound", "skipped", t,
                           {"reason": "No outbound webhook configured"}))
    return steps


def _build_redeem_lifecycle(rng, *, day, amount, prosper_tx_id):
    tx_hash = _hash()
    return [
        _step("trigger", "Trigger redeem", "ok", day,
              {"endpoint": "POST /v1/users/redeem", "amount": amount,
               "asset": ASSET, "prosper_tx_id": prosper_tx_id}),
        _step("burn", "Burn token Prosper", "ok",
              day + timedelta(seconds=rng.randint(5, 18)),
              {"tokens_burned": amount, "tx_hash": tx_hash,
               "memo": prosper_tx_id,
               "stellar_url": f"https://stellar.expert/explorer/public/tx/{tx_hash}"}),
        _step("offramp", "Offramp Alfred", "ok",
              day + timedelta(seconds=rng.randint(30, 180)),
              {"provider": "Alfred", "destination": "bank_account",
               "fiat_currency": "ARS",
               "fiat_amount": round(amount * rng.uniform(1180, 1245), 2)}),
        _step("settled", "Settled in client account", "ok",
              day + timedelta(minutes=rng.randint(5, 30)),
              {"settled_amount_usd": amount,
               "destination_wallet": STELLAR_TREASURY}),
    ]


async def seed_demo_transactions(days: int = 180):
    existing = await col(TRANSACTIONS).count_documents({"is_demo": True})
    if existing > 0:
        return {"skipped": True, "existing": existing}

    rng = random.Random(RNG_SEED)
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)

    orgs = await col(ORGANIZATIONS).find({"is_deleted": False}, {"_id": 0}).to_list(50)
    if not orgs:
        return {"skipped": True, "reason": "no orgs"}

    transactions: list[dict] = []
    positions:    list[dict] = []

    for day_offset in range(days):
        day = start + timedelta(days=day_offset)
        n_subs = rng.choices([0, 1, 2, 3, 4], weights=[20, 30, 25, 15, 10])[0]
        for _ in range(n_subs):
            org = rng.choice(orgs)
            amount = rng.choice([5_000, 10_000, 25_000, 50_000, 100_000, 250_000])
            pos_id  = f"pos_{new_id().split('_', 1)[1]}"
            tx_id   = f"tx_{new_id().split('_', 1)[1]}"
            tx_uuid = f"ptx_{new_id().split('_', 1)[1]}"
            tx_hash = _hash()
            positions.append(Position(
                position_id=pos_id, org_id=org["org_id"],
                user_id=DEMO_USER_IDS.get(org["org_id"]),
                product_id=DEMO_PRODUCT_ID, principal_usd=float(amount),
                apr_bps=850, accrued_interest=0.0, currency=ASSET,
                start=_iso(day), maturity=_iso(day + timedelta(days=180)),
                status="active", prosper_tx_id=tx_uuid,
                created_at=_iso(day), updated_at=_iso(day),
            ).model_dump() | {"is_demo": True})
            lifecycle = _build_subscribe_lifecycle(
                rng, day=day, amount=float(amount),
                prosper_tx_id=tx_uuid, position_id=pos_id)
            tx_status = "failed" if any(s["status"] == "error" for s in lifecycle) \
                        else "confirmed"
            transactions.append(Transaction(
                tx_id=tx_id, org_id=org["org_id"], prosper_tx_id=tx_uuid,
                type="subscribe", amount=float(amount), asset=ASSET,
                status=tx_status, related_position_id=pos_id, tx_hash=tx_hash,
                fee_amount=round(amount * 0.0010, 2), fee_currency=ASSET,
                memo=f"Subscribe PROS-180 day+{day_offset}",
                created_at=_iso(day), updated_at=_iso(day),
            ).model_dump() | {"is_demo": True, "lifecycle": lifecycle})

        n_red = rng.choices([0, 1, 2], weights=[60, 30, 10])[0]
        for _ in range(n_red):
            org = rng.choice(orgs)
            amount = rng.choice([5_000, 10_000, 25_000, 50_000])
            tx_id   = f"tx_{new_id().split('_', 1)[1]}"
            tx_uuid = f"ptx_{new_id().split('_', 1)[1]}"
            tx_hash = _hash()
            lifecycle = _build_redeem_lifecycle(
                rng, day=day, amount=float(amount), prosper_tx_id=tx_uuid)
            transactions.append(Transaction(
                tx_id=tx_id, org_id=org["org_id"], prosper_tx_id=tx_uuid,
                type="redeem", amount=float(amount), asset=ASSET,
                status="confirmed", tx_hash=tx_hash,
                fee_amount=round(amount * 0.0005, 2), fee_currency=ASSET,
                memo=f"Redeem day+{day_offset}",
                created_at=_iso(day), updated_at=_iso(day),
            ).model_dump() | {"is_demo": True, "lifecycle": lifecycle})

    if positions:
        await col(POSITIONS).insert_many(positions)
    if transactions:
        await col(TRANSACTIONS).insert_many(transactions)

    return {"positions": len(positions), "transactions": len(transactions)}


async def wipe_demo_transactions():
    res1 = await col(POSITIONS).delete_many({"is_demo": True})
    res2 = await col(TRANSACTIONS).delete_many({"is_demo": True})
    return {"positions_deleted": res1.deleted_count,
            "transactions_deleted": res2.deleted_count}
