"""Phase 5 — Compliance seeds.

Idempotent. Creates:
  - 5 KYC pending cases (individuals)
  - 3 KYB pending cases (orgs with UBO list + checklist=8 unchecked)
  - 7 platform-wide KYT rules with sensible defaults
  - ~25 KYT alerts spread across recent transactions
  - Risk scores for every org in `organizations`
  - 12 generic alerts feed entries (mix of severities)
  - 4 watchlist entries (3 wallets + 1 client)
"""
from __future__ import annotations

import random
import secrets
from datetime import datetime, timedelta, timezone

from db import (
    col,
    ALERTS, KYB_CASES, KYC_CASES, KYT_ALERTS, KYT_RULES, ORGANIZATIONS,
    RISK_SCORES, TRANSACTIONS, USERS, WATCHLIST,
)

random.seed(20260513)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Default KYT rules — platform-wide, editable from /admin/compliance/kyt
# ---------------------------------------------------------------------------
DEFAULT_KYT_RULES = [
    {"rule_id": "kyt_daily_cap",     "name": "Umbral diario por cliente",
     "description": "Volumen acumulado de un cliente en 24h supera el umbral.",
     "enabled": True,  "param_name": "threshold_usd", "param_value": 100_000,
     "param_unit": "USD", "severity": "warning"},
    {"rule_id": "kyt_monthly_cap",   "name": "Umbral mensual por cliente",
     "description": "Volumen acumulado de un cliente en 30d supera el umbral.",
     "enabled": True,  "param_name": "threshold_usd", "param_value": 2_000_000,
     "param_unit": "USD", "severity": "warning"},
    {"rule_id": "kyt_unusual_amount", "name": "Monto inusual",
     "description": "Una tx supera el X% del ticket promedio histórico del cliente.",
     "enabled": True,  "param_name": "above_avg_pct", "param_value": 400,
     "param_unit": "%", "severity": "warning"},
    {"rule_id": "kyt_high_frequency", "name": "Frecuencia anómala",
     "description": "Más de X transacciones por hora para un mismo cliente.",
     "enabled": True,  "param_name": "tx_per_hour", "param_value": 12,
     "param_unit": "tx/h", "severity": "info"},
    {"rule_id": "kyt_new_client_big", "name": "Cliente nuevo + monto alto",
     "description": "Tx > umbral durante los primeros 7 días del cliente.",
     "enabled": True,  "param_name": "threshold_usd", "param_value": 50_000,
     "param_unit": "USD", "severity": "critical"},
    {"rule_id": "kyt_multi_recipients", "name": "Multiples contrapartes",
     "description": "Transferencias a más de X wallets distintas en 24h.",
     "enabled": True,  "param_name": "n_wallets", "param_value": 5,
     "param_unit": "wallets", "severity": "warning"},
    {"rule_id": "kyt_geo_risk",      "name": "Riesgo geográfico",
     "description": "Tx originada en IP de jurisdicción restringida.",
     "enabled": True,  "param_name": "jurisdictions",
     "param_value": "IR,KP,SY,CU,RU",
     "param_unit": "ISO2 csv", "severity": "critical"},
]

# ---------------------------------------------------------------------------
# KYC pending — 5 individuals (mock docs, scores from Sumsub-style provider)
# ---------------------------------------------------------------------------
KYC_NAMES = [
    ("María",   "González", "AR", "DNI-AR-12.345.678"),
    ("Juan",    "Pérez",    "UY", "CI-UY-1.234.567-8"),
    ("Sofía",   "Rivera",   "MX", "INE-MX-RIVR890101"),
    ("Andrés",  "López",    "CO", "CC-CO-1234567890"),
    ("Camila",  "Torres",   "CL", "RUT-CL-12.345.678-9"),
]
PROVIDERS = ["aiprise", "sumsub"]


def _make_kyc_case(i: int) -> dict:
    fn, ln, country, doc_id = KYC_NAMES[i]
    applied_at = _now() - timedelta(hours=random.randint(2, 36))
    score = random.randint(55, 92)
    sla_hours_left = max(0.5, 24 - (_now() - applied_at).total_seconds() / 3600)
    flags = random.sample(
        ["doc_quality_ok", "liveness_pass", "address_match",
         "minor_age_alert", "selfie_blurry", "id_expired_soon",
         "pep_no_match", "sanctions_no_match"],
        k=random.randint(3, 5),
    )
    checks = {
        "aml":         random.choice(["pass", "manual_review"]),
        "sanctions":   "pass",
        "pep":         "pass",
        "travel_rule": random.choice(["pass", "pending"]),
    }
    return {
        "case_id":    f"kyc_seed_{i+1:02d}",
        "first_name": fn, "last_name": ln,
        "email":      f"{fn.lower()}.{ln.lower()}@example.com",
        "country":    country,
        "doc_id":     doc_id,
        "doc_type":   "national_id",
        "documents": [
            {"label": "DNI front",        "kind": "image",
             "url": f"https://placehold.co/720x460/0B0F19/F2F6FF/png?text=DNI+FRONT+{i+1}"},
            {"label": "DNI back",         "kind": "image",
             "url": f"https://placehold.co/720x460/0B0F19/F2F6FF/png?text=DNI+BACK+{i+1}"},
            {"label": "Selfie liveness",  "kind": "image",
             "url": f"https://placehold.co/520x520/0B0F19/2563FF/png?text=SELFIE+{i+1}"},
            {"label": "Proof of address", "kind": "pdf",
             "url": "https://placehold.co/720x920/F2F6FF/0B0F19/png?text=Proof+of+address"},
        ],
        "provider":   random.choice(PROVIDERS),
        "provider_score":      score,
        "provider_confidence": round(score / 100, 2),
        "provider_flags":      flags,
        "checks":     checks,
        "status":     "in_review" if i < 3 else "pending",
        "applied_at": _iso(applied_at),
        "sla_hours_left": round(sla_hours_left, 1),
        "org_id":     random.choice(["org_seed_alemany", "org_seed_finpact"]),
        "timeline":   [{
            "ts": _iso(applied_at), "by": "system",
            "what": "case_created", "meta": {}}],
        "is_deleted": False,
        "created_at": _iso(applied_at), "updated_at": _iso(applied_at),
    }


# ---------------------------------------------------------------------------
# KYB pending — 3 corporates with UBO list + 8-item checklist
# ---------------------------------------------------------------------------
KYB_CORPS = [
    ("Helix Capital S.A.",  "Helix Capital", "AR", "fintech",     "30-71234567-8"),
    ("Acme Holdings Ltd.",  "Acme",          "UK", "investment_co","UK-12345678"),
    ("Sunrise Funds LLC",   "Sunrise",       "US", "fund_manager","EIN-12-3456789"),
]
DEFAULT_CHECKLIST = [
    {"key": "certificate",       "label": "Certificado verificado",                  "checked": False},
    {"key": "board_resolution",  "label": "Board resolution válido",                 "checked": False},
    {"key": "ubo_list",          "label": "UBO list completo y verificado",          "checked": False},
    {"key": "address_proof",     "label": "Proof of address vigente (<3 meses)",     "checked": False},
    {"key": "financials",        "label": "Estados financieros revisados",           "checked": False},
    {"key": "sanctions",         "label": "Sanctions check pasado",                  "checked": False},
    {"key": "sectoral_risk",     "label": "Sectoral risk evaluado",                  "checked": False},
    {"key": "ownership_chart",   "label": "Ownership chart verificado",              "checked": False},
]


def _make_kyb_case(i: int) -> dict:
    legal, commercial, country, biz_type, tax_id = KYB_CORPS[i]
    applied_at = _now() - timedelta(hours=random.randint(6, 60))
    score = random.randint(62, 88)
    ubos = [
        {"name": "Diego López",      "ownership_pct": 45, "nationality": "AR",
         "is_pep": False, "verified": False},
        {"name": "Florencia García", "ownership_pct": 35, "nationality": "ES",
         "is_pep": True,  "verified": False},
        {"name": "Mariana Costa",    "ownership_pct": 20, "nationality": "BR",
         "is_pep": False, "verified": False},
    ]
    # Helix (i==0) starts with checklist 6/8 done so user can finish + approve.
    checklist = [dict(c) for c in DEFAULT_CHECKLIST]
    if i == 0:
        for c in checklist:
            if c["key"] not in ("ownership_chart", "ubo_list"):
                c["checked"] = True
    return {
        "case_id":     f"kyb_seed_{i+1:02d}",
        "legal_name":  legal, "commercial_name": commercial,
        "country":     country, "type": biz_type, "tax_id": tax_id,
        "incorporation_date": "2019-03-15",
        "documents": [
            {"label": "Certificate of incorporation",  "kind": "pdf",
             "url": "https://placehold.co/720x920/F2F6FF/0B0F19/png?text=Incorporation+Certificate"},
            {"label": "Board resolution",              "kind": "pdf",
             "url": "https://placehold.co/720x920/F2F6FF/0B0F19/png?text=Board+Resolution"},
            {"label": "Proof of address",              "kind": "pdf",
             "url": "https://placehold.co/720x920/F2F6FF/0B0F19/png?text=Proof+of+address"},
            {"label": "Financial statements",          "kind": "pdf",
             "url": "https://placehold.co/720x920/F2F6FF/0B0F19/png?text=Financials"},
            {"label": "Ownership structure chart",     "kind": "image",
             "url": "https://placehold.co/960x540/F2F6FF/0B0F19/png?text=Ownership+Chart"},
        ],
        "ubos":        ubos,
        "checklist":   checklist,
        "provider":    "aiprise",
        "provider_score": score,
        "provider_confidence": round(score / 100, 2),
        "provider_flags": ["company_active", "no_sanctions_match",
                            "ubo_pep_match" if i in (1,) else "ubo_clean"],
        "checks":      {"aml": "pass", "sanctions": "pass",
                         "pep": "manual_review" if i == 1 else "pass",
                         "travel_rule": "n/a"},
        "status":      "in_review" if i == 0 else "pending",
        "applied_at":  _iso(applied_at),
        "sla_hours_left": round(max(0.5, 48 - (_now() - applied_at).total_seconds() / 3600), 1),
        "org_id":      None,  # not yet onboarded as an org
        "timeline":    [{"ts": _iso(applied_at), "by": "system",
                          "what": "case_created", "meta": {}}],
        "is_deleted":  False,
        "created_at":  _iso(applied_at), "updated_at": _iso(applied_at),
    }


# ---------------------------------------------------------------------------
# Risk score calculator — composes 4 drivers per spec (KYC freshness, volume,
# geography, behavior) into a 0-100 score with explanations.
# ---------------------------------------------------------------------------
def _risk_drivers_for(org: dict, volume: float, last_kyc_days: int) -> list:
    drivers = []
    # KYC freshness (30%)
    if last_kyc_days >= 365:
        drivers.append({"key": "kyc", "label": "KYC > 12 meses", "weight": 30, "score": 28})
    elif last_kyc_days >= 180:
        drivers.append({"key": "kyc", "label": "KYC > 6 meses", "weight": 30, "score": 18})
    else:
        drivers.append({"key": "kyc", "label": "KYC reciente", "weight": 30, "score": 6})
    # Volume (25%)
    if volume > 2_000_000:
        drivers.append({"key": "volume", "label": "Alto volumen 30d", "weight": 25, "score": 22})
    elif volume > 500_000:
        drivers.append({"key": "volume", "label": "Volumen medio 30d", "weight": 25, "score": 12})
    else:
        drivers.append({"key": "volume", "label": "Volumen bajo 30d", "weight": 25, "score": 4})
    # Geography (25%)
    country = (org.get("country") or "AR").upper()
    if country in ("AR", "UY", "CL", "BR", "MX", "CO"):
        drivers.append({"key": "geo", "label": f"Jurisdicción {country} · OK", "weight": 25, "score": 6})
    elif country in ("IR", "KP", "SY", "CU", "RU"):
        drivers.append({"key": "geo", "label": f"Jurisdicción {country} · restringida", "weight": 25, "score": 25})
    else:
        drivers.append({"key": "geo", "label": f"Jurisdicción {country}", "weight": 25, "score": 10})
    # Behavior (20%) — random for demo
    behavior = random.randint(2, 16)
    drivers.append({"key": "behavior", "label": "Patrón comportamiento",
                     "weight": 20, "score": behavior})
    return drivers


def _profile_for(score: int) -> str:
    if score >= 75: return "critical"
    if score >= 50: return "high"
    if score >= 25: return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Main entrypoint — call from server startup
# ---------------------------------------------------------------------------
async def seed_compliance() -> dict:
    summary = {"kyt_rules": 0, "kyc_cases": 0, "kyb_cases": 0,
               "kyt_alerts": 0, "risk_scores": 0, "alerts": 0,
               "watchlist": 0}

    # KYT rules
    for r in DEFAULT_KYT_RULES:
        await col(KYT_RULES).update_one(
            {"rule_id": r["rule_id"]},
            {"$set": {**r, "updated_at": _iso(_now())},
             "$setOnInsert": {"created_at": _iso(_now())}},
            upsert=True,
        )
        summary["kyt_rules"] += 1

    # KYC cases (idempotent: only insert when missing)
    for i in range(len(KYC_NAMES)):
        cid = f"kyc_seed_{i+1:02d}"
        if not await col(KYC_CASES).find_one({"case_id": cid}):
            await col(KYC_CASES).insert_one(_make_kyc_case(i))
            summary["kyc_cases"] += 1

    # KYB cases
    for i in range(len(KYB_CORPS)):
        cid = f"kyb_seed_{i+1:02d}"
        if not await col(KYB_CASES).find_one({"case_id": cid}):
            await col(KYB_CASES).insert_one(_make_kyb_case(i))
            summary["kyb_cases"] += 1

    # KYT alerts — pick ~25 recent txs and attach 1 random rule trigger
    if await col(KYT_ALERTS).estimated_document_count() == 0:
        sample_txs = await col(TRANSACTIONS).aggregate([
            {"$match": {"is_deleted": False, "status": "confirmed"}},
            {"$sample": {"size": 25}},
        ]).to_list(25)
        for tx in sample_txs:
            rule = random.choice(DEFAULT_KYT_RULES)
            sev  = rule["severity"]
            await col(KYT_ALERTS).insert_one({
                "alert_id":   f"kyt_{secrets.token_hex(5)}",
                "rule_id":    rule["rule_id"],
                "rule_name":  rule["name"],
                "severity":   sev,
                "status":     random.choice(["open", "acknowledged", "open", "open"]),
                "tx_id":      tx.get("tx_id"),
                "prosper_tx_id": tx.get("prosper_tx_id"),
                "org_id":     tx.get("org_id"),
                "amount":     tx.get("amount"),
                "score":      random.randint(55, 95),
                "assigned_to": None,
                "context":    {"trigger": "seed", "matched_param": rule["param_value"]},
                "created_at": tx.get("created_at"),
                "updated_at": _iso(_now()),
                "is_deleted": False,
            })
            summary["kyt_alerts"] += 1

    # Risk scores for every org
    orgs = await col(ORGANIZATIONS).find(
        {"is_deleted": False}, {"_id": 0}).to_list(2000)
    for o in orgs:
        oid = o["org_id"]
        # last 30d volume
        agg = await col(TRANSACTIONS).aggregate([
            {"$match": {"is_deleted": False, "org_id": oid, "status": "confirmed",
                         "created_at": {"$gte": _iso(_now() - timedelta(days=30))}}},
            {"$group": {"_id": None, "v": {"$sum": "$amount"}}},
        ]).to_list(1)
        volume = (agg[0]["v"] if agg else 0)
        last_kyc_days = random.randint(0, 400)
        drivers = _risk_drivers_for(o, volume, last_kyc_days)
        score = sum(d["score"] for d in drivers)
        score = max(0, min(100, score))
        await col(RISK_SCORES).update_one(
            {"org_id": oid},
            {"$set": {
                "org_id":   oid,
                "name":     o.get("commercial_name") or o.get("legal_name") or oid,
                "score":    score,
                "profile":  _profile_for(score),
                "drivers":  drivers,
                "volume_30d_usd": round(volume, 2),
                "kyc_age_days":   last_kyc_days,
                "refreshed_at":   _iso(_now()),
                "is_deleted":     False,
            },  "$setOnInsert": {"created_at": _iso(_now())}},
            upsert=True,
        )
        summary["risk_scores"] += 1

    # Generic alerts feed — 12 mixed entries
    if await col(ALERTS).estimated_document_count() == 0:
        types = ["kyt", "operational", "compliance", "technical"]
        severities = ["info", "warning", "critical"]
        for i in range(12):
            sev = severities[i % 3]
            t   = types[i % 4]
            await col(ALERTS).insert_one({
                "alert_id":    f"al_{secrets.token_hex(5)}",
                "type":        t,
                "severity":    sev,
                "title":       f"{t.title()} alert · {sev}",
                "description": f"Seed alert #{i+1} for {t} type.",
                "org_id":      random.choice(["org_seed_alemany", "org_seed_finpact", None]),
                "rule_id":     "kyt_daily_cap" if t == "kyt" else None,
                "status":      random.choice(["open", "open", "acknowledged", "resolved"]),
                "assigned_to": None,
                "context":     {"seed": True},
                "created_at":  _iso(_now() - timedelta(hours=i * 3)),
                "updated_at":  _iso(_now() - timedelta(hours=i * 3)),
                "is_deleted":  False,
            })
            summary["alerts"] += 1

    # Watchlist seed entries
    if await col(WATCHLIST).estimated_document_count() == 0:
        for i, (kind, value, reason) in enumerate([
            ("wallet", "GAXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXBLACKLIST",
             "Address reported as scam by community"),
            ("wallet", "GAYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYMIXER",
             "Linked to known mixer service"),
            ("wallet", "GAZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZSANCTN",
             "OFAC sanctioned (manual entry)"),
            ("client", "org_seed_finpact",
             "Pending enhanced due diligence per board request"),
        ]):
            await col(WATCHLIST).insert_one({
                "entry_id":  f"wl_{secrets.token_hex(5)}",
                "kind":      kind,
                "value":     value,
                "reason":    reason,
                "added_by":  "usr_seed_compliance",
                "created_at": _iso(_now() - timedelta(days=i + 1)),
                "is_deleted": False,
            })
            summary["watchlist"] += 1

    return summary
