"""Demo seed data for the Prosper platform.

All seeded documents include `is_demo: True` so the UI can display a DEMO
banner and allow the operator to wipe demo data without affecting real data.
"""
from __future__ import annotations
from datetime import timedelta
import random
import hashlib
import uuid
from db import (
    col, ORGANIZATIONS, ONBOARDING, COMPLIANCE, FUNDS, PRODUCTS, NAV_SNAPSHOTS,
    TREASURY, POSITIONS, TRANSACTIONS, RECONCILIATION, API_APPS, API_KEYS,
    WEBHOOK_ENDPOINTS, WEBHOOK_DELIVERIES, ALERTS, REPORTS, AUDIT_LOGS,
    END_CUSTOMERS, ORG_USERS
)
from models import now_utc, new_id

DEMO_TAG = {"is_demo": True}


async def wipe_demo():
    """Delete every demo-tagged document across all collections."""
    for c in [ORGANIZATIONS, ONBOARDING, COMPLIANCE, FUNDS, PRODUCTS, NAV_SNAPSHOTS,
              TREASURY, POSITIONS, TRANSACTIONS, RECONCILIATION, API_APPS, API_KEYS,
              WEBHOOK_ENDPOINTS, WEBHOOK_DELIVERIES, ALERTS, REPORTS, AUDIT_LOGS,
              END_CUSTOMERS, ORG_USERS]:
        await col(c).delete_many({"is_demo": True})


async def seed_all(force: bool = False):
    """Seed demo data. If force=True, wipe existing demo data first."""
    if force:
        await wipe_demo()
    existing = await col(FUNDS).count_documents({"is_demo": True})
    if existing > 0 and not force:
        return {"status": "already_seeded"}

    now = now_utc()

    # ---- Organizations (partners + institutional) ----
    orgs = [
        {"org_id": f"org_{new_id()}", "name": "Alemany Capital", "legal_name": "Alemany Capital LLC",
         "type": "partner", "country": "AR", "contact_email": "ops@alemany.capital",
         "environment": "production", "status": "active", "aum_usd": 12_500_000,
         "active_investors": 342, "is_demo": True, "created_at": now.isoformat()},
        {"org_id": f"org_{new_id()}", "name": "Beachside Wealth", "legal_name": "Beachside Wealth Ltd",
         "type": "institutional", "country": "UY", "contact_email": "partners@beachside.uy",
         "environment": "production", "status": "active", "aum_usd": 8_200_000,
         "active_investors": 198, "is_demo": True, "created_at": now.isoformat()},
        {"org_id": f"org_{new_id()}", "name": "Quirón Markets", "legal_name": "Quirón Markets SA",
         "type": "partner", "country": "AR", "contact_email": "team@quironmarkets.com",
         "environment": "production", "status": "active", "aum_usd": 21_400_000,
         "active_investors": 512, "is_demo": True, "created_at": now.isoformat()},
        {"org_id": f"org_{new_id()}", "name": "Meridian Sandbox Co", "legal_name": "Meridian Sandbox Co",
         "type": "partner", "country": "BR", "contact_email": "dev@meridian.io",
         "environment": "sandbox", "status": "active", "aum_usd": 250_000,
         "active_investors": 12, "is_demo": True, "created_at": now.isoformat()},
        {"org_id": f"org_{new_id()}", "name": "Andes Trust", "legal_name": "Andes Trust SpA",
         "type": "institutional", "country": "CL", "contact_email": "it@andestrust.cl",
         "environment": "production", "status": "pending", "aum_usd": 0,
         "active_investors": 0, "is_demo": True, "created_at": now.isoformat()},
    ]
    await col(ORGANIZATIONS).insert_many([dict(o) for o in orgs])

    # ---- Funds + Products ----
    fund = {
        "fund_id": f"fund_{new_id()}", "code": "PROS", "name": "Prosper Yield",
        "underlying": "Quirón PyMEs", "issuer_address": "GISSUER...XYZABC",
        "treasury_address": "GTREAS...DEF123", "home_domain": "prosper.foundation",
        "total_supply": 45_000_000, "circulating_supply": 42_350_000,
        "nav_per_token": 1.0000, "currency": "USD", "status": "active",
        "regulator": "CNV Argentina", "rating": "Moody's Local AA",
        "environment": "production", "is_demo": True,
        "created_at": now.isoformat(),
    }
    fund_sbx = {**fund, "fund_id": f"fund_{new_id()}", "environment": "sandbox",
                "total_supply": 1_000_000, "circulating_supply": 350_000}
    await col(FUNDS).insert_many([dict(fund), dict(fund_sbx)])

    products = []
    for (days, apr) in [(30, 450), (90, 625), (180, 825), (365, 1100)]:
        products.append({
            "product_id": f"prod_{new_id()}", "fund_id": fund["fund_id"],
            "name": f"PROS Term {days}d",
            "kind": "term_staking", "term_days": days, "apr_bps": apr,
            "min_amount": 100, "payout_asset": "USDC", "principal_asset": "PROS",
            "status": "active", "is_demo": True, "created_at": now.isoformat(),
        })
    products.append({
        "product_id": f"prod_{new_id()}", "fund_id": fund["fund_id"],
        "name": "PROS Liquid", "kind": "liquid", "term_days": None, "apr_bps": 300,
        "min_amount": 50, "payout_asset": "USDC", "principal_asset": "PROS",
        "status": "active", "is_demo": True, "created_at": now.isoformat(),
    })
    await col(PRODUCTS).insert_many([dict(p) for p in products])

    # ---- NAV snapshots (14 days) ----
    snapshots = []
    for d in range(14, 0, -1):
        snapshots.append({
            "snapshot_id": f"nav_{new_id()}", "fund_id": fund["fund_id"],
            "as_of": (now - timedelta(days=d)).isoformat(),
            "nav_per_token": round(1.0 + (14 - d) * 0.00021 + random.uniform(-0.0001, 0.0001), 6),
            "total_supply": fund["total_supply"] - (d * 45_000),
            "is_demo": True,
        })
    await col(NAV_SNAPSHOTS).insert_many(snapshots)

    # ---- Treasury accounts ----
    treas = [
        {"account_id": f"acc_{new_id()}", "label": "Issuer (Cold)", "kind": "issuer",
         "fund_id": fund["fund_id"], "stellar_address": "GISSUER...XYZABC",
         "balance_native": 50.0, "balance_asset": 0.0, "asset_code": "PROS",
         "environment": "production", "custody": "cold", "is_demo": True},
        {"account_id": f"acc_{new_id()}", "label": "Treasury Operational", "kind": "treasury",
         "fund_id": fund["fund_id"], "stellar_address": "GTREAS...DEF123",
         "balance_native": 1250.0, "balance_asset": 2_650_000, "asset_code": "PROS",
         "environment": "production", "custody": "warm", "is_demo": True},
        {"account_id": f"acc_{new_id()}", "label": "Reward Pool 90d", "kind": "reward_pool",
         "fund_id": fund["fund_id"], "stellar_address": "GREWARD...ABC456",
         "balance_native": 100.0, "balance_asset": 125_000, "asset_code": "USDC",
         "environment": "production", "custody": "warm", "is_demo": True},
        {"account_id": f"acc_{new_id()}", "label": "Fee Collection", "kind": "fee",
         "fund_id": fund["fund_id"], "stellar_address": "GFEE...789",
         "balance_native": 30.0, "balance_asset": 18_420, "asset_code": "USDC",
         "environment": "production", "custody": "hot", "is_demo": True},
    ]
    await col(TREASURY).insert_many([dict(t) for t in treas])

    # ---- Onboarding cases ----
    ob_statuses = ["submitted", "under_review", "approved", "needs_info", "rejected"]
    onboarding = []
    for i in range(18):
        ob_id = f"case_{new_id()}"
        s = random.choice(ob_statuses)
        onboarding.append({
            "case_id": ob_id,
            "org_id": random.choice([o["org_id"] for o in orgs]),
            "applicant_name": random.choice([
                "Sofía Ramírez", "Matías López", "Isabella Fernández", "Carlos Mendoza",
                "Ana Gutiérrez", "Diego Silva", "Valeria Castro", "Federico Navarro",
                "Camila Torres", "Joaquín Díaz", "Lucía Paredes", "Tomás Vega"]) + f" #{i+1:02d}",
            "applicant_email": f"applicant{i+1}@demo.prosper.io",
            "applicant_type": random.choice(["individual", "entity"]),
            "country": random.choice(["AR", "UY", "BR", "CL", "MX"]),
            "status": s,
            "assigned_to": None,
            "sla_due": (now + timedelta(hours=random.randint(2, 72))).isoformat(),
            "risk_score": round(random.uniform(0.1, 0.85), 2),
            "progress": {"submitted": 20, "under_review": 55, "approved": 100,
                         "needs_info": 40, "rejected": 100}[s],
            "is_demo": True,
            "created_at": (now - timedelta(hours=random.randint(1, 240))).isoformat(),
            "updated_at": now.isoformat(),
        })
        # Add a compliance review for each
        await col(COMPLIANCE).insert_one({
            "review_id": f"rev_{new_id()}", "case_id": ob_id,
            "kyc_status": random.choice(["pending", "approved", "escalated"]),
            "aml_check": random.choice(["pending", "approved"]),
            "sanctions_check": "approved",
            "pep_check": random.choice(["pending", "approved"]),
            "travel_rule": random.choice(["pending", "approved"]),
            "decision": "approved" if s == "approved" else "pending",
            "is_demo": True, "created_at": now.isoformat(),
        })
    await col(ONBOARDING).insert_many(onboarding)

    # ---- Positions (only for approved orgs) ----
    positions = []
    for i in range(35):
        p = random.choice(products)
        org = random.choice(orgs[:3])
        principal = round(random.uniform(500, 50000), 2)
        start = now - timedelta(days=random.randint(1, 60))
        maturity = start + timedelta(days=p.get("term_days") or 365)
        accrued = round(principal * (p["apr_bps"] / 10000) * ((now - start).days / 365), 2)
        positions.append({
            "position_id": f"pos_{new_id()}",
            "org_id": org["org_id"],
            "user_reference_id": f"user_ref_{i+1:04d}",
            "product_id": p["product_id"], "fund_id": fund["fund_id"],
            "principal": principal, "accrued_interest": accrued, "claimed_interest": 0.0,
            "start_date": start.isoformat(),
            "maturity_date": maturity.isoformat(),
            "status": random.choice(["active", "active", "active", "pending", "matured"]),
            "stellar_address": f"GUSER{i:03d}ABC...XYZ",
            "is_demo": True, "created_at": start.isoformat(),
        })
    await col(POSITIONS).insert_many(positions)

    # ---- Transactions + Reconciliation ----
    tx_types = ["mint", "subscribe", "redeem", "transfer", "deposit", "claim", "fund"]
    txs = []
    recs = []
    for i in range(120):
        p_tx = str(uuid.uuid4())
        t = random.choice(tx_types)
        tx = {
            "tx_id": f"tx_{new_id()}", "prosper_tx_id": p_tx,
            "org_id": random.choice([o["org_id"] for o in orgs[:3]]),
            "user_reference_id": f"user_ref_{random.randint(1, 35):04d}",
            "fund_id": fund["fund_id"],
            "type": t,
            "amount": round(random.uniform(50, 50000), 2),
            "asset_code": random.choice(["PROS", "PROS", "USDC"]),
            "from_address": "GTREAS...DEF123" if t in ["subscribe", "deposit"] else f"GUSER{i:03d}",
            "to_address": f"GUSER{i:03d}" if t in ["subscribe", "deposit"] else "GTREAS...DEF123",
            "memo": p_tx,
            "tx_hash": hashlib.sha256(p_tx.encode()).hexdigest(),
            "ledger": 50_000_000 + i,
            "status": random.choice(["confirmed", "confirmed", "confirmed", "pending", "failed"]),
            "environment": "production",
            "is_demo": True,
            "created_at": (now - timedelta(hours=random.randint(0, 480))).isoformat(),
        }
        txs.append(tx)
        # Reconciliation record for most
        matched = tx["status"] == "confirmed"
        recs.append({
            "recon_id": f"rec_{new_id()}", "prosper_tx_id": p_tx,
            "onchain_match": matched, "offchain_match": True,
            "tx_hash": tx["tx_hash"],
            "discrepancy": None if matched else "pending_confirmation",
            "status": "matched" if matched else "investigating",
            "is_demo": True, "created_at": tx["created_at"],
        })
    await col(TRANSACTIONS).insert_many(txs)
    await col(RECONCILIATION).insert_many(recs)

    # ---- API Apps + Keys + Webhooks ----
    apps = []
    keys = []
    hooks = []
    for o in orgs[:3]:
        app_id = f"app_{new_id()}"
        apps.append({
            "app_id": app_id, "org_id": o["org_id"], "name": f"{o['name']} Prod Integration",
            "description": "Default production app", "environment": "production",
            "status": "active", "is_demo": True, "created_at": now.isoformat(),
        })
        apps.append({
            "app_id": f"app_{new_id()}", "org_id": o["org_id"], "name": f"{o['name']} Sandbox",
            "description": "Sandbox for development", "environment": "sandbox",
            "status": "active", "is_demo": True, "created_at": now.isoformat(),
        })
        key_raw = f"pk_live_{new_id()}{new_id()}"
        keys.append({
            "key_id": f"key_{new_id()}", "app_id": app_id, "org_id": o["org_id"],
            "label": "Primary Key", "key_prefix": key_raw[:12] + "...",
            "key_hash": hashlib.sha256(key_raw.encode()).hexdigest(),
            "scopes": ["read:positions", "write:transactions", "read:funds"],
            "environment": "production", "status": "active",
            "last_used_at": (now - timedelta(hours=random.randint(1, 48))).isoformat(),
            "is_demo": True, "created_at": now.isoformat(),
        })
        hooks.append({
            "endpoint_id": f"hook_{new_id()}", "app_id": app_id, "org_id": o["org_id"],
            "url": f"https://{o['name'].lower().replace(' ', '')}.example.com/hooks/prosper",
            "events": ["transaction.confirmed", "position.matured", "onboarding.approved"],
            "secret_prefix": "whsec_" + new_id(),
            "status": "active", "environment": "production",
            "is_demo": True, "created_at": now.isoformat(),
        })
    await col(API_APPS).insert_many(apps)
    await col(API_KEYS).insert_many(keys)
    await col(WEBHOOK_ENDPOINTS).insert_many(hooks)

    deliveries = []
    for h in hooks:
        for i in range(6):
            deliveries.append({
                "delivery_id": f"del_{new_id()}", "endpoint_id": h["endpoint_id"],
                "event_type": random.choice(h["events"]),
                "payload": {"txId": str(uuid.uuid4()), "amount": random.randint(100, 5000)},
                "response_status": random.choice([200, 200, 200, 500, 404]),
                "attempt": 1, "delivered": True, "is_demo": True,
                "created_at": (now - timedelta(hours=random.randint(0, 72))).isoformat(),
            })
    await col(WEBHOOK_DELIVERIES).insert_many(deliveries)

    # ---- Alerts ----
    alerts = [
        {"alert_id": f"al_{new_id()}", "severity": "critical", "kind": "treasury",
         "title": "Reward Pool 90d balance below threshold",
         "message": "Reward pool for 90d product is below 10% of expected payout next cycle.",
         "resolved": False, "is_demo": True, "created_at": now.isoformat()},
        {"alert_id": f"al_{new_id()}", "severity": "warning", "kind": "reconciliation",
         "title": "4 transactions pending reconciliation > 2h",
         "message": "Transactions submitted over 2 hours ago are still unreconciled.",
         "resolved": False, "is_demo": True, "created_at": now.isoformat()},
        {"alert_id": f"al_{new_id()}", "severity": "info", "kind": "onboarding",
         "title": "Onboarding SLA reminder",
         "message": "3 onboarding cases approaching 48h SLA.",
         "resolved": False, "is_demo": True, "created_at": now.isoformat()},
        {"alert_id": f"al_{new_id()}", "severity": "warning", "kind": "webhook",
         "title": "Webhook delivery failures",
         "message": "Alemany Capital webhook endpoint returning 500 for last 3 deliveries.",
         "resolved": False, "is_demo": True,
         "created_at": (now - timedelta(hours=2)).isoformat()},
    ]
    await col(ALERTS).insert_many(alerts)

    # ---- Reports ----
    reports = []
    for kind in ["daily_nav", "audit", "performance", "tax"]:
        for m in range(3):
            reports.append({
                "report_id": f"rep_{new_id()}", "kind": kind,
                "period": f"2026-{2 - m:02d}", "status": "ready",
                "download_url": "#",
                "is_demo": True, "created_at": now.isoformat(),
            })
    await col(REPORTS).insert_many(reports)

    # ---- Audit logs ----
    audits = []
    actions = ["user.login", "onboarding.approve", "fund.create", "tx.submit",
               "apikey.rotate", "webhook.enable", "position.redeem", "settings.update"]
    for i in range(40):
        audits.append({
            "audit_id": f"aud_{new_id()}",
            "actor_id": "user_demo",
            "actor_email": random.choice([
                "ops@prosper.foundation", "compliance@prosper.foundation",
                "finance@prosper.foundation", "dev@alemany.capital"
            ]),
            "action": random.choice(actions),
            "resource": random.choice(["fund", "transaction", "api_key", "user", "webhook"]),
            "resource_id": new_id(),
            "environment": random.choice(["production", "sandbox"]),
            "ip": f"{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}",
            "created_at": (now - timedelta(hours=random.randint(0, 240))).isoformat(),
            "metadata": {}, "is_demo": True,
        })
    await col(AUDIT_LOGS).insert_many(audits)

    # ---- End Customers (for partners) ----
    ecs = []
    for i in range(24):
        o = random.choice(orgs[:3])
        ecs.append({
            "end_customer_id": f"ec_{new_id()}", "org_id": o["org_id"],
            "external_ref": f"CUST-{1000+i}",
            "name": f"End Customer {i+1:03d}",
            "email": f"customer{i+1}@{o['name'].lower().replace(' ', '')}.com",
            "country": random.choice(["AR", "UY", "BR", "CL", "MX"]),
            "kyc_status": random.choice(["pending", "approved", "approved"]),
            "total_invested": round(random.uniform(500, 80000), 2),
            "is_demo": True, "created_at": now.isoformat(),
        })
    await col(END_CUSTOMERS).insert_many(ecs)

    return {"status": "seeded", "orgs": len(orgs), "tx": len(txs),
            "positions": len(positions), "alerts": len(alerts)}
