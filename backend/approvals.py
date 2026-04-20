"""Approval workflow helpers (two-signer pattern).

Business rules:
- `mint` and `fund.create` ALWAYS require an approval request.
- `position.redeem` > $10,000 requires approval.
- Requester cannot be the approver (different user_id).
- By default `required_approvals=1` (one second signer). Can be raised per action type.
"""
from __future__ import annotations
from typing import Dict, Any, Optional, List
from datetime import datetime
from models import now_utc, new_id, User
from db import col, APPROVALS, TRANSACTIONS, FUNDS, POSITIONS
import hashlib
import uuid
import prosper_client

APPROVAL_REQUIRED_ACTIONS = {
    "mint": {"required_approvals": 1},
    "fund.create": {"required_approvals": 1},
    "position.redeem.large": {"required_approvals": 1, "threshold_usd": 10_000},
}


async def create_approval_request(*, action: str, payload: Dict[str, Any], requester: User,
                                  reason: Optional[str] = None, required_approvals: int = 1) -> Dict[str, Any]:
    doc = {
        "approval_id": f"apv_{new_id()}",
        "action": action,
        "payload": payload,
        "requested_by": requester.user_id,
        "requested_by_email": requester.email,
        "required_approvals": required_approvals,
        "approvals": [],
        "rejections": [],
        "status": "pending",
        "reason": reason,
        "created_at": now_utc().isoformat(),
        "executed_at": None,
        "result": None,
        "is_demo": False,
    }
    await col(APPROVALS).insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def _execute_mint(payload: Dict[str, Any], requester_email: str) -> Dict[str, Any]:
    prosper_tx_id = payload.get("prosper_tx_id") or str(uuid.uuid4())
    fund_id = payload["fund_id"]
    amount = float(payload["amount"])
    reason = payload.get("reason", "")

    proxy = await prosper_client.call("POST", "/v1/tokens/mint", {
        "amount": str(amount), "reason": reason, "prosperTxId": prosper_tx_id,
    })
    tx_hash = (proxy.get("data") or {}).get("txHash") if proxy.get("proxied") else \
              hashlib.sha256(prosper_tx_id.encode()).hexdigest()
    tx = {
        "tx_id": f"tx_{new_id()}", "prosper_tx_id": prosper_tx_id,
        "fund_id": fund_id, "type": "mint", "amount": amount,
        "asset_code": "PROS", "from_address": None, "to_address": "treasury",
        "memo": prosper_tx_id, "tx_hash": tx_hash,
        "status": "submitted" if proxy.get("proxied") else "confirmed",
        "metadata": {"reason": reason, "requester": requester_email, "proxy": proxy,
                     "approval": True},
        "environment": "production", "is_demo": False,
        "created_at": now_utc().isoformat(),
    }
    await col(TRANSACTIONS).insert_one(dict(tx))
    tx.pop("_id", None)
    return {"transaction": tx, "prosper_tx_id": prosper_tx_id}


async def _execute_fund_create(payload: Dict[str, Any], requester_email: str) -> Dict[str, Any]:
    prosper_tx_id = payload.get("prosper_tx_id") or str(uuid.uuid4())
    proxy = await prosper_client.call("POST", "/v1/funds", {
        "InitialAmount": str(payload.get("initial_amount", 0)),
        "homeDomain": payload.get("home_domain") or "prosper.foundation",
        "prosperTxId": prosper_tx_id,
    })
    doc = {
        "fund_id": f"fund_{new_id()}", "code": payload["code"], "name": payload["name"],
        "underlying": payload.get("underlying", ""),
        "home_domain": payload.get("home_domain"),
        "total_supply": float(payload.get("initial_amount", 0)),
        "circulating_supply": 0, "nav_per_token": 1.0,
        "status": "active", "environment": payload.get("environment", "sandbox"),
        "is_demo": False, "created_at": now_utc().isoformat(),
    }
    await col(FUNDS).insert_one(dict(doc))
    doc.pop("_id", None)
    return {"fund": doc, "prosper_tx_id": prosper_tx_id, "proxy": proxy}


async def execute_approved_action(action: str, payload: Dict[str, Any], requester_email: str) -> Dict[str, Any]:
    if action == "mint":
        return await _execute_mint(payload, requester_email)
    if action == "fund.create":
        return await _execute_fund_create(payload, requester_email)
    if action == "position.redeem.large":
        # Simplified: just mark the position redeemed; a prod system would re-run redeem.
        pid = payload.get("position_id")
        if pid:
            await col(POSITIONS).update_one({"position_id": pid}, {"$set": {"status": "redeemed"}})
        return {"position_id": pid}
    raise ValueError(f"Unknown action: {action}")
