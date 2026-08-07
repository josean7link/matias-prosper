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
from roles import Role, is_internal
from routes.phase22_admin_yield import stakings_payload

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
    """List stakings scoped to the client's email.

    Internal roles (super_admin / admin / finance / compliance_officer)
    that happen to hit this route see everything — but the primary
    entry point for internals is the admin one.
    """
    if _is_internal(user):
        return await stakings_payload(scope=scope, asset=asset,
                                        status=status)
    email = _current_email(user)
    return await stakings_payload(scope=scope, asset=asset,
                                    status=status, email=email,
                                    org_id=user.org_id)


@router.get("/cms/wallets")
async def client_list_cms_wallets(
        user: CurrentUser = Depends(get_current_user)):
    """Return the client's own CMS wallets (matched by email).

    Internal roles see the full CMS wallet list; clients only see rows
    whose `email` (or `prosperId` if the CMS stored the email there)
    matches their session email.
    """
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
    if not _is_internal(user):
        email = _current_email(user)
        items = [it for it in items
                 if (str(it.get("email") or "").lower() == email
                     or str(it.get("prosperId") or "").lower() == email)]
    return {"items":      items,
             "raw":        data.get("raw"),
             "total":      len(items),
             "mode":       os.environ.get("PROSPER_MODE", "mock"),
             "fetched_at": _iso()}


# NOTE: `POST /client/staking/cms/users` and
# `POST /client/staking/cms/cashin` were removed intentionally (Aug 2026).
# The only supported way for a client to obtain a new Prosper wallet is
# the investment flow (`POST /client/invest/onchain`), which lazily
# provisions the wallet through `ensure_org_prosper_wallet` using the
# client_admin's email as the prosperId. Internal roles still create
# CMS accounts + cashins via the admin routes.
