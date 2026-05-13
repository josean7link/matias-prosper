"""Phase 5 — Risk overview + watchlist + SAR/STR reports."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from audit import log_action
from auth import CurrentUser
from db import col, ORGANIZATIONS, RISK_SCORES, TRANSACTIONS, WATCHLIST
from ._deps import require_compliance, require_compliance_decide

router = APIRouter(prefix="/admin/compliance/risk", tags=["admin-compliance-risk"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/overview")
async def risk_overview(_: CurrentUser = Depends(require_compliance)):
    rows = await col(RISK_SCORES).find({"is_deleted": False}, {"_id": 0}).to_list(2000)
    buckets = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for r in rows:
        p = r.get("profile") or "low"
        if p in buckets: buckets[p] += 1
    top10 = sorted(rows, key=lambda r: r.get("score", 0), reverse=True)[:10]
    return {"distribution": buckets, "top10": top10, "total": len(rows)}


@router.get("/clients")
async def list_risk_clients(_: CurrentUser = Depends(require_compliance)):
    rows = await col(RISK_SCORES).find({"is_deleted": False}, {"_id": 0})\
              .sort("score", -1).to_list(2000)
    return {"items": rows, "total": len(rows)}


@router.get("/clients/{org_id}")
async def risk_client_detail(org_id: str, _: CurrentUser = Depends(require_compliance)):
    r = await col(RISK_SCORES).find_one({"org_id": org_id, "is_deleted": False}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Risk score not found")
    return r


# --------- SAR / STR (drafts) ---------
class SarIn(BaseModel):
    org_id: str
    summary: str


class StrIn(BaseModel):
    tx_id: str
    summary: str


@router.post("/reports/sar")
async def generate_sar(body: SarIn,
                       user: CurrentUser = Depends(require_compliance_decide)):
    org = await col(ORGANIZATIONS).find_one({"org_id": body.org_id, "is_deleted": False},
                                              {"_id": 0})
    if not org:
        raise HTTPException(404, "Org not found")
    risk = await col(RISK_SCORES).find_one({"org_id": body.org_id}, {"_id": 0})
    report = {
        "type":         "SAR",
        "report_id":    f"sar_{datetime.now(timezone.utc).timestamp():.0f}",
        "draft":        True,
        "generated_by": user.email,
        "generated_at": _iso_now(),
        "subject": {
            "org_id":       org["org_id"],
            "legal_name":   org.get("legal_name"),
            "country":      org.get("country"),
            "kyb_status":   org.get("kyb_status"),
            "risk_score":   (risk or {}).get("score"),
            "risk_profile": (risk or {}).get("profile"),
        },
        "summary":      body.summary,
        "context":      {"drivers": (risk or {}).get("drivers"),
                          "volume_30d_usd": (risk or {}).get("volume_30d_usd")},
    }
    await log_action(actor=user, action="compliance.report.sar_generated",
                     resource_type="organization", resource_id=org["org_id"],
                     metadata={"report_id": report["report_id"]})
    return report


@router.post("/reports/str")
async def generate_str(body: StrIn,
                       user: CurrentUser = Depends(require_compliance_decide)):
    tx = await col(TRANSACTIONS).find_one({"tx_id": body.tx_id}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "Transaction not found")
    report = {
        "type":         "STR",
        "report_id":    f"str_{datetime.now(timezone.utc).timestamp():.0f}",
        "draft":        True,
        "generated_by": user.email,
        "generated_at": _iso_now(),
        "transaction": {
            "tx_id":         tx.get("tx_id"),
            "prosper_tx_id": tx.get("prosper_tx_id"),
            "org_id":        tx.get("org_id"),
            "amount":        tx.get("amount"),
            "type":          tx.get("type"),
            "status":        tx.get("status"),
            "created_at":    tx.get("created_at"),
            "tx_hash":       tx.get("tx_hash"),
        },
        "summary":      body.summary,
    }
    await log_action(actor=user, action="compliance.report.str_generated",
                     resource_type="transaction", resource_id=tx.get("tx_id") or "",
                     metadata={"report_id": report["report_id"]})
    return report
