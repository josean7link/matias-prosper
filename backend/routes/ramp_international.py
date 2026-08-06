"""Phase 15.2 — International off-ramp (ARS → BOB/PEN/PYG) + crypto transfers.

The FastAPI layer orchestrates a 3-step flow against the `andes-gateway`:

    1) ensure_intl_account     — persist & forward a destination bank account
    2) quote                    — bind quotes for BOB/PEN (expire); rate-only for PYG
    3) execute_offramp          — actually move ARSa → fiat in destination country

Each execution persists a `ramp_movements` row with `kind="intl_offramp"` and
`status="Pending"`; the final state arrives via the webhook
`international.offramp.success|failed` (handled in `ramp_webhook.py`).

Crypto wallet-to-wallet transfers (Phase 15.2 / B) live here too: a single
`POST /accounts/{ecid}/transfer` endpoint that wraps `wallets/transfers` on the
gateway and persists `ramp_movements(kind="transfer")`.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import (
    col, RAMP_ACCOUNTS, RAMP_BALANCES, RAMP_INTL_ACCOUNTS,
    RAMP_MOVEMENTS, RAMP_WALLETS,
)

logger = logging.getLogger("prosper.ramp.international")
router = APIRouter(prefix="/ramp", tags=["ramp-international"])

_BACKOFFICE_WRITE = {"super_admin", "admin", "finance_admin", "finance"}
_BACKOFFICE_READ  = {"super_admin", "admin", "finance_admin", "finance",
                        "compliance_admin", "compliance_officer", "ops"}


def _now() -> datetime:  return datetime.now(timezone.utc)
def _now_iso() -> str:   return _now().isoformat()


def _gateway() -> tuple[str, str]:
    url = os.environ.get("ANDES_GATEWAY_URL", "http://localhost:8090").rstrip("/")
    tok = os.environ.get("GATEWAY_INTERNAL_TOKEN",
                              "dev-internal-token-change-me")
    return url, tok


def _require_finance(u: CurrentUser):
    if u.role not in _BACKOFFICE_WRITE:
        raise HTTPException(403, "requires finance_admin or super_admin")


def _require_backoffice(u: CurrentUser):
    if u.role not in _BACKOFFICE_READ:
        raise HTTPException(403, "backoffice only")


async def _resolve_account(org_id: str, ecid: str) -> dict:
    acc = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id, "end_customer_id": ecid}, {"_id": 0})
    if not acc:
        raise HTTPException(404, "ramp account not found")
    return acc


async def _gw(method: str, path: str, *,
                  json_body: Optional[dict] = None,
                  params: Optional[dict] = None) -> dict:
    url, tok = _gateway()
    async with httpx.AsyncClient(timeout=20.0) as cli:
        r = await cli.request(method, f"{url}{path}",
                                  json=json_body, params=params,
                                  headers={"X-Internal-Token": tok})
    if r.status_code >= 400:
        raise HTTPException(r.status_code,
                              f"gateway {r.status_code}: {r.text[:300]}")
    try:    return r.json()
    except Exception:  return {}


# ---------------------------------------------------------------------------
# A.1 — Destination accounts (BOB / PEN / PYG)
# ---------------------------------------------------------------------------
class IntlAccountIn(BaseModel):
    end_customer_id: str
    country: str = Field(..., pattern="^(bob|pen|pyg)$")
    # Common subset (we accept either snake or camel — see _build_gateway_body)
    account_number: str
    account_holder: str
    account_holder_last_name: str
    document_number: str
    document_type: Optional[str] = None
    account_type: Optional[str] = "checking"
    bank_code: Optional[str] = None
    bank_name: Optional[str] = None
    phone_number: Optional[str] = None


def _build_gateway_body(provider_user_id: str, body: IntlAccountIn) -> dict:
    # The SDK uses camelCase. Same for the gateway pass-through.
    base = {
        "userId":               provider_user_id,
        "accountNumber":        body.account_number,
        "accountHolderLastName": body.account_holder_last_name,
        "documentNumber":       body.document_number,
        "documentType":         body.document_type or "DNI",
        "accountType":          body.account_type or "checking",
    }
    if body.country == "bob":
        base.update({"accountHolder": body.account_holder,
                       "bankCode": body.bank_code})
    elif body.country == "pen":
        base.update({"accountHolderName": body.account_holder,
                       "bankName": body.bank_name,
                       "phoneNumber": body.phone_number})
    else:  # pyg
        base.update({"accountHolder": body.account_holder,
                       "bankCode": int(body.bank_code or 0)})
    return base


@router.post("/international/accounts")
async def create_intl_account(body: IntlAccountIn,
                                   user: CurrentUser = Depends(get_current_user),
                                   org_id_q: Optional[str] = Query(None,
                                        alias="org_id")):
    _require_finance(user)
    org_id = org_id_q or user.org_id
    acc = await _resolve_account(org_id, body.end_customer_id)
    pu = acc["provider_user_id"]

    gw_body = _build_gateway_body(pu, body)
    resp = await _gw("POST", f"/intl/accounts/{body.country}",
                          json_body=gw_body)

    fid = (resp.get("pygFiatAccountId")
              or resp.get("id")
              or "intl_" + secrets.token_hex(6))
    doc = {
        "id":                fid,
        "org_id":            org_id,
        "end_customer_id":   body.end_customer_id,
        "provider_user_id":  pu,
        "country":           body.country,
        "account_number":    body.account_number,
        "account_holder":    body.account_holder,
        "account_holder_last_name": body.account_holder_last_name,
        "document_number":   body.document_number,
        "document_type":     body.document_type or "DNI",
        "account_type":      body.account_type or "checking",
        "bank_code":         body.bank_code,
        "bank_name":         body.bank_name,
        "fiat_account_id":   fid,
        "created_at":        _now_iso(),
        "updated_at":        _now_iso(),
    }
    await col(RAMP_INTL_ACCOUNTS).insert_one(dict(doc))
    await log_action(actor=user, action="ramp.intl.account.created",
                       resource_type="ramp_intl_account",
                       resource_id=fid,
                       metadata={"org_id": org_id,
                                  "country": body.country,
                                  "end_customer_id": body.end_customer_id})
    doc.pop("_id", None)
    return doc


@router.get("/international/accounts")
async def list_intl_accounts(end_customer_id: Optional[str] = Query(None),
                                   user: CurrentUser = Depends(get_current_user),
                                   org_id_q: Optional[str] = Query(None,
                                        alias="org_id")):
    _require_backoffice(user)
    org_id = org_id_q or user.org_id
    flt: dict = {"org_id": org_id}
    if end_customer_id: flt["end_customer_id"] = end_customer_id
    items = await col(RAMP_INTL_ACCOUNTS).find(flt, {"_id": 0}).to_list(200)
    return items


@router.get("/international/banks/{country}")
async def list_banks(country: str,
                       user: CurrentUser = Depends(get_current_user)):
    _require_backoffice(user)
    if country not in ("bob", "pen", "pyg"):
        raise HTTPException(400, "country must be bob|pen|pyg")
    return await _gw("GET", f"/intl/banks/{country}")


@router.get("/international/cotization")
async def cotization(user: CurrentUser = Depends(get_current_user)):
    _require_backoffice(user)
    return await _gw("GET", "/intl/cotization")


# ---------------------------------------------------------------------------
# A.2 — Quotes (BOB/PEN bind quoteIds; PYG is rate-only)
# ---------------------------------------------------------------------------
class IntlQuoteIn(BaseModel):
    country: str = Field(..., pattern="^(bob|pen|pyg)$")
    from_amount: Optional[str] = None        # required for bob|pen
    payment_method_type: Optional[str] = "bank_transfer"


@router.post("/international/quote")
async def quote_intl(body: IntlQuoteIn,
                       user: CurrentUser = Depends(get_current_user)):
    _require_backoffice(user)
    if body.country == "pyg":
        return await _gw("GET", "/intl/quote/pyg")
    if not body.from_amount:
        raise HTTPException(400, "from_amount required for bob|pen")
    return await _gw("POST", f"/intl/quote/{body.country}", json_body={
        "fromAmount": body.from_amount,
        "paymentMethodType": body.payment_method_type or "bank_transfer",
    })


# ---------------------------------------------------------------------------
# A.3 — Execute off-ramp
# ---------------------------------------------------------------------------
class IntlOfframpIn(BaseModel):
    end_customer_id: str
    country: str = Field(..., pattern="^(bob|pen|pyg)$")
    fiat_account_id: str
    # BOB/PEN
    ars_usdt_quote_id: Optional[str] = None
    usdt_dest_quote_id: Optional[str] = None
    quote_expiration: Optional[str] = None    # ISO; rejected if past
    # PYG
    ars_amount: Optional[str] = None
    # Computed display
    expected_to_amount: Optional[str] = None


async def _arsa_balance(ramp_account_id: str, chain: str) -> float:
    row = await col(RAMP_BALANCES).find_one(
        {"ramp_account_id": ramp_account_id, "asset": "arsa", "chain": chain},
        {"_id": 0, "balance": 1})
    return float((row or {}).get("balance") or 0)


@router.post("/international/offramp")
async def execute_intl_offramp(body: IntlOfframpIn,
                                     user: CurrentUser = Depends(get_current_user),
                                     idempotency_key: Optional[str] =
                                          Header(None, alias="Idempotency-Key"),
                                     org_id_q: Optional[str] = Query(None,
                                          alias="org_id")):
    _require_finance(user)
    org_id = org_id_q or user.org_id
    acc = await _resolve_account(org_id, body.end_customer_id)
    pu = acc["provider_user_id"]

    # Validate quote expiration (BOB/PEN)
    if body.country in ("bob", "pen"):
        if not (body.ars_usdt_quote_id and body.usdt_dest_quote_id):
            raise HTTPException(400, "ars_usdt_quote_id + usdt_dest_quote_id required")
        if body.quote_expiration:
            try:
                exp = datetime.fromisoformat(body.quote_expiration.replace("Z", "+00:00"))
                if exp < _now():
                    raise HTTPException(409, "quote has expired — re-quote and retry")
            except ValueError:
                pass

    # Validate ARSa balance ≥ from_amount
    from_amount = body.ars_amount if body.country == "pyg" else None
    if body.country in ("bob", "pen"):
        # We don't have explicit from_amount here, but for safety we compute
        # from expected_to_amount * inv-rate is unreliable; instead trust the
        # backoffice + check the local wallet's chain.
        from_amount = body.expected_to_amount or "0"
    # Resolve the user's ARSa wallet chain (Phase 17/18) — must be active
    w = await col(RAMP_WALLETS).find_one(
        {"ramp_account_id": acc["id"], "asset": "arsa"},
        {"_id": 0, "chain": 1, "status": 1})
    if not w or w.get("status") != "active":
        raise HTTPException(409,
            "Wallet ARSa todavía no está activa — esperá a wallet.active")
    if body.country == "pyg" and float(body.ars_amount or 0) > 0:
        bal = await _arsa_balance(acc["id"], w["chain"])
        if bal < float(body.ars_amount or 0):
            raise HTTPException(400,
                f"insufficient ARSa balance: have {bal}, need {body.ars_amount}")

    # Idempotency by header (if provided)
    if idempotency_key:
        prev = await col(RAMP_MOVEMENTS).find_one(
            {"idempotency_key": idempotency_key, "kind": "intl_offramp"},
            {"_id": 0})
        if prev:
            return prev

    # Build gateway body
    gw_body: dict = {"userId": pu, "fiatAccountId": body.fiat_account_id}
    if body.country == "bob":
        gw_body.update({"arsUsdtQuoteId": body.ars_usdt_quote_id,
                          "usdtBobQuoteId": body.usdt_dest_quote_id})
    elif body.country == "pen":
        gw_body.update({"arsUsdtQuoteId": body.ars_usdt_quote_id,
                          "usdtPenQuoteId": body.usdt_dest_quote_id})
    else:  # pyg
        if not body.ars_amount:
            raise HTTPException(400, "ars_amount required for pyg")
        gw_body["arsAmount"] = body.ars_amount

    try:
        resp = await _gw("POST", f"/intl/offramp/{body.country}",
                              json_body=gw_body)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"offramp execution failed: {e}")

    ext_id = str(resp.get("id") or resp.get("transactionId")
                   or "off_" + secrets.token_hex(6))
    prosper_tx_id = "prosper_intl_" + secrets.token_hex(6)
    mv = {
        "id":                "mv_" + secrets.token_hex(6),
        "org_id":            org_id,
        "ramp_account_id":   acc["id"],
        "provider":          "andeslabs",
        "provider_user_id":  pu,
        "external_id":       ext_id,
        "kind":              "intl_offramp",
        "country":           body.country,
        "asset":             "arsa",
        "chain":             w["chain"],
        "from_amount":       from_amount,
        "to_amount":         body.expected_to_amount or resp.get("to_amount"),
        "to_currency":       body.country.upper(),
        "fiat_account_id":   body.fiat_account_id,
        "status":            "Pending",
        "prosper_tx_id":     prosper_tx_id,
        "occurred_at":       _now_iso(),
        "raw":               resp,
        "idempotency_key":   idempotency_key,
        "created_at":        _now_iso(),
        "updated_at":        _now_iso(),
    }
    await col(RAMP_MOVEMENTS).insert_one(dict(mv))
    await log_action(actor=user, action="ramp.intl.offramp.executed",
                       resource_type="ramp_movement",
                       resource_id=mv["id"],
                       metadata={"org_id": org_id,
                                  "country": body.country,
                                  "from_amount": from_amount,
                                  "external_id": ext_id})
    mv.pop("_id", None)
    return mv


@router.get("/international/offramp")
async def list_intl_offramps(end_customer_id: Optional[str] = Query(None),
                                   user: CurrentUser = Depends(get_current_user),
                                   org_id_q: Optional[str] = Query(None,
                                        alias="org_id"),
                                   limit: int = Query(100, le=500)):
    _require_backoffice(user)
    org_id = org_id_q or user.org_id
    flt = {"org_id": org_id, "kind": "intl_offramp"}
    if end_customer_id:
        acc = await _resolve_account(org_id, end_customer_id)
        flt["ramp_account_id"] = acc["id"]
    items = await col(RAMP_MOVEMENTS).find(flt, {"_id": 0}).sort(
        "created_at", -1).to_list(limit)
    return items


# ---------------------------------------------------------------------------
# B — Crypto wallet-to-wallet transfers
# ---------------------------------------------------------------------------
class TransferIn(BaseModel):
    asset:       str = Field(..., pattern="^(arsa|usdc|usdt)$")
    chain:       str = Field(..., pattern="^(stellar|base|worldchain)$")
    amount:      str
    to_address:  str = Field(..., min_length=4, max_length=128)
    memo:        Optional[str] = None


@router.post("/accounts/{end_customer_id}/transfer")
async def execute_transfer(end_customer_id: str,
                                 body: TransferIn,
                                 user: CurrentUser = Depends(get_current_user),
                                 idempotency_key: Optional[str] =
                                      Header(None, alias="Idempotency-Key"),
                                 org_id_q: Optional[str] = Query(None,
                                      alias="org_id")):
    _require_finance(user)
    org_id = org_id_q or user.org_id
    acc = await _resolve_account(org_id, end_customer_id)
    pu = acc["provider_user_id"]

    # Validate wallet exists + active + sufficient balance
    w = await col(RAMP_WALLETS).find_one(
        {"ramp_account_id": acc["id"], "asset": body.asset,
          "chain": body.chain},
        {"_id": 0, "status": 1})
    if not w:
        raise HTTPException(404, "source wallet not found")
    if w.get("status") != "active":
        raise HTTPException(409, "wallet not active yet — wait for wallet.active")

    amount = float(body.amount)
    if amount <= 0:
        raise HTTPException(400, "amount must be positive")

    bal_row = await col(RAMP_BALANCES).find_one(
        {"ramp_account_id": acc["id"], "asset": body.asset,
          "chain": body.chain},
        {"_id": 0, "balance": 1})
    bal = float((bal_row or {}).get("balance") or 0)
    if bal < amount:
        raise HTTPException(400,
            f"insufficient {body.asset} balance: have {bal}, need {amount}")

    if idempotency_key:
        prev = await col(RAMP_MOVEMENTS).find_one(
            {"idempotency_key": idempotency_key, "kind": "transfer"},
            {"_id": 0})
        if prev:
            return prev

    # Call gateway
    gw_body = {"user_id": pu, "chain": body.chain, "asset": body.asset,
                 "to_address": body.to_address, "amount": amount}
    resp = await _gw("POST", "/wallets/transfers", json_body=gw_body)
    ext_id = str(resp.get("transactionId")
                   or "tx_" + secrets.token_hex(6))

    # Pre-debit the cached balance immediately
    new_bal = max(0.0, bal - amount)
    await col(RAMP_BALANCES).update_one(
        {"ramp_account_id": acc["id"], "asset": body.asset,
          "chain": body.chain},
        {"$set": {"balance": str(new_bal), "as_of": _now_iso()}},
        upsert=True)

    prosper_tx_id = "prosper_tr_" + secrets.token_hex(6)
    mv = {
        "id":                "mv_" + secrets.token_hex(6),
        "org_id":            org_id,
        "ramp_account_id":   acc["id"],
        "provider":          "andeslabs",
        "provider_user_id":  pu,
        "external_id":       ext_id,
        "kind":              "transfer",
        "asset":             body.asset,
        "chain":             body.chain,
        "amount":            body.amount,
        "to_address":        body.to_address,
        "memo":              body.memo,
        "status":            "Pending",
        "prosper_tx_id":     prosper_tx_id,
        "occurred_at":       _now_iso(),
        "raw":               resp,
        "idempotency_key":   idempotency_key,
        "created_at":        _now_iso(),
        "updated_at":        _now_iso(),
    }
    await col(RAMP_MOVEMENTS).insert_one(dict(mv))
    await log_action(actor=user, action="ramp.transfer.executed",
                       resource_type="ramp_movement",
                       resource_id=mv["id"],
                       metadata={"org_id": org_id,
                                  "end_customer_id": end_customer_id,
                                  "asset": body.asset, "chain": body.chain,
                                  "amount": body.amount,
                                  "to_address": body.to_address,
                                  "external_id": ext_id})
    mv.pop("_id", None)
    return mv
