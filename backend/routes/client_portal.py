"""Phase 7 — Client portal endpoints (scoped to JWT org_id)."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import CurrentUser, get_current_user, JWT_SECRET, JWT_ALGORITHM
from db import (
    col, ALERTS, KYB_CASES, ORGANIZATIONS, POSITIONS, RISK_SCORES,
    SIGNED_LINKS, TRANSACTIONS, USERS,
)
from integrations.email_sender import send_email, _shell

router = APIRouter(prefix="/client", tags=["client"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/me")
async def client_me(user: CurrentUser = Depends(get_current_user)):
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": user.org_id, "is_deleted": False}, {"_id": 0})
    if not org:
        raise HTTPException(404, "Organization not found")

    # ---- Onboarding progress (derived from KybCase if any) ----
    kyb_status = org.get("kyb_status") or "pending"
    case = await col(KYB_CASES).find_one(
        {"org_id": user.org_id, "is_deleted": False},
        {"_id": 0, "checklist": 1, "documents": 1, "status": 1},
        sort=[("created_at", -1)])

    checklist_total = 8
    checklist_done  = 0
    docs_count      = 0
    if case:
        checklist_done = sum(1 for it in (case.get("checklist") or []) if it.get("checked"))
        docs_count     = len(case.get("documents") or [])

    if kyb_status == "approved":
        stage = "approved"; pct = 100
    elif kyb_status == "rejected":
        stage = "rejected"; pct = 0
    elif kyb_status == "in_review":
        stage = "in_review"
        pct = max(40, round(checklist_done / checklist_total * 100))
    elif kyb_status == "needs_info":
        stage = "needs_info"
        pct = max(60, round(checklist_done / checklist_total * 100))
    elif case:
        stage = "applied"
        pct = max(40, round(checklist_done / checklist_total * 100))
    else:
        stage = "not_started"
        pct = 0

    return {
        "user": {"user_id": user.user_id, "email": user.email,
                  "full_name": getattr(user, "full_name", None),
                  "role": user.role, "org_id": user.org_id},
        "org": {
            "org_id":         org["org_id"],
            "legal_name":     org.get("legal_name"),
            "commercial_name": org.get("commercial_name"),
            "country":        org.get("country"),
            "kyb_status":     kyb_status,
            "env":            org.get("env") or "sandbox",
            "tier":           org.get("tier") or "T2",
            "paused":         bool(org.get("paused")),
            "kyb_reject_reason": org.get("kyb_reject_reason"),
        },
        "features": {
            "can_operate":    (kyb_status == "approved") and not org.get("paused"),
            "can_view_data":  True,
            "can_edit_profile": True,
        },
        "onboarding": {
            "stage":           stage,
            "percent":         pct,
            "checklist_done":  checklist_done,
            "checklist_total": checklist_total,
            "docs_count":      docs_count,
            "has_case":        case is not None,
        },
    }


@router.get("/dashboard")
async def client_dashboard(user: CurrentUser = Depends(get_current_user)):
    org_id = user.org_id
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": org_id, "is_deleted": False}, {"_id": 0})
    if not org:
        raise HTTPException(404, "Organization not found")

    # Positions
    positions = await col(POSITIONS).find(
        {"org_id": org_id, "is_deleted": False}, {"_id": 0})\
        .sort("start", -1).to_list(200)
    active_positions = [p for p in positions if p.get("status") == "active"]

    # Transactions (latest 100 for sums + 5 for ledger)
    txs = await col(TRANSACTIONS).find(
        {"org_id": org_id, "is_deleted": False, "status": "confirmed"},
        {"_id": 0}).sort("created_at", -1).to_list(500)
    recent_5 = txs[:5]

    # KPIs
    subscribed = sum(t.get("amount", 0) for t in txs if t.get("type") == "subscribe")
    redeemed   = sum(t.get("amount", 0) for t in txs if t.get("type") == "redeem")
    onramped   = sum(t.get("amount", 0) for t in txs if t.get("type") == "onramp")
    offramped  = sum(t.get("amount", 0) for t in txs if t.get("type") == "offramp")
    available_usdc = max(0, onramped - subscribed + redeemed - offramped)

    principal_invested = sum(p.get("principal_usd", 0) or 0 for p in active_positions)
    accrued_total      = sum(p.get("accrued_interest", 0) or 0 for p in positions)

    weighted_apr_num = sum((p.get("principal_usd", 0) or 0) * (p.get("apr_bps", 0) or 0)
                            for p in active_positions)
    avg_apr_bps = (weighted_apr_num / principal_invested) if principal_invested else 0

    token_balance = subscribed - redeemed   # 1:1 PUSD ≈ USD for demo

    # Monthly yield series — last 12 months
    now = datetime.now(timezone.utc)
    months = []
    for i in range(11, -1, -1):
        y = now.year; m = now.month - i
        while m <= 0: m += 12; y -= 1
        key = f"{y:04d}-{m:02d}"
        months.append(key)
    yield_by_month: dict[str, float] = {k: 0.0 for k in months}
    for p in positions:
        ts = (p.get("start") or "")[:7]
        if ts in yield_by_month:
            yield_by_month[ts] += p.get("accrued_interest", 0) or 0
    monthly_yield_series = [{"month": k, "yield_usd": round(v, 2)}
                            for k, v in yield_by_month.items()]

    # Projected vs realized annual
    realized_ytd = sum(p.get("accrued_interest", 0) or 0 for p in positions
                       if (p.get("start") or "")[:4] == str(now.year))
    projected_annual = principal_invested * (avg_apr_bps / 10_000)

    # --- Today's yield: live-computed slice of the daily accrual ---
    # We accrue: principal × apr_bps / 10_000 / 365 per position per day.
    # If today's accrual already ran (last_accrued_date == today), we expose
    # that as "earned"; otherwise we expose the same number as "earning today"
    # so the customer sees the figure regardless of when they visit.
    today_str = now.strftime("%Y-%m-%d")
    today_earned = 0.0
    earning_now  = 0.0
    for p in active_positions:
        daily = (p.get("principal_usd", 0) or 0) * (p.get("apr_bps", 0) or 0) / 10_000 / 365
        if p.get("last_accrued_date") == today_str:
            today_earned += daily
        else:
            earning_now += daily
    today_total = round(today_earned + earning_now, 4)

    # Last 7 days yield (only includes already-applied accruals).
    daily_yield: list[dict] = []
    for offset in range(6, -1, -1):
        day = (now - timedelta(days=offset)).strftime("%Y-%m-%d")
        # We approximate per-day accrual from active positions whose
        # start_date <= day; this is a snapshot used only to fill the sparkline.
        earned = 0.0
        for p in positions:
            if (p.get("start") or "")[:10] <= day and p.get("status") != "redeemed":
                earned += (p.get("principal_usd", 0) or 0) * (p.get("apr_bps", 0) or 0) / 10_000 / 365
        daily_yield.append({"date": day, "yield_usd": round(earned, 4)})

    return {
        "kpis": {
            "available_usdc":      round(available_usdc, 2),
            "token_balance":       round(max(0, token_balance), 2),
            "token_value_usd":     round(max(0, token_balance), 2),
            "principal_invested":  round(principal_invested, 2),
            "accrued_total":       round(accrued_total, 2),
            "avg_apr_bps":         round(avg_apr_bps),
            "avg_apr_pct":         round(avg_apr_bps / 100, 2),
        },
        "positions": [{
            "position_id":   p.get("position_id"),
            "product":       "Term Staking",
            "principal":     p.get("principal_usd") or 0,
            "accrued":       p.get("accrued_interest") or 0,
            "apr_bps":       p.get("apr_bps") or 0,
            "apr_pct":       round((p.get("apr_bps") or 0) / 100, 2),
            "start_date":    p.get("start"),
            "maturity_date": p.get("maturity"),
            "status":        p.get("status"),
            "days_to_maturity": _days_to(p.get("maturity")),
        } for p in active_positions],
        "recent_transactions": [{
            "tx_id":          t.get("tx_id"),
            "prosper_tx_id":  t.get("prosper_tx_id"),
            "type":           t.get("type"),
            "amount":         t.get("amount"),
            "status":         t.get("status"),
            "created_at":     t.get("created_at"),
        } for t in recent_5],
        "monthly_yield":      monthly_yield_series,
        "daily_yield":        daily_yield,
        "today_yield": {
            "earned":      round(today_earned, 4),
            "earning_now": round(earning_now, 4),
            "total":       today_total,
            "as_of":       today_str,
        },
        "projection": {
            "realized_ytd":     round(realized_ytd, 2),
            "projected_annual": round(projected_annual, 2),
        },
        "kyb_status":  org.get("kyb_status") or "pending",
        "paused":      bool(org.get("paused")),
    }


def _days_to(iso: Optional[str]) -> Optional[int]:
    if not iso: return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return max(0, (dt - datetime.now(timezone.utc)).days)
    except Exception:
        return None


@router.get("/transactions")
async def client_transactions(limit: int = 100,
                                user: CurrentUser = Depends(get_current_user)):
    rows = await col(TRANSACTIONS).find(
        {"org_id": user.org_id, "is_deleted": False}, {"_id": 0})\
        .sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": rows, "total": len(rows)}


# ---------------------------------------------------------------------------
# Public /apply wizard endpoints (token-gated, no session needed)
# ---------------------------------------------------------------------------
import jwt
public = APIRouter(prefix="/apply", tags=["apply-public"])


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")


class TokenIn(BaseModel):
    token: str


@public.post("/context")
async def apply_context(body: TokenIn):
    payload = _decode(body.token)
    if payload.get("purpose") != "kyb":
        raise HTTPException(400, "Token is not a KYB link")
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": payload.get("org_id"), "is_deleted": False}, {"_id": 0})
    if not org:
        raise HTTPException(404, "Organization not found")
    # Don't consume yet — only on /finalize
    return {
        "org_id":        org["org_id"],
        "legal_name":    org.get("legal_name"),
        "commercial_name": org.get("commercial_name"),
        "country":       org.get("country"),
        "tax_id":        org.get("tax_id"),
        "type":          org.get("type"),
        "primary_email": org.get("primary_email"),
        "primary_name":  org.get("primary_name"),
    }


class ApplyFinalize(BaseModel):
    token: str
    personal: dict           # first_name, last_name, dob, gender, nationality, doc_id
    corporate: dict          # legal_name, country, tax_id, etc (might be confirmed)
    ubos: list[dict]         # name, ownership_pct, nationality, is_pep
    documents: list[dict]    # label, kind, url (mock for now)
    accept_terms: bool


@public.post("/finalize")
async def apply_finalize(body: ApplyFinalize):
    payload = _decode(body.token)
    if payload.get("purpose") != "kyb":
        raise HTTPException(400, "Token is not a KYB link")
    if not body.accept_terms:
        raise HTTPException(400, "Terms must be accepted")
    org_id = payload.get("org_id")

    # Consume the link
    res = await col(SIGNED_LINKS).update_one(
        {"link_id": payload.get("link_id"), "status": "pending"},
        {"$set": {"status": "used", "consumed_at": _iso_now()}})
    if not res.modified_count:
        raise HTTPException(401, "Link already used or expired")

    # Update or create the KybCase
    case_id = f"kyb_apply_{org_id[-8:]}"
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id}, {"_id": 0}) or {}
    checklist = [
        {"key": "certificate",      "label": "Certificado verificado", "checked": False},
        {"key": "board_resolution", "label": "Board resolution válido", "checked": False},
        {"key": "ubo_list",         "label": "UBO list completo y verificado", "checked": False},
        {"key": "address_proof",    "label": "Proof of address vigente (<3 meses)", "checked": False},
        {"key": "financials",       "label": "Estados financieros revisados", "checked": False},
        {"key": "sanctions",        "label": "Sanctions check pasado", "checked": False},
        {"key": "sectoral_risk",    "label": "Sectoral risk evaluado", "checked": False},
        {"key": "ownership_chart",  "label": "Ownership chart verificado", "checked": False},
    ]
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {
            "case_id":    case_id,
            "org_id":     org_id,
            "legal_name": (body.corporate or {}).get("legal_name") or org.get("legal_name"),
            "commercial_name": org.get("commercial_name") or org.get("legal_name"),
            "country":    org.get("country") or "AR",
            "type":       org.get("type") or "fintech",
            "tax_id":     org.get("tax_id"),
            "applicant":  body.personal,
            "ubos":       body.ubos,
            "documents":  body.documents,
            "checklist":  checklist,
            "provider":   "self_apply",
            "provider_score": 0, "provider_confidence": 0, "provider_flags": [],
            "checks":     {"aml": "manual_review", "sanctions": "manual_review",
                            "pep": "manual_review", "travel_rule": "n/a"},
            "status":     "in_review",
            "applied_at": _iso_now(),
            "is_deleted": False,
            "timeline":   [{"ts": _iso_now(), "by": "client_apply",
                             "what": "submitted_via_wizard", "meta": {}}],
            "updated_at": _iso_now(),
        }, "$setOnInsert": {"created_at": _iso_now()}},
        upsert=True)

    # Flip org.kyb_status to in_review (only if currently pending/needs_info)
    if org.get("kyb_status") in (None, "pending", "needs_info"):
        await col(ORGANIZATIONS).update_one(
            {"org_id": org_id},
            {"$set": {"kyb_status": "in_review", "updated_at": _iso_now()}})

    # Alert compliance officers
    await col(ALERTS).insert_one({
        "alert_id":    f"al_kyb_{org_id[-8:]}",
        "type":        "compliance",
        "severity":    "warning",
        "title":       f"Nuevo KYB recibido · {org.get('commercial_name') or org_id}",
        "description": f"El cliente {org.get('commercial_name') or org_id} envió docs vía /apply.",
        "org_id":      org_id,
        "rule_id":     None,
        "status":      "open",
        "assigned_to": None,
        "context":     {"case_id": case_id},
        "created_at":  _iso_now(),
        "updated_at":  _iso_now(),
        "is_deleted":  False,
    })

    # Notify compliance@prosper.foundation
    subj = f"[KYB] Nuevo caso para revisión · {org.get('commercial_name') or org_id}"
    body_html = _shell(f"""
        <h1>Nuevo KYB recibido</h1>
        <p>El cliente <strong>{org.get('commercial_name') or org_id}</strong> completó el wizard
        de onboarding desde /apply.</p>
        <p>Case ID: <code>{case_id}</code></p>
        <p><a class="btn" href="https://finance-control-215.preview.emergentagent.com/admin/compliance/kyb">
          Abrir cola KYB</a></p>""")
    await send_email(to="compliance@prosper.foundation", subject=subj,
                      html=body_html, template="kyb_submitted",
                      context={"org_id": org_id, "case_id": case_id},
                      org_id=org_id, actor_email="system.apply")

    # Sprint 12.6 — Kick off Alfred KYB now so the iframe URL is available
    # immediately on the status page. Best-effort: if the adapter is in mock
    # mode we still get a usable URL; if it fails we keep going (compliance
    # can still review manually).
    alfred_kyb: dict | None = None
    try:
        from integrations.alfred.kyc import get_kyc_adapter
        kyb_resp = await get_kyc_adapter().create_kyb_customer(
            org_id=org_id,
            business={
                "legal_name":    (body.corporate or {}).get("legal_name") or org.get("legal_name"),
                "country":       org.get("country") or "ARG",
                "tax_id":        org.get("tax_id"),
                "primary_email": org.get("primary_email"),
                "primary_contact": body.personal or {},
            },
            redirect_uri=f"/apply/status?app_id={case_id}",
        )
        await col(ORGANIZATIONS).update_one(
            {"org_id": org_id},
            {"$set": {
                "alfred_customer_id":    kyb_resp.customer_id,
                "alfred_kyb_iframe_url": kyb_resp.iframe_url,
                "alfred_kyb_init_tx":    kyb_resp.init_transaction,
                "alfred_kyb_status":     kyb_resp.status,
                "alfred_kyb_mode":       kyb_resp.mode,
                "alfred_kyb_started_at": _iso_now(),
                "updated_at":            _iso_now(),
            }})
        alfred_kyb = {
            "customer_id": kyb_resp.customer_id,
            "iframe_url":  kyb_resp.iframe_url,
            "status":      kyb_resp.status,
            "mode":        kyb_resp.mode,
        }
    except Exception as e:  # noqa: BLE001
        # AiPrise is deprecated; if Alfred KYB fails we still file the case
        # for compliance to handle manually. Log loud so ops can react.
        import logging as _lg
        _lg.getLogger("prosper.apply").exception(
            "alfred KYB auto-start failed for org=%s: %s", org_id, e)

    return {"ok": True, "case_id": case_id, "kyb_status": "in_review",
             "alfred_kyb": alfred_kyb}
