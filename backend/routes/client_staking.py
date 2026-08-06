"""Client-portal Staking module — mirrors the admin CMS staking surface.

Per user directive (June 2026): staking is available from ANY portal
client (all client roles, especially `client_admin`) with the SAME
access level as the admin module — full stakings listing, CMS wallets
listing, account creation and cash-in creation for any email.

Backend of record is the Prosper CMS (`cmsback.protocol-prosper.io`);
these are thin passthroughs sharing helpers with
`routes/phase22_admin_yield.py`.
"""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from routes.phase22_admin_yield import emails_payload, stakings_payload

router = APIRouter(prefix="/client/staking", tags=["client-staking"])


@router.get("/stakings")
async def client_list_stakings(
        scope: str = Query("all", regex="^(all|ours|external)$"),
        asset: Optional[str] = Query(None, regex="^(arsa|usdc)$"),
        status: Optional[str] = Query(None,
            regex="^(active|matured|redeemed)$"),
        user: CurrentUser = Depends(get_current_user)):
    return await stakings_payload(scope=scope, asset=asset, status=status)


@router.get("/emails")
async def client_list_emails(user: CurrentUser = Depends(get_current_user)):
    return await emails_payload()


@router.get("/cms/wallets")
async def client_list_cms_wallets(
        user: CurrentUser = Depends(get_current_user)):
    import os
    from integrations.prosper import get_adapter, ProsperError
    adapter = get_adapter()
    fn = getattr(adapter, "list_cms_users", None)
    if fn is None:
        raise HTTPException(501, "adapter does not support list_cms_users")
    try:
        data = await fn()
    except ProsperError as e:
        raise HTTPException(502, f"CMS users read failed: {e}")
    from routes.phase22_admin_yield import _iso
    items = data.get("items", [])
    return {"items":      items,
             "raw":        data.get("raw"),
             "total":      len(items),
             "mode":       os.environ.get("PROSPER_MODE", "mock"),
             "fetched_at": _iso()}


class ClientCmsUserBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


@router.post("/cms/users")
async def client_create_cms_account(
        body: ClientCmsUserBody,
        user: CurrentUser = Depends(get_current_user)):
    from integrations.prosper import get_adapter, ProsperError
    email = body.email.strip().lower()
    fn = getattr(get_adapter(), "create_cms_user", None)
    if fn is None:
        raise HTTPException(501, "adapter does not support create_cms_user")
    try:
        r = await fn(email=email)
    except ProsperError as e:
        if "ya existe" in str(e).lower():
            raise HTTPException(409, "El usuario ya existe en el CMS")
        raise HTTPException(502, f"CMS create user failed: {e}")
    await log_action(
        actor=user, action="client.staking.cms.user_created",
        resource_type="prosper_cms_user", resource_id=email,
        metadata={"user_id": r.get("user_id")})
    return {"email": email, "user_id": r.get("user_id"), "raw": r.get("raw")}


class ClientCmsCashinBody(BaseModel):
    email: str | None = Field(None, min_length=3, max_length=254)
    prosper_id: str | None = Field(None, min_length=1, max_length=128)
    modality: str = Field(..., pattern="^(end|month)$")


@router.post("/cms/cashin")
async def client_create_cms_cashin(
        body: ClientCmsCashinBody,
        user: CurrentUser = Depends(get_current_user)):
    from integrations.prosper import get_adapter, ProsperError
    prosper_id = (body.email or body.prosper_id or "").strip()
    if not prosper_id:
        raise HTTPException(422, "email is required")
    ptx = "cli_" + secrets.token_hex(8)
    try:
        w = await get_adapter().create_user_wallet(
            user_reference_id=prosper_id,
            prosper_tx_id=ptx,
            modality=body.modality)
    except ProsperError as e:
        raise HTTPException(502, f"CMS cashin failed: {e}")
    reused = bool((w.raw or {}).get("reused"))
    await log_action(
        actor=user, action="client.staking.cms.cashin",
        resource_type="prosper_wallet", resource_id=prosper_id,
        metadata={"modality": body.modality, "address": w.address,
                   "status": w.status, "reused": reused,
                   "prosper_tx_id": ptx})
    return {"prosper_id": prosper_id,
             "email":      prosper_id,
             "modality":   body.modality,
             "address":    w.address,
             "status":     w.status,
             "reused":     reused,
             "tx_hash":    w.tx_hash,
             "raw":        w.raw}
