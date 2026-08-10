"""Client-portal Staking module — scoped view of the CMS staking surface.

Per user directive (Aug 2026): a client (client_admin / client_user)
should see ONLY their own stakings and wallets — matched by the email
on the JWT session, which is the same email used to create each
cash-in at the CMS.

The manual "create CMS user / cashin" endpoints are intentionally NOT
exposed to client roles: the only supported path to obtain a new
Prosper wallet is through `/client/invest/onchain` (which provisions
the wallet as a side-effect of an investment). Internal roles keep the
admin routes with full visibility and mutation power (see
`routes/phase22_admin_yield.py`).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import CurrentUser, get_current_user
from db import col, ORGANIZATIONS, POSITIONS
from integrations.prosper import get_adapter
from routes.phase22_admin_yield import _iso, cms_wallets_payload

router = APIRouter(prefix="/client/staking", tags=["client-staking"])


def _current_email(user: CurrentUser) -> str:
    email = (getattr(user, "email", "") or "").strip().lower()
    if not email:
        raise HTTPException(401, "No email on session")
    return email


def _is_internal(user: CurrentUser) -> bool:
    try:
        return is_internal(Role(user.role))
    except (ValueError, AttributeError):
        return False


@router.get("/stakings")
async def client_list_stakings(
        scope: str = Query("all", regex="^(all|ours|external)$"),
        asset: Optional[str] = Query(None, regex="^(arsa|usdc)$"),
        status: Optional[str] = Query(None,
            regex="^(active|matured|redeemed)$"),
        user: CurrentUser = Depends(get_current_user)):
    """Return stakings strictly scoped to the logged-in client organization/user."""
    user_wallets: set[str] = set()
    org_name: str = user.email or "Organización"
    if user.org_id:
        org = await col(ORGANIZATIONS).find_one(
            {"org_id": user.org_id, "is_deleted": {"$ne": True}},
            {"_id": 0, "prosper_wallets": 1, "stellar_address": 1, "commercial_name": 1, "legal_name": 1})
        if org:
            org_name = org.get("commercial_name") or org.get("legal_name") or user.email or org.get("org_id")
            for w in (org.get("prosper_wallets") or []):
                addr = str(w.get("address") or "").strip().lower()
                if addr:
                    user_wallets.add(addr)
            if org.get("stellar_address"):
                user_wallets.add(str(org["stellar_address"]).strip().lower())

    client_email = user.email.strip().lower() if user.email else "cliente"

    match_or: list[dict] = []
    if user.user_id:
        match_or.append({"user_id": user.user_id})
    if user.org_id:
        match_or.append({"org_id": user.org_id})
    if user_wallets:
        w_list = list(user_wallets) + [w.upper() for w in user_wallets] + [w.lower() for w in user_wallets]
        match_or.append({"wallet": {"$in": list(set(w_list))}})

    if not match_or:
        return {
            "ours": {"items": [], "by_org": [], "total": 0},
            "external": {"items": [], "total": 0, "note": ""},
            "total": 0,
            "fetched_at": _iso()
        }

    query: dict = {
        "$or": match_or,
        "wallet": {"$exists": True, "$ne": None},
        "memo": {"$exists": True, "$ne": None},
        "is_deleted": {"$ne": True},
        "external": {"$ne": True}
    }
    if isinstance(asset, str):
        query["asset"] = asset
    if isinstance(status, str):
        query["status"] = status

    rows = await col(POSITIONS).find(query, {"_id": 0}).sort("updated_at", -1).to_list(200)

    for p in rows:
        p["client_email"] = client_email
        p["contract_email"] = client_email

    by_org = []
    if rows:
        arsa_amt = sum(float(p.get("principal_native") or 0) for p in rows if p.get("asset") == "arsa")
        usdc_amt = sum(float(p.get("principal_native") or 0) for p in rows if p.get("asset") != "arsa")
        active_cnt = sum(1 for p in rows if p.get("status") == "active")
        by_org = [{
            "org_id": user.org_id or "client_org",
            "name": org_name,
            "positions": rows,
            "principal_arsa": arsa_amt,
            "principal_usdc": usdc_amt,
            "active_count": active_cnt
        }]

    return {
        "ours": {
            "items": rows,
            "by_org": by_org,
            "total": len(rows)
        },
        "external": {
            "items": [],
            "total": 0,
            "note": ""
        },
        "total": len(rows),
        "fetched_at": _iso()
    }


@router.get("/emails")
async def client_list_emails(user: CurrentUser = Depends(get_current_user)):
    email = user.email.strip().lower() if user.email else None
    emails = [email] if email else []
    items = []
    wallets = []
    if user.org_id:
        org = await col(ORGANIZATIONS).find_one(
            {"org_id": user.org_id, "is_deleted": {"$ne": True}},
            {"_id": 0, "prosper_wallets": 1, "commercial_name": 1, "legal_name": 1}
        )
        if org:
            wallets = list(org.get("prosper_wallets") or [])
    if email:
        items.append({
            "email": email,
            "org_id": user.org_id or email,
            "user_id": user.user_id,
            "name": email,
            "prosper_wallets": wallets,
        })
    return {"emails": emails, "items": items, "total": len(items)}


@router.get("/cms/wallets")
async def client_list_cms_wallets(
        user: CurrentUser = Depends(get_current_user)):
    """Return CMS wallets for the logged-in client organization's prosper_wallets."""
    import os

    client_email = user.email.strip().lower() if user.email else "cliente"
    items: list[dict] = []
    seen_addr_mod: set[str] = set()

    if user.org_id:
        org = await col(ORGANIZATIONS).find_one(
            {"org_id": user.org_id, "is_deleted": {"$ne": True}},
            {"_id": 0, "org_id": 1, "prosper_wallets": 1, "stellar_address": 1}
        )
        if org:
            for w in (org.get("prosper_wallets") or []):
                addr = str(w.get("address") or "").strip()
                mod = str(w.get("modality") or "end").strip().lower()
                if addr:
                    key = f"{addr.lower()}_{mod}"
                    if key not in seen_addr_mod:
                        seen_addr_mod.add(key)
                        items.append({
                            "prosperId": user.org_id,
                            "userId": user.org_id,
                            "email": client_email,
                            "address": addr,
                            "cashin": mod,
                            "modality": mod,
                            "integration": "prosper",
                            "createdAt": w.get("provisioned_at") or _iso(),
                        })

    all_cms = await cms_wallets_payload()
    for it in all_cms.get("items", []):
        w_addr = str(it.get("address") or "").strip()
        w_email = str(it.get("email") or "").strip().lower()
        w_pid = str(it.get("prosperId") or it.get("userId") or "").strip()
        w_mod = str(it.get("cashin") or it.get("modality") or "").strip().lower()
        key = f"{w_addr.lower()}_{w_mod}"
        if (w_email == client_email or (user.org_id and w_pid == user.org_id)) and key not in seen_addr_mod:
            seen_addr_mod.add(key)
            it["email"] = client_email
            items.append(it)

    return {
        "items": items,
        "raw": [],
        "total": len(items),
        "mode": os.environ.get("PROSPER_MODE", "mock"),
        "fetched_at": _iso()
    }


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
    org_id: str | None = Field(None, min_length=1, max_length=128)
    modality: str = Field(..., pattern="^(end|month)$")


@router.post("/cms/cashin")
async def client_create_cms_cashin(
        body: ClientCmsCashinBody,
        user: CurrentUser = Depends(get_current_user)):
    from integrations.prosper import get_adapter, ProsperError
    target_org_id = (body.org_id or user.org_id or "").strip()
    client_email = (body.email or user.email or "").strip().lower()
    if not target_org_id:
        target_org_id = (body.prosper_id or client_email or "").strip()
    if not target_org_id:
        raise HTTPException(422, "org_id or email is required")

    org_doc = None
    if target_org_id:
        org_doc = await col(ORGANIZATIONS).find_one(
            {"$or": [{"org_id": target_org_id}, {"prosper_id": target_org_id}]},
            {"_id": 0, "org_id": 1, "prosper_wallets": 1}
        )
    if org_doc:
        existing_wallets = list(org_doc.get("prosper_wallets") or [])
        existing_m = next((w for w in existing_wallets if w.get("modality") == body.modality), None)
        if existing_m and existing_m.get("address"):
            return {
                "prosper_id": target_org_id,
                "org_id":     target_org_id,
                "email":      client_email or target_org_id,
                "modality":   body.modality,
                "address":    existing_m["address"],
                "status":     "active",
                "reused":     True,
                "tx_hash":    existing_m.get("tx_hash"),
                "raw":        existing_m.get("raw") or {},
            }
        if len(existing_wallets) >= 2:
            raise HTTPException(400, "El usuario ya tiene ambas modalidades disponibles ('month' y 'end')")

    ptx = "cli_" + secrets.token_hex(8)
    try:
        w = await get_adapter().create_user_wallet(
            user_reference_id=target_org_id,
            prosper_tx_id=ptx,
            modality=body.modality)
    except ProsperError as e:
        raise HTTPException(502, f"CMS cashin failed: {e}")
    reused = bool((w.raw or {}).get("reused"))

    if org_doc and w.address:
        w_entry = {
            "modality":        body.modality,
            "address":         w.address,
            "prosper_user_id": str(target_org_id),
            "provisioned_at":  _iso(),
            "source":          "cms_cashin",
        }
        updated_wallets = [x for x in (org_doc.get("prosper_wallets") or []) if x.get("modality") != body.modality]
        updated_wallets.append(w_entry)
        await col(ORGANIZATIONS).update_one(
            {"org_id": org_doc["org_id"]},
            {"$set": {"prosper_wallets": updated_wallets, "updated_at": _iso()}}
        )

    await log_action(
        actor=user, action="client.staking.cms.cashin",
        resource_type="prosper_wallet", resource_id=target_org_id,
        metadata={"org_id": target_org_id, "modality": body.modality,
                   "address": w.address, "status": w.status,
                   "reused": reused, "prosper_tx_id": ptx})
    return {"prosper_id": target_org_id,
            "org_id":     target_org_id,
            "email":      client_email or target_org_id,
            "modality":   body.modality,
            "address":    w.address,
            "status":     w.status,
            "reused":     reused,
            "tx_hash":    w.tx_hash,
            "raw":        w.raw}
