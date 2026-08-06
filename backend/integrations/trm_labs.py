"""TRM Labs Public API integration — Wallet Screening.

Single read-only function: `screen_wallet(address)` calls TRM Labs Wallet
Screening API and normalises the response to our internal `WatchlistResult`
shape. If `TRM_LABS_API_KEY` is empty (as in dev/preview today), the function
returns a clearly-flagged `unavailable` result so the UI can render a
"external screening pending integration" badge instead of breaking the flow.

Docs reference: see integration playbook returned by integration_playbook_expert_v2.
Endpoint: POST https://api.trmlabs.com/v1/wallets/screening
Auth: Authorization: Bearer ${TRM_LABS_API_KEY}
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("prosper.trm")

TRM_LABS_API_KEY  = os.environ.get("TRM_LABS_API_KEY", "")
TRM_LABS_BASE_URL = os.environ.get("TRM_LABS_BASE_URL", "https://api.trmlabs.com")
TIMEOUT_SECONDS   = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def screen_wallet(address: str, blockchain: Optional[str] = "stellar") -> dict:
    """Return a normalised screening result for the given on-chain address.

    Shape always contains: address, blockchain, status, risk_score, is_sanctioned,
    risks[], entity_type, entity_name, screened_at, error_reason.
    """
    address = (address or "").strip()
    if not address:
        return {
            "address": address, "blockchain": blockchain,
            "status": "error", "error_reason": "empty address",
            "risk_score": None, "is_sanctioned": False, "risks": [],
            "entity_type": None, "entity_name": None,
            "screened_at": _now_iso(),
        }

    if not TRM_LABS_API_KEY:
        logger.info(f"[TRM stub] screen_wallet({address[:8]}…) — no key set")
        return {
            "address": address, "blockchain": blockchain,
            "status": "unavailable",
            "error_reason": "TRM_LABS_API_KEY missing",
            "risk_score": None, "is_sanctioned": False, "risks": [],
            "entity_type": None, "entity_name": None,
            "screened_at": _now_iso(),
        }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as c:
            r = await c.post(
                f"{TRM_LABS_BASE_URL}/v1/wallets/screening",
                headers={"Authorization": f"Bearer {TRM_LABS_API_KEY}",
                         "Content-Type": "application/json"},
                json={"addresses": [address],
                      "include_transaction_details": True,
                      "include_entity_attribution": True},
            )
        if r.status_code == 401:
            return {"address": address, "blockchain": blockchain,
                    "status": "error", "error_reason": "auth failed",
                    "risk_score": None, "is_sanctioned": False, "risks": [],
                    "entity_type": None, "entity_name": None,
                    "screened_at": _now_iso()}
        if r.status_code == 429:
            return {"address": address, "blockchain": blockchain,
                    "status": "rate_limited",
                    "error_reason": "rate limit exceeded",
                    "risk_score": None, "is_sanctioned": False, "risks": [],
                    "entity_type": None, "entity_name": None,
                    "screened_at": _now_iso()}
        r.raise_for_status()
        data = (r.json() or {})
        results = data.get("results") or []
        first = next((x for x in results if x.get("address") == address), results[0] if results else None)
        if not first:
            return {"address": address, "blockchain": blockchain,
                    "status": "success", "error_reason": None,
                    "risk_score": 0, "is_sanctioned": False, "risks": [],
                    "entity_type": None, "entity_name": None,
                    "screened_at": _now_iso()}
        risks_raw = first.get("risks") or []
        risks = [{
            "category":   r.get("category", "counterparty"),
            "severity":   r.get("severity", "low"),
            "label":      r.get("label", "Unknown"),
            "confidence": float(r.get("confidence", 0.0)),
            "description": r.get("description", ""),
            "source":     r.get("source", "trm"),
        } for r in risks_raw]
        is_sanctioned = any(
            r["severity"] in ("high", "severe") and r["category"] == "ownership"
            for r in risks
        )
        entity = first.get("entity") or {}
        risk_score = ((first.get("risk_score") or {}).get("current")) or 0
        return {
            "address":      address,
            "blockchain":   blockchain,
            "status":       "success",
            "error_reason": None,
            "risk_score":   risk_score,
            "is_sanctioned": is_sanctioned,
            "risks":        risks,
            "entity_type":  entity.get("type"),
            "entity_name":  entity.get("name"),
            "screened_at":  _now_iso(),
        }
    except httpx.TimeoutException:
        return {"address": address, "blockchain": blockchain,
                "status": "timeout", "error_reason": "TRM API timeout",
                "risk_score": None, "is_sanctioned": False, "risks": [],
                "entity_type": None, "entity_name": None,
                "screened_at": _now_iso()}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"TRM screen_wallet failed: {e}")
        return {"address": address, "blockchain": blockchain,
                "status": "error", "error_reason": str(e),
                "risk_score": None, "is_sanctioned": False, "risks": [],
                "entity_type": None, "entity_name": None,
                "screened_at": _now_iso()}
