"""Phase 14 — `/api/v1/ramp/accounts*` business endpoints.

Orchestrates the 3-step Andes onboarding (account → wallet → fiat account)
and exposes balances + funding instructions to the portals.

Roles enforced via JWT. Idempotency via `Idempotency-Key` header.

Resilience contract (per Phase 14 PRD + product call):
    * If the provider rejects `ensure_fiat_account` because KYC files are
      missing, the account + ARSa wallet are still created and the row is
      marked `onboarding_status=kyc_pending_andes`. The operator can retry
      from the backoffice once docs are uploaded (POST .../retry).
    * If the provider is unreachable, the row is persisted with
      `onboarding_status=error` so it is visible + retryable.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import (
    col, ORGANIZATIONS, RAMP_ACCOUNTS, RAMP_BALANCES, RAMP_FIAT_ACCOUNTS,
    RAMP_MOVEMENTS, RAMP_WALLETS,
)
from ramp import (
    AvailableChain, FiatAccountParams, FiatAccountType,
    NotSupportedByProvider, WalletAsset, get_registry,
)
from ramp.chain_config import resolve_arsa_chain

logger = logging.getLogger("prosper.ramp.routes")

router = APIRouter(prefix="/ramp", tags=["ramp"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_FINANCE_ROLES = {"super_admin", "admin", "compliance_admin", "compliance_officer",
                   "finance_admin", "finance", "ops", "client_admin"}
_BACKOFFICE_ROLES = {"super_admin", "admin", "compliance_admin",
                      "compliance_officer", "finance_admin", "finance", "ops"}


def _require_finance(user: CurrentUser) -> None:
    if user.role not in _FINANCE_ROLES:
        raise HTTPException(403, f"role {user.role} cannot manage ramp accounts")


def _resolve_org_scope(user: CurrentUser, org_id_query: Optional[str]) -> str:
    """Return the org_id the caller may operate on.

    * Backoffice roles (super_admin/admin/…) may pass `?org_id=X` to
      operate on any tenant. Without the override, falls back to their own.
    * Client roles (client_admin / client_user — e.g. N1 of a Phase 23
      hierarchy) are pinned to `user.org_id`. If they explicitly pass a
      different `?org_id` (typical attempt: an N1 trying to operate on
      their N2 sub-client) we reject with **403** so the ownership
      boundary is visible (instead of silently dropping the override and
      returning 404 from a downstream lookup).
    """
    if org_id_query and user.role in _BACKOFFICE_ROLES:
        return org_id_query
    if org_id_query and org_id_query != user.org_id:
        raise HTTPException(
            403,
            f"Ownership violation: role={user.role} cannot operate on "
            f"org_id={org_id_query}. Sub-clients (N2) are independent tenants "
            f"and only their own client_admin can act on their resources.")
    return user.org_id


_ASSET_PRETTY = {
    "arsa": {"label": "ARSa", "symbol": "$", "caption": "peso digital 1:1"},
    "usdc": {"label": "USDC", "symbol": "US$", "caption": "USD Coin"},
    "usdt": {"label": "USDT", "symbol": "US$", "caption": "Tether USD"},
}


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
class CreateAccountIn(BaseModel):
    end_customer_id: Optional[str] = Field(None, min_length=3, max_length=64)
    display_name: Optional[str] = None
    account_type: FiatAccountType = FiatAccountType.BUSINESS
    chain: Optional[AvailableChain] = None   # resolved via chain_config if omitted
    holder_name: Optional[str] = None
    holder_tax_id: Optional[str] = None
    alias: Optional[str] = None


class RampAccountOut(BaseModel):
    end_customer_id: str
    provider: str
    provider_user_id: str
    account_name: Optional[str] = None
    wallet_address: Optional[str] = None
    wallet_chain: Optional[str] = None       # phase 18
    wallet_status: Optional[str] = None      # phase 18 — "pending" | "active"
    wallet_activated_at: Optional[str] = None
    cvu: Optional[str] = None
    alias: Optional[str] = None
    cvu_status: str                          # pending | completed
    onboarding_status: str                   # approved | pending_approval |
                                             # kyc_pending_andes | error |
                                             # rejected
    onboarding_message: Optional[str] = None
    created_at: str
    updated_at: str


class BalanceOut(BaseModel):
    asset_code: str       # "arsa"
    asset_label: str      # "ARSa"
    asset_symbol: str     # "$"
    asset_caption: str    # "peso digital 1:1"
    chain: str
    amount: str           # decimal string
    as_of: str


class BalancesOut(BaseModel):
    end_customer_id: str
    provider: str
    items: list[BalanceOut]


class FundingOut(BaseModel):
    cvu: Optional[str] = None
    alias: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal orchestrator (also called from KYB approval hooks)
# ---------------------------------------------------------------------------
async def ensure_org_ramp_account(
    *,
    org_id: str,
    end_customer_id: Optional[str] = None,
    display_name: Optional[str] = None,
    account_type: FiatAccountType = FiatAccountType.BUSINESS,
    chain: Optional[AvailableChain] = None,
    holder_name: Optional[str] = None,
    holder_tax_id: Optional[str] = None,
    alias: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> dict[str, Any]:
    """Idempotently provision the active provider's account+wallet+fiat for
    a given org. Never raises on graceful failures — see resilience contract
    at the top of this module. Returns the persisted `ramp_accounts` doc.

    If `chain` is None, it is resolved via `resolve_arsa_chain` (org-level
    default + account-level override).
    """
    end_customer_id = end_customer_id or org_id
    if chain is None:
        chain = await resolve_arsa_chain(org_id, end_customer_id)

    existing = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id, "end_customer_id": end_customer_id},
        {"_id": 0})
    if existing:
        return existing

    provider = await get_registry().resolve(org_id=org_id)
    onboarding_message: Optional[str] = None

    # 1) Account
    try:
        acc = await provider.create_account(
            org_id=org_id, end_customer_id=end_customer_id,
            display_name=display_name or f"{org_id}:{end_customer_id}")
    except NotSupportedByProvider as e:
        logger.warning("create_account failed for %s/%s: %s",
                          org_id, end_customer_id, e)
        doc = _stub_error_doc(org_id, end_customer_id,
                                 provider.provider_id, str(e),
                                 idempotency_key)
        await col(RAMP_ACCOUNTS).insert_one(dict(doc))
        doc.pop("_id", None)
        return doc

    onboarding_status = "approved"

    # 2) Wallet (ARSa / Stellar by default)
    wallet_address: Optional[str] = None
    try:
        w = await provider.ensure_wallet(
            andes_user_id=acc.provider_user_id,
            asset=WalletAsset.ARSA,
            chain=chain)
        wallet_address = w.address
    except NotSupportedByProvider as e:
        logger.warning("ensure_wallet skipped for %s: %s", org_id, e)

    # 3) Fiat / CVU
    fa_cvu: Optional[str] = None
    fa_alias: Optional[str] = None
    fa_cvu_status = "pending"
    # Phase 22+ — Guard: calling `/fiat` for an individual (USER) without
    # the 3 KYC files is guaranteed to fail at Andes and would leave us in
    # the synthetic `kyc_pending_andes` error state. Skip the call and
    # surface the explicit `kyc_docs_required` state so the frontend can
    # prompt the user to upload via the widget. Business (`USER` is the
    # value used here for individuals; `BUSINESS` keeps the old behaviour
    # because `/fiat/business` is JSON-only and doesn't require files).
    skip_fiat_for_individual = account_type == FiatAccountType.USER
    if skip_fiat_for_individual:
        onboarding_status = "kyc_docs_required"
        onboarding_message = (
            "Cuenta y wallet ARSa creadas. Falta que el usuario suba "
            "sus 3 documentos de identidad para emitir el CVU.")
        logger.info("ensure_org_ramp_account: skipping /fiat for USER %s "
                    "(no files) → kyc_docs_required", org_id)
    try:
        if skip_fiat_for_individual:
            raise NotSupportedByProvider("kyc_docs_required: files needed")
        fa = await provider.ensure_fiat_account(FiatAccountParams(
            org_id=org_id, end_customer_id=end_customer_id,
            account_type=account_type,
            chain=chain,
            holder_name=holder_name or display_name or end_customer_id,
            holder_tax_id=holder_tax_id,
            alias=alias),
            andes_user_id=acc.provider_user_id)
        fa_cvu = fa.cvu
        fa_alias = fa.alias
        fa_cvu_status = (fa.status.value if hasattr(fa.status, "value")
                          else str(fa.status))
        onboarding_status = (fa.onboarding_status.value
                              if hasattr(fa.onboarding_status, "value")
                              else str(fa.onboarding_status))
        await col(RAMP_FIAT_ACCOUNTS).update_one(
            {"org_id": org_id, "fiat_account_id": fa.fiat_account_id},
            {"$set": {
                "org_id": org_id, "fiat_account_id": fa.fiat_account_id,
                "ramp_account_id": acc.id,
                "provider": provider.provider_id,
                "account_type": fa.account_type.value,
                "cvu": fa.cvu, "alias": fa.alias,
                "holder_name": fa.holder_name, "holder_tax_id": fa.holder_tax_id,
                "status": fa_cvu_status, "onboarding_status": onboarding_status,
                "updated_at": _now_iso(),
            }, "$setOnInsert": {"created_at": _now_iso()}},
            upsert=True)
    except NotSupportedByProvider as e:
        logger.info("ensure_fiat_account pending (likely KYC docs missing) "
                       "for %s: %s", org_id, e)
        onboarding_status = "kyc_pending_andes"
        onboarding_message = (
            "Cuenta y wallet ARSa creadas. Falta el KYC de Andes "
            "(face, id_front, id_back) para emitir el CVU. Subí los "
            "documentos y reintentá desde el backoffice.")

    if wallet_address:
        # Phase 18 — Stellar wallets start `pending`; Base/EVM are active
        # immediately. The Andes wallet.active webhook flips Stellar to active.
        w_status = "active" if chain.value != "stellar" else "pending"
        w_activated = _now_iso() if w_status == "active" else None
        await col(RAMP_WALLETS).update_one(
            {"org_id": org_id, "provider_user_id": acc.provider_user_id,
              "asset": "arsa", "chain": chain.value},
            {"$set": {
                "org_id": org_id, "ramp_account_id": acc.id,
                "provider": provider.provider_id,
                "provider_user_id": acc.provider_user_id,
                "asset": "arsa", "chain": chain.value,
                "address": wallet_address,
                "status": w_status, "activated_at": w_activated,
                "updated_at": _now_iso(),
            }, "$setOnInsert": {"created_at": _now_iso()}},
            upsert=True)

    doc = {
        "id":                acc.id,
        "org_id":            org_id,
        "end_customer_id":   end_customer_id,
        "provider":          provider.provider_id,
        "provider_user_id":  acc.provider_user_id,
        "account_name":      acc.account_name,
        "wallet_address":    wallet_address,
        "cvu":               fa_cvu,
        "alias":             fa_alias,
        "cvu_status":        fa_cvu_status,
        "onboarding_status": onboarding_status,
        "onboarding_message": onboarding_message,
        "idempotency_key":   idempotency_key,
        "created_at":        _now_iso(),
        "updated_at":        _now_iso(),
    }
    await col(RAMP_ACCOUNTS).insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


def _stub_error_doc(org_id: str, end_customer_id: str, provider_id: str,
                      err_msg: str, idempotency_key: Optional[str]) -> dict:
    return {
        "id":                "acc_err_" + secrets.token_hex(4),
        "org_id":            org_id,
        "end_customer_id":   end_customer_id,
        "provider":          provider_id,
        "provider_user_id":  "",
        "account_name":      None,
        "wallet_address":    None,
        "cvu":               None,
        "alias":             None,
        "cvu_status":        "pending",
        "onboarding_status": "error",
        "onboarding_message": err_msg[:500],
        "idempotency_key":   idempotency_key,
        "created_at":        _now_iso(),
        "updated_at":        _now_iso(),
    }


async def _refresh_account(org_id: str, end_customer_id: str) -> dict:
    """Re-run the orchestrator steps that previously failed. Idempotent."""
    doc = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id, "end_customer_id": end_customer_id},
        {"_id": 0})
    if not doc:
        return await ensure_org_ramp_account(
            org_id=org_id, end_customer_id=end_customer_id)

    if doc.get("onboarding_status") not in {
            "error", "kyc_pending_andes", "pending_approval"}:
        return doc

    provider = await get_registry().resolve(org_id=org_id)

    # Ensure account
    provider_user_id = doc.get("provider_user_id") or ""
    if not provider_user_id:
        try:
            acc = await provider.create_account(
                org_id=org_id, end_customer_id=end_customer_id,
                display_name=doc.get("account_name") or end_customer_id)
            provider_user_id = acc.provider_user_id
            await col(RAMP_ACCOUNTS).update_one(
                {"org_id": org_id, "end_customer_id": end_customer_id},
                {"$set": {"id": acc.id,
                            "provider_user_id": provider_user_id,
                            "account_name": acc.account_name,
                            "updated_at": _now_iso()}})
            doc["id"] = acc.id
            doc["provider_user_id"] = provider_user_id
        except NotSupportedByProvider as e:
            await col(RAMP_ACCOUNTS).update_one(
                {"org_id": org_id, "end_customer_id": end_customer_id},
                {"$set": {"onboarding_status": "error",
                            "onboarding_message": str(e)[:500],
                            "updated_at": _now_iso()}})
            doc["onboarding_status"] = "error"
            doc["onboarding_message"] = str(e)
            return doc

    # Ensure wallet (always upsert ramp_wallets even if account already has
    # wallet_address — covers the case where the row was created before the
    # ramp_wallets persistence was wired in)
    effective_chain = await resolve_arsa_chain(org_id, end_customer_id)
    if not doc.get("wallet_address"):
        try:
            w = await provider.ensure_wallet(
                andes_user_id=provider_user_id,
                asset=WalletAsset.ARSA,
                chain=effective_chain)
            await col(RAMP_ACCOUNTS).update_one(
                {"org_id": org_id, "end_customer_id": end_customer_id},
                {"$set": {"wallet_address": w.address,
                            "updated_at": _now_iso()}})
            doc["wallet_address"] = w.address
        except NotSupportedByProvider as e:
            logger.warning("retry ensure_wallet failed: %s", e)
    if doc.get("wallet_address"):
        # Phase 18 — Stellar wallets start `pending`. Don't override if we
        # already have a row in `active` (e.g. wallet.active arrived first).
        prev_w = await col(RAMP_WALLETS).find_one(
            {"org_id": org_id, "provider_user_id": provider_user_id,
              "asset": "arsa", "chain": effective_chain.value},
            {"_id": 0, "status": 1, "activated_at": 1})
        if prev_w and prev_w.get("status") == "active":
            status = "active"
            activated_at = prev_w.get("activated_at")
        else:
            status = "active" if effective_chain.value != "stellar" else "pending"
            activated_at = _now_iso() if status == "active" else None
        await col(RAMP_WALLETS).update_one(
            {"org_id": org_id, "provider_user_id": provider_user_id,
              "asset": "arsa", "chain": effective_chain.value},
            {"$set": {
                "org_id": org_id, "ramp_account_id": doc["id"],
                "provider": provider.provider_id,
                "provider_user_id": provider_user_id,
                "asset": "arsa", "chain": effective_chain.value,
                "address": doc["wallet_address"],
                "status": status, "activated_at": activated_at,
                "updated_at": _now_iso(),
            }, "$setOnInsert": {"created_at": _now_iso()}},
            upsert=True)

    # Phase 22+ — For personal orgs, /fiat without files always fails. Skip
    # the call entirely and surface kyc_docs_required so the widget can
    # prompt the user. The admin retry endpoint with multipart files goes
    # through `services.andes_kyc.submit_andes_kyc_docs` instead.
    org_doc_for_retry = await col(ORGANIZATIONS).find_one(
        {"org_id": org_id}, {"_id": 0, "type": 1}) or {}
    is_personal_org = org_doc_for_retry.get("type") == "personal"
    if is_personal_org:
        friendly = (
            "Cuenta y wallet ARSa creadas. Falta que el usuario suba "
            "sus documentos de identidad para emitir el CVU.")
        await col(RAMP_ACCOUNTS).update_one(
            {"org_id": org_id, "end_customer_id": end_customer_id},
            {"$set": {"onboarding_status": "kyc_docs_required",
                        "onboarding_message": friendly,
                        "updated_at": _now_iso()}})
        doc["onboarding_status"] = "kyc_docs_required"
        doc["onboarding_message"] = friendly
        return doc

    # Ensure fiat / CVU (business path)
    try:
        fa = await provider.ensure_fiat_account(FiatAccountParams(
            org_id=org_id, end_customer_id=end_customer_id,
            account_type=FiatAccountType.BUSINESS,
            chain=effective_chain,
            holder_name=doc.get("account_name") or end_customer_id),
            andes_user_id=provider_user_id)
        new_status = (fa.onboarding_status.value
                       if hasattr(fa.onboarding_status, "value")
                       else str(fa.onboarding_status))
        # Persist the fiat account row (for the withdraw flow + admin)
        await col(RAMP_FIAT_ACCOUNTS).update_one(
            {"org_id": org_id, "fiat_account_id": fa.fiat_account_id},
            {"$set": {
                "org_id": org_id, "fiat_account_id": fa.fiat_account_id,
                "ramp_account_id": doc["id"],
                "provider": provider.provider_id,
                "account_type": fa.account_type.value,
                "cvu": fa.cvu, "alias": fa.alias,
                "holder_name": fa.holder_name,
                "holder_tax_id": fa.holder_tax_id,
                "status": fa.status.value if hasattr(fa.status, "value")
                            else str(fa.status),
                "onboarding_status": new_status,
                "updated_at": _now_iso(),
            }, "$setOnInsert": {"created_at": _now_iso()}},
            upsert=True)
        await col(RAMP_ACCOUNTS).update_one(
            {"org_id": org_id, "end_customer_id": end_customer_id},
            {"$set": {"cvu": fa.cvu, "alias": fa.alias,
                        "cvu_status": "completed" if fa.cvu else "pending",
                        "onboarding_status": new_status,
                        "onboarding_message": None,
                        "updated_at": _now_iso()}})
        doc.update({"cvu": fa.cvu, "alias": fa.alias,
                       "cvu_status": "completed" if fa.cvu else "pending",
                       "onboarding_status": new_status,
                       "onboarding_message": None})
    except NotSupportedByProvider as e:
        # Render a customer-friendly message; the raw gateway/SDK error is
        # noise for the end user. Operators can read the full error in the
        # admin audit log (the raw text is also logged below).
        raw_msg = str(e)
        logger.info("retry ensure_fiat_account pending for %s: %s",
                       org_id, raw_msg)
        friendly = (
            "Cuenta y wallet ARSa creadas. Falta el KYC/KYB de Andes "
            "para emitir el CVU. Subí los documentos y reintentá desde "
            "el backoffice.")
        await col(RAMP_ACCOUNTS).update_one(
            {"org_id": org_id, "end_customer_id": end_customer_id},
            {"$set": {"onboarding_status": "kyc_pending_andes",
                        "onboarding_message": friendly,
                        "updated_at": _now_iso()}})
        doc["onboarding_status"] = "kyc_pending_andes"
        doc["onboarding_message"] = friendly

    return doc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/accounts", response_model=RampAccountOut)
async def create_account(body: CreateAccountIn, request: Request,
                            user: CurrentUser = Depends(get_current_user),
                            org_id_q: Optional[str] = Query(None, alias="org_id"),
                            idempotency_key: Optional[str] = Header(
                                None, alias="Idempotency-Key")):
    """Alta completa: account → wallet ARSa/Stellar → fiat (CVU).

    Idempotente por (org_id, end_customer_id). Si la fiat no se puede crear
    por falta de KYC Andes, la cuenta queda en `kyc_pending_andes` y se puede
    reintentar desde el backoffice.
    """
    _require_finance(user)
    org_id = _resolve_org_scope(user, org_id_q)
    end_customer_id = body.end_customer_id or org_id

    doc = await ensure_org_ramp_account(
        org_id=org_id,
        end_customer_id=end_customer_id,
        display_name=body.display_name,
        account_type=body.account_type,
        chain=body.chain,
        holder_name=body.holder_name,
        holder_tax_id=body.holder_tax_id,
        alias=body.alias,
        idempotency_key=idempotency_key)

    await log_action(actor=user, action="ramp.account.created",
                       resource_type="ramp_account",
                       resource_id=doc.get("id", ""),
                       metadata={"end_customer_id": end_customer_id,
                                  "provider": doc.get("provider"),
                                  "onboarding_status": doc.get("onboarding_status")})
    return _account_view(await _enrich_with_wallet(doc))


@router.post("/accounts/{end_customer_id}/retry", response_model=RampAccountOut)
async def retry_account(end_customer_id: str,
                          user: CurrentUser = Depends(get_current_user),
                          org_id_q: Optional[str] = Query(None, alias="org_id")):
    """Reintenta los pasos que fallaron (típicamente fiat/KYC Andes)."""
    _require_finance(user)
    org_id = _resolve_org_scope(user, org_id_q)
    doc = await _refresh_account(org_id, end_customer_id)
    await log_action(actor=user, action="ramp.account.retry",
                       resource_type="ramp_account",
                       resource_id=doc.get("id", ""),
                       metadata={"end_customer_id": end_customer_id,
                                  "org_id": org_id,
                                  "onboarding_status": doc.get("onboarding_status")})
    return _account_view(await _enrich_with_wallet(doc))


@router.post("/accounts/{end_customer_id}/retry-with-docs",
              response_model=RampAccountOut)
async def retry_account_with_docs(
    end_customer_id: str,
    face: UploadFile = File(...),
    id_front: UploadFile = File(...),
    id_back: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    org_id_q: Optional[str] = Query(None, alias="org_id"),
):
    """Admin-side fallback: upload KYC docs on behalf of an individual user
    to unblock them. Goes through the same shared helper as the client
    widget so behaviour matches exactly.
    """
    _require_finance(user)
    org_id = _resolve_org_scope(user, org_id_q)

    files_payload: dict[str, tuple[str, bytes, str]] = {}
    for name, up in (("face", face), ("id_front", id_front),
                      ("id_back", id_back)):
        files_payload[name] = (up.filename or f"{name}.jpg",
                                await up.read(),
                                up.content_type or "image/jpeg")

    from services.andes_kyc import submit_andes_kyc_docs, AndesKycError
    try:
        await submit_andes_kyc_docs(
            org_id=org_id, files=files_payload, actor=user,
            source="admin_retry_with_docs")
    except AndesKycError as e:
        raise HTTPException(e.status, {"message": e.message,
                                         "retryable": e.retryable})

    # Re-fetch the (now updated) ramp_account doc to return the latest state.
    doc = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id, "end_customer_id": end_customer_id},
        {"_id": 0}) or {}
    await log_action(actor=user, action="ramp.account.retry_with_docs",
                       resource_type="ramp_account",
                       resource_id=doc.get("id", ""),
                       metadata={"end_customer_id": end_customer_id,
                                  "org_id": org_id,
                                  "onboarding_status": doc.get("onboarding_status")})
    return _account_view(await _enrich_with_wallet(doc))


@router.get("/accounts", response_model=list[RampAccountOut])
async def list_accounts(user: CurrentUser = Depends(get_current_user),
                          org_id_q: Optional[str] = Query(None, alias="org_id")):
    """Lista las cuentas de ramp para la org del caller (backoffice tab)."""
    org_id = _resolve_org_scope(user, org_id_q)
    cur = col(RAMP_ACCOUNTS).find({"org_id": org_id}, {"_id": 0})
    rows = await cur.to_list(length=200)
    return [_account_view(await _enrich_with_wallet(r)) for r in rows]


@router.get("/accounts/{end_customer_id}", response_model=RampAccountOut)
async def get_account(end_customer_id: str,
                        user: CurrentUser = Depends(get_current_user),
                        org_id_q: Optional[str] = Query(None, alias="org_id")):
    org_id = _resolve_org_scope(user, org_id_q)
    doc = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id, "end_customer_id": end_customer_id},
        {"_id": 0})
    if not doc:
        raise HTTPException(404, "Ramp account not found for this end_customer_id")
    return _account_view(await _enrich_with_wallet(doc))


@router.post("/accounts/{end_customer_id}/refresh-wallet-status",
                response_model=RampAccountOut)
async def refresh_wallet_status(end_customer_id: str,
                                     user: CurrentUser = Depends(get_current_user),
                                     org_id_q: Optional[str] = Query(
                                          None, alias="org_id")):
    """Phase 18 — poll the Andes gateway `GET /wallets/:userId` and reflect the
    current wallet status into ramp_wallets. Used as a fallback for the
    `wallet.active` webhook (e.g. if it's delayed or lost)."""
    org_id = _resolve_org_scope(user, org_id_q)
    doc = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id, "end_customer_id": end_customer_id},
        {"_id": 0})
    if not doc:
        raise HTTPException(404, "ramp account not found")

    gateway_url = os.environ.get("ANDES_GATEWAY_URL",
                                       "http://localhost:8090").rstrip("/")
    gateway_tok = os.environ.get("GATEWAY_INTERNAL_TOKEN",
                                       "dev-internal-token-change-me")
    pu = doc.get("provider_user_id") or ""
    if not pu:
        return _account_view(await _enrich_with_wallet(doc))

    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.get(f"{gateway_url}/wallets/{pu}",
                              headers={"X-Internal-Token": gateway_tok})
    if r.status_code != 200:
        logger.warning("refresh-wallet-status gateway %s: %s",
                          r.status_code, r.text[:200])
        return _account_view(await _enrich_with_wallet(doc))

    wallets = (r.json() or {}).get("wallets") or []
    for w in wallets:
        asset = (w.get("asset") or "").lower()
        chain = (w.get("chain") or "").lower()
        status = (w.get("status") or "active").lower()
        if asset != "arsa":
            continue
        prev = await col(RAMP_WALLETS).find_one(
            {"org_id": org_id, "provider_user_id": pu,
              "asset": asset, "chain": chain},
            {"_id": 0, "status": 1, "activated_at": 1})
        already_active = bool(prev and prev.get("status") == "active")
        new_activated = (
            prev.get("activated_at") if already_active and prev
            else (w.get("activated_at") or _now_iso())
        ) if status == "active" else None
        await col(RAMP_WALLETS).update_one(
            {"org_id": org_id, "provider_user_id": pu,
              "asset": asset, "chain": chain},
            {"$set": {"status": status,
                        "activated_at": new_activated,
                        "address": w.get("address") or "",
                        "updated_at": _now_iso()},
              "$setOnInsert": {"org_id": org_id,
                                "provider_user_id": pu,
                                "asset": asset, "chain": chain,
                                "ramp_account_id": doc["id"],
                                "provider": "andeslabs",
                                "created_at": _now_iso()}},
            upsert=True)

    await log_action(actor=user, action="ramp.wallet.refresh_status",
                       resource_type="ramp_account",
                       resource_id=doc.get("id", ""),
                       metadata={"end_customer_id": end_customer_id,
                                  "checked": len(wallets)})

    fresh = await col(RAMP_ACCOUNTS).find_one(
        {"id": doc["id"]}, {"_id": 0})
    return _account_view(await _enrich_with_wallet(fresh or doc))




@router.get("/accounts/{end_customer_id}/balances", response_model=BalancesOut)
async def get_balances(end_customer_id: str,
                         user: CurrentUser = Depends(get_current_user),
                         org_id_q: Optional[str] = Query(None, alias="org_id")):
    org_id = _resolve_org_scope(user, org_id_q)
    doc = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id, "end_customer_id": end_customer_id},
        {"_id": 0, "provider": 1, "provider_user_id": 1, "id": 1})
    if not doc:
        raise HTTPException(404, "Ramp account not found")
    provider = await get_registry().resolve(org_id=org_id)
    try:
        balances = await provider.get_balances(
            andes_user_id=doc["provider_user_id"])
    except NotSupportedByProvider as e:
        raise HTTPException(502, f"Provider error: {e}")

    items: list[BalanceOut] = []
    now = _now_iso()
    for b in balances:
        code = (b.asset.value if hasattr(b.asset, "value") else str(b.asset)).lower()
        pretty = _ASSET_PRETTY.get(code, {"label": code.upper(),
                                            "symbol": "",
                                            "caption": ""})
        items.append(BalanceOut(
            asset_code=code,
            asset_label=pretty["label"],
            asset_symbol=pretty["symbol"],
            asset_caption=pretty["caption"],
            chain=(b.chain.value if hasattr(b.chain, "value") else str(b.chain)),
            amount=str(b.balance),
            as_of=now))
        await col(RAMP_BALANCES).update_one(
            {"ramp_account_id": doc["id"],
              "asset": code, "chain": items[-1].chain},
            {"$set": {
                "ramp_account_id": doc["id"], "asset": code,
                "chain": items[-1].chain, "balance": str(b.balance),
                "as_of": now}},
            upsert=True)

    # If the provider returned no rows, still expose the ARSa skeleton at 0
    # so the UI can render the "peso digital 1:1" card. Use the org's
    # currently configured effective chain so the badge matches.
    if not items:
        eff = await resolve_arsa_chain(org_id, end_customer_id)
        pretty = _ASSET_PRETTY["arsa"]
        items.append(BalanceOut(
            asset_code="arsa",
            asset_label=pretty["label"],
            asset_symbol=pretty["symbol"],
            asset_caption=pretty["caption"],
            chain=eff.value,
            amount="0",
            as_of=now))

    await log_action(actor=user, action="ramp.balances.read",
                       resource_type="ramp_account", resource_id=doc["id"],
                       metadata={"end_customer_id": end_customer_id,
                                  "count": len(items)})
    return BalancesOut(end_customer_id=end_customer_id,
                         provider=doc["provider"], items=items)


@router.get("/accounts/{end_customer_id}/funding", response_model=FundingOut)
async def get_funding(end_customer_id: str,
                        user: CurrentUser = Depends(get_current_user),
                        org_id_q: Optional[str] = Query(None, alias="org_id")):
    org_id = _resolve_org_scope(user, org_id_q)
    doc = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id, "end_customer_id": end_customer_id},
        {"_id": 0, "provider_user_id": 1, "cvu": 1, "alias": 1, "id": 1})
    if not doc:
        raise HTTPException(404, "Ramp account not found")
    provider = await get_registry().resolve(org_id=org_id)
    try:
        info = await provider.get_funding_instructions(
            andes_user_id=doc["provider_user_id"])
    except NotSupportedByProvider:
        info = {"cvu": doc.get("cvu"), "alias": doc.get("alias")}
    cvu = info.get("cvu") or doc.get("cvu")
    alias = info.get("alias") or doc.get("alias")

    if cvu and cvu != doc.get("cvu"):
        await col(RAMP_ACCOUNTS).update_one(
            {"id": doc["id"]},
            {"$set": {"cvu": cvu, "alias": alias,
                       "cvu_status": "completed",
                       "updated_at": _now_iso()}})

    return FundingOut(cvu=cvu, alias=alias)


# ---------------------------------------------------------------------------
# View helpers
# ---------------------------------------------------------------------------
def _account_view(doc: dict[str, Any]) -> RampAccountOut:
    # Pull the ARSa wallet (chain may be either stellar or base) for status info
    return RampAccountOut(
        end_customer_id=doc.get("end_customer_id", ""),
        provider=doc.get("provider", ""),
        provider_user_id=doc.get("provider_user_id", ""),
        account_name=doc.get("account_name"),
        wallet_address=doc.get("wallet_address"),
        wallet_chain=doc.get("_wallet_chain"),
        wallet_status=doc.get("_wallet_status"),
        wallet_activated_at=doc.get("_wallet_activated_at"),
        cvu=doc.get("cvu"),
        alias=doc.get("alias"),
        cvu_status=doc.get("cvu_status") or "pending",
        onboarding_status=doc.get("onboarding_status") or "pending_approval",
        onboarding_message=doc.get("onboarding_message"),
        created_at=doc.get("created_at") or _now_iso(),
        updated_at=doc.get("updated_at") or _now_iso())


async def _enrich_with_wallet(doc: dict[str, Any]) -> dict[str, Any]:
    """Attach `_wallet_status` / `_wallet_chain` / `_wallet_activated_at` from
    ramp_wallets (single-source-of-truth for status). Returns the same dict."""
    if not doc.get("provider_user_id"):
        return doc
    w = await col(RAMP_WALLETS).find_one(
        {"provider_user_id": doc["provider_user_id"], "asset": "arsa"},
        {"_id": 0, "status": 1, "chain": 1, "activated_at": 1, "address": 1})
    if w:
        doc["_wallet_status"]       = w.get("status")
        doc["_wallet_chain"]        = w.get("chain")
        doc["_wallet_activated_at"] = w.get("activated_at")
        # Keep the canonical address in sync if the row was upserted later
        # (e.g. via webhook before the account doc was patched).
        if not doc.get("wallet_address") and w.get("address"):
            doc["wallet_address"] = w["address"]
    return doc


# ---------------------------------------------------------------------------
# Phase 15.1 — Offramp (withdraw) + movements + CVU lookup
# ---------------------------------------------------------------------------
import httpx  # noqa: E402


# Per-org ARSa caps. We persist them on `organizations.caps` so the existing
# cap UI can manage them too. Defaults are intentionally generous for demo.
_DEFAULT_DAILY_CAP_ARSA   = 5_000_000.0   # ARSa $ 5.000.000 / día
_DEFAULT_MONTHLY_CAP_ARSA = 50_000_000.0  # ARSa $ 50.000.000 / mes


class WithdrawIn(BaseModel):
    amount: str = Field(..., description="ARSa amount as decimal string")
    to_cvu: Optional[str] = None
    to_alias: Optional[str] = None
    holder_name_confirmed: Optional[str] = Field(
        None, description="Holder name the user saw and confirmed (audit)")


class MovementOut(BaseModel):
    id: str
    kind: str                # deposit | withdrawal
    asset: str               # arsa
    asset_label: str         # ARSa
    asset_symbol: str        # $
    chain: str
    amount: str
    status: str              # TxStatus
    fail_reason: Optional[str] = None
    destination_cvu: Optional[str] = None
    destination_alias: Optional[str] = None
    destination_name: Optional[str] = None
    external_id: Optional[str] = None
    prosper_tx_id: Optional[str] = None
    created_at: str
    settled_at: Optional[str] = None


class CvuLookupOut(BaseModel):
    cvu: Optional[str] = None
    alias: Optional[str] = None
    holder_name: Optional[str] = None
    holder_tax_id: Optional[str] = None
    bank: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _gateway_url() -> str:
    return (os.environ.get("ANDES_GATEWAY_URL")
              or "http://localhost:8090").rstrip("/")


def _gateway_token() -> str:
    return os.environ.get("GATEWAY_INTERNAL_TOKEN",
                            "dev-internal-token-change-me")


async def _sum_withdrawals_since(org_id: str, since_iso: str) -> float:
    cur = col(RAMP_MOVEMENTS).aggregate([
        {"$match": {"org_id": org_id, "kind": "withdrawal",
                     "asset": "arsa",
                     "status": {"$in": ["Pending", "Success"]},
                     "created_at": {"$gte": since_iso}}},
        {"$group": {"_id": None,
                      "total": {"$sum": {"$toDouble": "$amount"}}}},
    ])
    rows = await cur.to_list(length=1)
    return float(rows[0]["total"]) if rows else 0.0


async def _check_arsa_caps(org_id: str, amount: float) -> None:
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id},
                                              {"_id": 0, "caps": 1}) or {}
    caps = (org.get("caps") or {})
    daily = float(caps.get("arsa_withdraw_daily_cap_arsa",
                              _DEFAULT_DAILY_CAP_ARSA))
    monthly = float(caps.get("arsa_withdraw_monthly_cap_arsa",
                                _DEFAULT_MONTHLY_CAP_ARSA))

    now = datetime.now(timezone.utc)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    today = await _sum_withdrawals_since(org_id, day0.isoformat())
    this_month = await _sum_withdrawals_since(org_id, month0.isoformat())

    if today + amount > daily:
        raise HTTPException(409,
            f"Daily ARSa withdraw cap exceeded "
            f"(today={today:.2f}, requested={amount:.2f}, cap={daily:.2f})")
    if this_month + amount > monthly:
        raise HTTPException(409,
            f"Monthly ARSa withdraw cap exceeded "
            f"(month={this_month:.2f}, requested={amount:.2f}, "
            f"cap={monthly:.2f})")


# ---------------------------------------------------------------------------
# Routes — CVU lookup
# ---------------------------------------------------------------------------
@router.get("/cvu-lookup", response_model=CvuLookupOut)
async def cvu_lookup(cvu: Optional[str] = Query(None),
                       alias: Optional[str] = Query(None),
                       user: CurrentUser = Depends(get_current_user)):
    """Resolve the holder of a destination CVU/alias before confirming a
    withdrawal. Pass through to the gateway."""
    _require_finance(user)
    if not cvu and not alias:
        raise HTTPException(400, "provide cvu or alias")
    qs = {}
    if cvu:   qs["cvu"]   = cvu
    if alias: qs["alias"] = alias
    try:
        async with httpx.AsyncClient(timeout=15.0) as cx:
            r = await cx.get(f"{_gateway_url()}/fiat/cvu-lookup",
                                headers={"X-Internal-Token": _gateway_token()},
                                params=qs)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"gateway unreachable: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code,
                            f"lookup failed: {r.text[:200]}")
    d = r.json() if r.text else {}
    return CvuLookupOut(
        cvu=d.get("cvu") or cvu,
        alias=d.get("alias") or alias,
        holder_name=d.get("holderName") or d.get("holder_name"),
        holder_tax_id=d.get("holderTaxId") or d.get("holder_tax_id"),
        bank=d.get("bank"))


# ---------------------------------------------------------------------------
# Routes — Withdraw (offramp)
# ---------------------------------------------------------------------------
@router.post("/accounts/{end_customer_id}/withdraw", response_model=MovementOut)
async def withdraw(end_customer_id: str, body: WithdrawIn,
                     user: CurrentUser = Depends(get_current_user),
                     org_id_q: Optional[str] = Query(None, alias="org_id"),
                     idempotency_key: Optional[str] = Header(
                         None, alias="Idempotency-Key")):
    """ARSa offramp: debits the wallet and submits the fiat withdrawal to
    Andes. The terminal status arrives via webhook (`fiat.withdrawal.success`
    or `.failed`)."""
    _require_finance(user)
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    if not body.to_cvu and not body.to_alias:
        raise HTTPException(400, "to_cvu or to_alias is required")

    org_id = _resolve_org_scope(user, org_id_q)

    # Locate the ramp account
    acc = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id, "end_customer_id": end_customer_id},
        {"_id": 0})
    if not acc:
        raise HTTPException(404, "Ramp account not found")
    if acc.get("onboarding_status") != "approved":
        raise HTTPException(409,
            f"Ramp account not approved (status={acc.get('onboarding_status')})")

    # Idempotency on (org_id, idempotency_key) inside ramp_movements
    existing = await col(RAMP_MOVEMENTS).find_one(
        {"org_id": org_id, "idempotency_key": idempotency_key,
          "kind": "withdrawal"},
        {"_id": 0})
    if existing:
        return _movement_view(existing)

    # Parse + validate amount
    try:
        amount_num = float(body.amount)
    except ValueError:
        raise HTTPException(400, "amount must be a number")
    if amount_num <= 0:
        raise HTTPException(400, "amount must be > 0")

    # Per-org ARSa caps
    await _check_arsa_caps(org_id, amount_num)

    # Locate the fiat account id (CVU container) — required by Andes
    fa = await col(RAMP_FIAT_ACCOUNTS).find_one(
        {"org_id": org_id, "ramp_account_id": acc["id"]},
        {"_id": 0, "fiat_account_id": 1})
    fiat_account_id = (fa or {}).get("fiat_account_id")

    # Resolve effective chain for this account (override / org default)
    effective_chain = await resolve_arsa_chain(org_id, end_customer_id)

    # Call the gateway
    gateway_body = {
        "user_id":         acc["provider_user_id"],
        "fiat_account_id": fiat_account_id,
        "chain":           effective_chain.value,
        "asset":           "arsa",
        "amount":          body.amount,
        "to_cvu":          body.to_cvu,
        "to_alias":        body.to_alias,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.post(f"{_gateway_url()}/fiat/withdraw",
                                 headers={"X-Internal-Token": _gateway_token(),
                                            "Content-Type": "application/json"},
                                 json=gateway_body)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"gateway unreachable: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code,
                            f"withdraw rejected: {r.text[:200]}")
    rj = r.json() if r.text else {}
    ext_id = str(rj.get("transactionId") or rj.get("transaction_id")
                  or "wd_" + secrets.token_hex(6))
    initial_status = str(rj.get("status") or "Pending")

    # Persist movement
    mv = {
        "id":               "mv_" + secrets.token_hex(6),
        "org_id":           org_id,
        "ramp_account_id":  acc["id"],
        "provider":         "andeslabs",
        "provider_user_id": acc["provider_user_id"],
        "external_id":      ext_id,
        "kind":             "withdrawal",
        "asset":            "arsa",
        "chain":            effective_chain.value,
        "amount":           body.amount,
        "status":           initial_status,
        "destination_cvu":  body.to_cvu,
        "destination_alias": body.to_alias,
        "destination_name": body.holder_name_confirmed,
        "prosper_tx_id":    "prosper_wd_" + secrets.token_hex(6),
        "idempotency_key":  idempotency_key,
        "raw":              {"submission": gateway_body, "response": rj},
        "occurred_at":      _now_iso(),
        "created_at":       _now_iso(),
        "updated_at":       _now_iso(),
    }
    await col(RAMP_MOVEMENTS).insert_one(dict(mv))

    # Decrement cached balance immediately (the gateway already debited)
    prev = await col(RAMP_BALANCES).find_one(
        {"ramp_account_id": acc["id"], "asset": "arsa",
          "chain": effective_chain.value},
        {"_id": 0, "balance": 1})
    if prev:
        new_bal = max(0.0, float(prev.get("balance") or 0) - amount_num)
        await col(RAMP_BALANCES).update_one(
            {"ramp_account_id": acc["id"], "asset": "arsa",
              "chain": effective_chain.value},
            {"$set": {"balance": str(new_bal), "as_of": _now_iso()}})

    await log_action(actor=user, action="ramp.withdraw.submit",
                       resource_type="ramp_movement", resource_id=mv["id"],
                       metadata={"org_id": org_id, "amount": body.amount,
                                  "to_cvu": body.to_cvu, "to_alias": body.to_alias,
                                  "ext_id": ext_id, "status": initial_status})
    return _movement_view(mv)


# ---------------------------------------------------------------------------
# Routes — Movements list
# ---------------------------------------------------------------------------
@router.get("/accounts/{end_customer_id}/movements",
              response_model=list[MovementOut])
async def list_movements(end_customer_id: str,
                            limit: int = Query(50, ge=1, le=200),
                            user: CurrentUser = Depends(get_current_user),
                            org_id_q: Optional[str] = Query(None, alias="org_id")):
    org_id = _resolve_org_scope(user, org_id_q)
    acc = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id, "end_customer_id": end_customer_id},
        {"_id": 0, "id": 1, "provider": 1, "provider_user_id": 1})
    if not acc:
        raise HTTPException(404, "Ramp account not found")

    # Live sync from Andes before reading the cache, so the dashboard
    # always reflects deposits/withdrawals the customer made — even if
    # the webhook delivery didn't arrive. This is the single source of
    # truth bridge: Andes API → ramp_movements.
    if acc.get("provider") == "andeslabs" and acc.get("provider_user_id"):
        try:
            await _sync_andes_movements_to_cache(
                org_id=org_id, ramp_account_id=acc["id"],
                andes_user_id=acc["provider_user_id"], limit=max(limit, 50))
        except Exception as e:                                # noqa: BLE001
            logger.warning("andes movement sync failed for org=%s: %s",
                              org_id, e)

    cur = col(RAMP_MOVEMENTS).find(
        {"ramp_account_id": acc["id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(limit)
    rows = await cur.to_list(length=limit)
    return [_movement_view(r) for r in rows]


async def _sync_andes_movements_to_cache(
    *, org_id: str, ramp_account_id: str, andes_user_id: str,
    limit: int = 200,
) -> int:
    """Pull movements from Andes (`andes.fiat.movementsForUser`) and
    upsert each row into the local `ramp_movements` collection. Returns
    how many rows were newly persisted. Idempotent on (external_id).

    The Andes payload looks like:
        { id, type: "deposit"|"withdraw"|"transfer", amount, status,
          occurred_at, chain, fiat_account_id, user_id, wallet_id,
          destination_cbu, destination_name, ... }

    We map it to our internal shape so the rest of the codebase (the
    dashboard, the transactions feed, the admin monitor) reads from a
    stable schema regardless of provider.
    """
    from ramp.adapters.andes import AndesAdapter
    rows = await AndesAdapter().list_movements(
        andes_user_id=andes_user_id, limit=limit)
    if not rows:
        return 0
    persisted = 0
    for r in rows:
        external_id = r.get("id")
        if not external_id:
            continue
        kind_raw = (r.get("type") or "").lower()
        if kind_raw not in ("deposit", "withdraw", "withdrawal", "transfer"):
            continue
        kind = "withdraw" if kind_raw in ("withdraw", "withdrawal") else kind_raw
        doc = {
            "ramp_account_id":  ramp_account_id,
            "org_id":           org_id,
            "external_id":      external_id,
            "kind":             kind,
            "asset":            "arsa",
            "chain":            r.get("chain") or "stellar",
            "amount":           str(r.get("amount") or "0"),
            "status":           r.get("status") or "Pending",
            "destination_cvu":  r.get("destination_cbu")
                                  or r.get("destination_cvu"),
            "destination_name": r.get("destination_name"),
            "destination_alias": r.get("destination_alias"),
            "occurred_at":      r.get("occurred_at"),
            "created_at":       r.get("occurred_at") or _now_iso(),
            "settled_at":       r.get("occurred_at")
                                  if r.get("status") == "Success" else None,
            "is_deleted":       False,
            "source":           "andes_sync",
        }
        # Idempotent upsert on (ramp_account_id, external_id).
        result = await col(RAMP_MOVEMENTS).update_one(
            {"ramp_account_id": ramp_account_id, "external_id": external_id},
            {"$set": doc,
              "$setOnInsert": {"id": "rmv_" + secrets.token_hex(6)}},
            upsert=True)
        if result.upserted_id is not None:
            persisted += 1
    return persisted


def _movement_view(doc: dict[str, Any]) -> MovementOut:
    asset = (doc.get("asset") or "arsa").lower()
    pretty = _ASSET_PRETTY.get(asset, {"label": asset.upper(), "symbol": ""})
    return MovementOut(
        id=doc.get("id", ""),
        kind=doc.get("kind", ""),
        asset=asset,
        asset_label=pretty["label"],
        asset_symbol=pretty["symbol"],
        chain=doc.get("chain", "stellar"),
        amount=str(doc.get("amount", "0")),
        status=str(doc.get("status", "Pending")),
        fail_reason=doc.get("fail_reason"),
        destination_cvu=doc.get("destination_cvu"),
        destination_alias=doc.get("destination_alias"),
        destination_name=doc.get("destination_name"),
        external_id=doc.get("external_id"),
        prosper_tx_id=doc.get("prosper_tx_id"),
        created_at=doc.get("created_at") or _now_iso(),
        settled_at=doc.get("settled_at"))
