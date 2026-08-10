"""Phase 1 demo seed — 1 super_admin + 2 orgs (Alemany approved, Finpact pending) + 1 client_admin each."""
from __future__ import annotations
from db import col, ORGANIZATIONS, USERS
from models import Organization, OrgCaps, User, utc_now
from roles import Role


SEED_USERS = {
    "super_admin": {
        "user_id": "usr_seed_super_admin",
        "email":   "admin@prosper.foundation",
        "role":    Role.super_admin.value,
        "org_id":  None,
        "first_name": "System", "last_name": "Admin",
        "status": "active",
    },
    "ops_admin": {
        "user_id": "usr_seed_ops_admin",
        "email":   "ops@prosper.foundation",
        "role":    Role.admin.value,
        "org_id":  None,
        "first_name": "Ops", "last_name": "Team",
        "status": "active",
    },
    "compliance_officer": {
        "user_id": "usr_seed_compliance",
        "email":   "compliance@prosper.foundation",
        "role":    Role.compliance_officer.value,
        "org_id":  None,
        "first_name": "Compliance", "last_name": "Officer",
        "status": "active",
    },
    "finance": {
        "user_id": "usr_seed_finance",
        "email":   "finance@prosper.foundation",
        "role":    Role.finance.value,
        "org_id":  None,
        "first_name": "Finance", "last_name": "Team",
        "status": "active",
    },
    "alemany_client_admin": {
        "user_id": "usr_seed_alemany_admin",
        "email":   "client.admin@alemany.capital",
        "role":    Role.client_admin.value,
        "org_id":  "org_seed_alemany",
        "first_name": "Sofía", "last_name": "Alemany",
        "status": "active",
    },
    "finpact_client_admin": {
        "user_id": "usr_seed_finpact_admin",
        "email":   "client.admin@finpact.io",
        "role":    Role.client_admin.value,
        "org_id":  "org_seed_finpact",
        "first_name": "Diego", "last_name": "Vázquez",
        "status": "invited",
    },
}

SEED_ORGS = {
    "org_seed_alemany": Organization(
        org_id="org_seed_alemany",
        legal_name="Alemany Capital S.A.",
        commercial_name="Alemany Capital",
        country="AR",
        primary_email="client.admin@alemany.capital",
        type="family_office",
        kyb_status="approved",
        risk_score=18, risk_profile="low",
        allowlist_domains=["alemany.capital"],
        caps=OrgCaps(subscribe_daily_cap_usd=250_000, subscribe_monthly_cap_usd=2_000_000,
                     redeem_daily_cap_usd=150_000, redeem_monthly_cap_usd=1_000_000),
        stellar_address="GA…ALEMANY",
        expected_aum_usd=1_500_000,
        internal_notes="Seed org · approved · used for happy-path tests.",
    ).model_dump(),
    "org_seed_finpact": Organization(
        org_id="org_seed_finpact",
        legal_name="Finpact LLC",
        commercial_name="Finpact",
        country="UY",
        primary_email="client.admin@finpact.io",
        type="fintech",
        kyb_status="pending",
        risk_score=62, risk_profile="medium",
        allowlist_domains=["finpact.io"],
        caps=OrgCaps(),
        expected_aum_usd=600_000,
        internal_notes="Seed org · KYB in progress.",
    ).model_dump(),
}


async def seed_phase1():
    """Idempotent — safe to run on every boot."""
    for org_id, doc in SEED_ORGS.items():
        d = {k: v for k, v in doc.items() if k != "created_at"}
        await col(ORGANIZATIONS).update_one(
            {"org_id": org_id},
            {"$set": {**d, "updated_at": utc_now()},
             "$setOnInsert": {"created_at": utc_now()}},
            upsert=True,
        )
    for key, payload in SEED_USERS.items():
        doc = User(**payload).model_dump()
        d = {k: v for k, v in doc.items() if k != "created_at"}
        await col(USERS).update_one(
            {"email": doc["email"]},
            {"$set": {**d, "updated_at": utc_now()},
             "$setOnInsert": {"created_at": utc_now()}},
            upsert=True,
        )
    return {"orgs": list(SEED_ORGS), "users": list(SEED_USERS)}
