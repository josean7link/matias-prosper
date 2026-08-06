"""Phase 16 — Admin backoffice for the ramp provider.

Endpoints mounted at `/api/v1/admin/ramp/*`. Restricted to backoffice roles
(super_admin, admin, compliance_admin, finance_admin, ops). Every mutation
emits an audit log entry capturing actor + before/after state.

Sections:
  A. Provider switch (global + per-org overrides) + connectivity probe
     + capabilities
  B. Accounts monitoring (list + KPIs + drill-down)
  C. Movements feed (list + CSV export)
  D. Project stats (proxy to gateway)
  E. Webhook events (db rows + andes deliveries cross-check)
"""
from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import (
    col, ORGANIZATIONS, RAMP_ACCOUNTS, RAMP_BALANCES, RAMP_FIAT_ACCOUNTS,
    RAMP_MOVEMENTS, RAMP_WALLETS, RAMP_WEBHOOK_EVENTS,
)
from ramp.chain_config import (
    ARSA_CHAINS, DEFAULT_ARSA_CHAIN, get_org_arsa_chain_config,
    resolve_arsa_chain_with_source,
)
from ramp.registry import (
    RAMP_PROVIDER_CONFIG, get_registry, reset_registry,
)

logger = logging.getLogger("prosper.admin.ramp")

router = APIRouter(prefix="/admin/ramp", tags=["admin-ramp"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
_BACKOFFICE_ROLES = {"super_admin", "admin", "compliance_admin",
                      "compliance_officer", "finance_admin", "finance", "ops"}
_WRITE_ROLES      = {"super_admin", "finance_admin", "finance"}


def _require_backoffice(user: CurrentUser) -> None:
    if user.role not in _BACKOFFICE_ROLES:
        raise HTTPException(403, f"role {user.role} cannot access ramp admin")


def _require_write(user: CurrentUser) -> None:
    if user.role not in _WRITE_ROLES:
        raise HTTPException(
            403, f"role {user.role} cannot mutate provider config")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gateway_url() -> str:
    return (os.environ.get("ANDES_GATEWAY_URL")
              or "http://localhost:8090").rstrip("/")


def _gateway_token() -> str:
    return os.environ.get("GATEWAY_INTERNAL_TOKEN",
                            "dev-internal-token-change-me")


# ---------------------------------------------------------------------------
# Section A — Provider switch + connectivity probe + capabilities
# ---------------------------------------------------------------------------
class ProviderConfigRow(BaseModel):
    scope: str                # "global" or an org_id
    provider: str             # "alfred" | "andeslabs"
    mode: str                 # "mock" | "sandbox" | "real"
    enabled: bool
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None


class ProviderConfigUpdate(BaseModel):
    provider: str = Field(..., pattern="^(alfred|andeslabs)$")
    mode: str = Field(..., pattern="^(mock|sandbox|real)$")
    enabled: bool = True


class ConnectivityResult(BaseModel):
    provider: str
    enabled: bool
    reachable: bool
    authenticated: bool
    error: Optional[str] = None
    latency_ms: Optional[int] = None
    details: dict[str, Any] = Field(default_factory=dict)


@router.get("/provider-config")
async def list_provider_config(user: CurrentUser = Depends(get_current_user)):
    """Return the global row + every per-org override."""
    _require_backoffice(user)
    rows = await col(RAMP_PROVIDER_CONFIG).find(
        {}, {"_id": 0}
    ).sort("scope", 1).to_list(length=500)
    # Pull org display names for nicer rendering
    org_ids = [r["scope"] for r in rows if r.get("scope") not in (None, "global")]
    orgs = {}
    if org_ids:
        async for o in col(ORGANIZATIONS).find(
                {"org_id": {"$in": org_ids}},
                {"_id": 0, "org_id": 1, "legal_name": 1, "commercial_name": 1}):
            orgs[o["org_id"]] = (o.get("commercial_name")
                                  or o.get("legal_name") or o["org_id"])
    return {
        "rows": rows,
        "org_names": orgs,
    }


@router.put("/provider-config")
async def set_global_provider_config(body: ProviderConfigUpdate,
                                          user: CurrentUser = Depends(get_current_user)):
    return await _upsert_provider_config(
        scope="global", body=body, actor=user)


@router.put("/provider-config/{org_id}")
async def set_org_provider_config(org_id: str, body: ProviderConfigUpdate,
                                       user: CurrentUser = Depends(get_current_user)):
    # Validate the org exists so we don't strand orphan overrides
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id},
                                              {"_id": 0, "org_id": 1})
    if not org:
        raise HTTPException(404, f"org {org_id} not found")
    return await _upsert_provider_config(scope=org_id, body=body, actor=user)


@router.delete("/provider-config/{org_id}")
async def clear_org_provider_config(org_id: str,
                                         user: CurrentUser = Depends(get_current_user)):
    _require_write(user)
    if org_id == "global":
        raise HTTPException(400, "cannot delete the global config")
    prev = await col(RAMP_PROVIDER_CONFIG).find_one_and_delete(
        {"scope": org_id}, projection={"_id": 0})
    reset_registry()  # so the next resolve() re-reads the table
    await log_action(actor=user, action="admin.ramp.provider_config.delete",
                       resource_type="ramp_provider_config", resource_id=org_id,
                       metadata={"before": prev, "after": None})
    return {"ok": True, "removed": bool(prev), "before": prev}


async def _upsert_provider_config(scope: str, body: ProviderConfigUpdate,
                                       actor: CurrentUser) -> dict:
    _require_write(actor)
    prev = await col(RAMP_PROVIDER_CONFIG).find_one({"scope": scope},
                                                          {"_id": 0})
    new_doc = {
        "scope":      scope,
        "provider":   body.provider,
        "mode":       body.mode,
        "enabled":    body.enabled,
        "updated_by": actor.email or actor.user_id or "system",
        "updated_at": _now_iso(),
    }
    await col(RAMP_PROVIDER_CONFIG).update_one(
        {"scope": scope}, {"$set": new_doc}, upsert=True)
    reset_registry()  # next resolve() picks up the new value
    await log_action(actor=actor,
                       action=f"admin.ramp.provider_config.{'create' if not prev else 'update'}",
                       resource_type="ramp_provider_config",
                       resource_id=scope,
                       metadata={"scope": scope,
                                  "before": prev,
                                  "after": new_doc})
    return {"ok": True, "before": prev, "after": new_doc}


@router.get("/capabilities")
async def list_capabilities(user: CurrentUser = Depends(get_current_user)):
    """What does each provider currently support? Used by the UI to render
    the right "supports X / Y" panel under the toggle."""
    _require_backoffice(user)
    # Pull from the gateway (single source of truth for andes mode) AND
    # combine with the in-process capabilities() from each adapter.
    out: dict[str, dict] = {}
    for provider_id in ("alfred", "andeslabs"):
        for mode in ("mock", "sandbox"):
            try:
                adapter = get_registry().adapter_for(provider_id, mode)
                caps = adapter.capabilities()
                # Convert dataclass-or-pydantic to dict
                if hasattr(caps, "model_dump"):
                    cd = caps.model_dump()
                elif hasattr(caps, "__dict__"):
                    cd = {k: (v.value if hasattr(v, "value") else v)
                            for k, v in caps.__dict__.items()}
                else:
                    cd = dict(caps)
                # Stringify enums in lists
                for k, v in list(cd.items()):
                    if isinstance(v, list):
                        cd[k] = [(x.value if hasattr(x, "value") else x)
                                   for x in v]
                out.setdefault(provider_id, cd)
                break
            except Exception as e:  # noqa: BLE001
                logger.debug("capabilities for %s/%s failed: %s",
                                provider_id, mode, e)
    # Also include the gateway's authoritative capabilities so the UI can show
    # what's enabled even if no FastAPI adapter exists yet.
    try:
        async with httpx.AsyncClient(timeout=5.0) as cx:
            r = await cx.get(f"{_gateway_url()}/capabilities",
                                headers={"X-Internal-Token": _gateway_token()})
        if r.status_code < 400:
            gw = r.json()
            out["_gateway"] = gw
    except httpx.HTTPError as e:
        logger.warning("gateway capabilities unreachable: %s", e)
    return out


@router.get("/connectivity", response_model=list[ConnectivityResult])
async def connectivity_probe(user: CurrentUser = Depends(get_current_user)):
    """Run a light probe against each known provider. Returns the semaphore
    quadruplet (enabled / reachable / authenticated / error) per provider."""
    _require_backoffice(user)
    results: list[ConnectivityResult] = []

    # ---- Andes via gateway ------------------------------------------------
    async def probe_andes() -> ConnectivityResult:
        t0 = datetime.now(timezone.utc)
        try:
            async with httpx.AsyncClient(timeout=8.0) as cx:
                health = await cx.get(f"{_gateway_url()}/health")
                if health.status_code >= 400:
                    return ConnectivityResult(
                        provider="andeslabs", enabled=True, reachable=False,
                        authenticated=False,
                        error=f"gateway /health → HTTP {health.status_code}")
                hjson = health.json()

                stats = await cx.get(
                    f"{_gateway_url()}/project/stats",
                    headers={"X-Internal-Token": _gateway_token()},
                    timeout=8.0)
        except httpx.HTTPError as e:
            return ConnectivityResult(
                provider="andeslabs", enabled=True, reachable=False,
                authenticated=False, error=f"unreachable: {e}")
        latency = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
        if stats.status_code == 401:
            return ConnectivityResult(
                provider="andeslabs", enabled=True, reachable=True,
                authenticated=False, latency_ms=latency,
                error="gateway rejected internal token",
                details={"health": hjson})
        if stats.status_code >= 400:
            return ConnectivityResult(
                provider="andeslabs", enabled=True, reachable=True,
                authenticated=False, latency_ms=latency,
                error=f"/project/stats → HTTP {stats.status_code}",
                details={"health": hjson})
        return ConnectivityResult(
            provider="andeslabs", enabled=True, reachable=True,
            authenticated=True, latency_ms=latency,
            details={"health": hjson, "stats_mode": stats.json().get("mode")})

    # ---- Alfred via in-process adapter ------------------------------------
    async def probe_alfred() -> ConnectivityResult:
        t0 = datetime.now(timezone.utc)
        try:
            from integrations.alfred.factory import get_adapter as get_alfred
            adapter = get_alfred()
            h = await adapter.health_check()
            latency = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            ok = bool((h or {}).get("ok") or (h or {}).get("status") == "ok"
                        or (h or {}).get("healthy"))
            return ConnectivityResult(
                provider="alfred", enabled=True, reachable=True,
                authenticated=ok, latency_ms=latency,
                error=None if ok else (h or {}).get("error") or "alfred reported not-ok",
                details=h or {})
        except Exception as e:  # noqa: BLE001
            return ConnectivityResult(
                provider="alfred", enabled=True, reachable=False,
                authenticated=False, error=str(e)[:200])

    import asyncio
    andes_r, alfred_r = await asyncio.gather(probe_andes(), probe_alfred())
    results = [andes_r, alfred_r]
    return results


# ---------------------------------------------------------------------------
# Section B — Accounts monitoring
# ---------------------------------------------------------------------------
class AccountKpis(BaseModel):
    total_arsa_under_management: str
    accounts_active: int
    accounts_pending_kyc: int
    accounts_error: int


@router.get("/accounts/kpis", response_model=AccountKpis)
async def accounts_kpis(user: CurrentUser = Depends(get_current_user)):
    _require_backoffice(user)
    active = await col(RAMP_ACCOUNTS).count_documents(
        {"onboarding_status": "approved"})
    pending = await col(RAMP_ACCOUNTS).count_documents(
        {"onboarding_status": {"$in": ["pending_approval", "kyc_pending_andes"]}})
    err = await col(RAMP_ACCOUNTS).count_documents(
        {"onboarding_status": {"$in": ["error", "rejected"]}})
    cur = col(RAMP_BALANCES).aggregate([
        {"$match": {"asset": "arsa"}},
        {"$group": {"_id": None,
                      "total": {"$sum": {"$toDouble": "$balance"}}}}
    ])
    rows = await cur.to_list(length=1)
    total = float(rows[0]["total"]) if rows else 0.0
    return AccountKpis(
        total_arsa_under_management=f"{total:.2f}",
        accounts_active=active,
        accounts_pending_kyc=pending,
        accounts_error=err)


@router.get("/accounts")
async def list_accounts(status: Optional[str] = Query(None),
                          has_cvu: Optional[bool] = Query(None),
                          q: Optional[str] = Query(None,
                              description="search by end_customer_id or CVU"),
                          limit: int = Query(100, ge=1, le=500),
                          user: CurrentUser = Depends(get_current_user)):
    _require_backoffice(user)
    flt: dict[str, Any] = {}
    if status:
        flt["onboarding_status"] = status
    if has_cvu is True:
        flt["cvu"] = {"$ne": None, "$exists": True}
    elif has_cvu is False:
        flt["$or"] = [{"cvu": None}, {"cvu": {"$exists": False}}]
    if q:
        flt["$or"] = [
            {"end_customer_id": {"$regex": q, "$options": "i"}},
            {"cvu":             {"$regex": q}},
            {"provider_user_id": {"$regex": q, "$options": "i"}},
        ]
    cur = col(RAMP_ACCOUNTS).find(flt, {"_id": 0}
        ).sort("updated_at", -1).limit(limit)
    rows = await cur.to_list(length=limit)

    # Hydrate ARSa balance per account
    ids = [r["id"] for r in rows]
    bal_map: dict[str, str] = {}
    if ids:
        async for b in col(RAMP_BALANCES).find(
                {"ramp_account_id": {"$in": ids}, "asset": "arsa"},
                {"_id": 0, "ramp_account_id": 1, "balance": 1}):
            bal_map[b["ramp_account_id"]] = b["balance"]
    for r in rows:
        r["arsa_balance"] = bal_map.get(r["id"], "0")
    return {"items": rows, "total": len(rows)}


@router.get("/accounts/{end_customer_id}/detail")
async def account_detail(end_customer_id: str,
                            org_id: Optional[str] = Query(None),
                            user: CurrentUser = Depends(get_current_user)):
    """Drill-down: wallets + balances + last movements + fiat account."""
    _require_backoffice(user)
    flt = {"end_customer_id": end_customer_id}
    if org_id: flt["org_id"] = org_id
    acc = await col(RAMP_ACCOUNTS).find_one(flt, {"_id": 0})
    if not acc:
        raise HTTPException(404, "account not found")
    wallets = await col(RAMP_WALLETS).find(
        {"ramp_account_id": acc["id"]}, {"_id": 0}).to_list(length=20)
    balances = await col(RAMP_BALANCES).find(
        {"ramp_account_id": acc["id"]}, {"_id": 0}).to_list(length=20)
    fiat = await col(RAMP_FIAT_ACCOUNTS).find_one(
        {"ramp_account_id": acc["id"]}, {"_id": 0})
    moves = await col(RAMP_MOVEMENTS).find(
        {"ramp_account_id": acc["id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(20).to_list(length=20)
    return {"account": acc, "wallets": wallets, "balances": balances,
              "fiat_account": fiat, "recent_movements": moves}


# ---------------------------------------------------------------------------
# Section C — Movements feed + CSV
# ---------------------------------------------------------------------------
def _build_movement_filter(kind: Optional[str], status: Optional[str],
                              org_id: Optional[str],
                              date_from: Optional[str],
                              date_to: Optional[str],
                              q: Optional[str]) -> dict:
    flt: dict[str, Any] = {}
    if kind:   flt["kind"]   = kind
    if status: flt["status"] = status
    if org_id: flt["org_id"] = org_id
    if date_from or date_to:
        flt["created_at"] = {}
        if date_from: flt["created_at"]["$gte"] = date_from
        if date_to:   flt["created_at"]["$lte"] = date_to
    if q:
        flt["$or"] = [
            {"external_id":     {"$regex": q, "$options": "i"}},
            {"destination_cvu": {"$regex": q}},
            {"destination_name":{"$regex": q, "$options": "i"}},
            {"prosper_tx_id":   {"$regex": q, "$options": "i"}},
        ]
    return flt


@router.get("/movements")
async def list_movements(
        kind: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        org_id: Optional[str] = Query(None),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=500),
        user: CurrentUser = Depends(get_current_user)):
    _require_backoffice(user)
    flt = _build_movement_filter(kind, status, org_id, date_from, date_to, q)
    cur = col(RAMP_MOVEMENTS).find(flt, {"_id": 0}
        ).sort("created_at", -1).limit(limit)
    rows = await cur.to_list(length=limit)
    # Mark "stale Pending" — Pending|TransferPending older than 30 min so the
    # UI can highlight reconciliation candidates.
    threshold = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    for r in rows:
        is_pending = r.get("status") in ("Pending", "TransferPending")
        r["is_stale"] = bool(is_pending and (r.get("created_at") or "") < threshold)
    return {"items": rows, "total": len(rows)}


@router.get("/movements.csv")
async def export_movements_csv(
        kind: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        org_id: Optional[str] = Query(None),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        limit: int = Query(5000, ge=1, le=20000),
        user: CurrentUser = Depends(get_current_user)):
    _require_backoffice(user)
    flt = _build_movement_filter(kind, status, org_id, date_from, date_to, q)
    cur = col(RAMP_MOVEMENTS).find(flt, {"_id": 0}
        ).sort("created_at", -1).limit(limit)
    rows = await cur.to_list(length=limit)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["created_at", "kind", "asset", "chain", "amount", "status",
                "destination_cvu", "destination_alias", "destination_name",
                "external_id", "prosper_tx_id", "org_id",
                "provider", "fail_reason", "settled_at"])
    for r in rows:
        w.writerow([r.get("created_at"), r.get("kind"), r.get("asset"),
                    r.get("chain"), r.get("amount"), r.get("status"),
                    r.get("destination_cvu"), r.get("destination_alias"),
                    r.get("destination_name"), r.get("external_id"),
                    r.get("prosper_tx_id"), r.get("org_id"),
                    r.get("provider"), r.get("fail_reason"),
                    r.get("settled_at")])
    await log_action(actor=user, action="admin.ramp.movements.export_csv",
                       resource_type="ramp_movements", resource_id="*",
                       metadata={"filter": flt, "rows": len(rows)})
    buf.seek(0)
    fname = f"ramp-movements-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------------------------------------------------------------------------
# Section D — Project stats (proxy to gateway)
# ---------------------------------------------------------------------------
@router.get("/stats")
async def project_stats(user: CurrentUser = Depends(get_current_user)):
    _require_backoffice(user)
    try:
        async with httpx.AsyncClient(timeout=8.0) as cx:
            r = await cx.get(f"{_gateway_url()}/project/stats",
                                headers={"X-Internal-Token": _gateway_token()})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"gateway unreachable: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"stats failed: {r.text[:200]}")
    return r.json()


@router.get("/stats/timeseries")
async def project_stats_timeseries(
        window: str = Query("30d"),
        bucket: str = Query("1d"),
        user: CurrentUser = Depends(get_current_user)):
    _require_backoffice(user)
    try:
        async with httpx.AsyncClient(timeout=8.0) as cx:
            r = await cx.get(
                f"{_gateway_url()}/project/stats-timeseries",
                headers={"X-Internal-Token": _gateway_token()},
                params={"window": window, "bucket": bucket})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"gateway unreachable: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code,
                            f"timeseries failed: {r.text[:200]}")
    return r.json()


# ---------------------------------------------------------------------------
# Section E — Webhook events (db + andes deliveries cross-check)
# ---------------------------------------------------------------------------
@router.get("/webhooks")
async def list_webhook_events(
        event_type: Optional[str] = Query(None),
        processed: Optional[bool] = Query(None),
        signature_valid: Optional[bool] = Query(None),
        limit: int = Query(100, ge=1, le=500),
        user: CurrentUser = Depends(get_current_user)):
    _require_backoffice(user)
    flt: dict[str, Any] = {}
    if event_type:        flt["event_type"] = event_type
    if processed is not None:        flt["processed"] = processed
    if signature_valid is not None:  flt["signature_valid"] = signature_valid
    cur = col(RAMP_WEBHOOK_EVENTS).find(flt, {"_id": 0}
        ).sort("received_at", -1).limit(limit)
    rows = await cur.to_list(length=limit)
    return {"items": rows, "total": len(rows)}


@router.get("/webhooks/deliveries")
async def webhook_deliveries(limit: int = Query(100, ge=1, le=500),
                                user: CurrentUser = Depends(get_current_user)):
    """Cross-check: what Andes thinks it delivered vs what FastAPI received."""
    _require_backoffice(user)
    try:
        async with httpx.AsyncClient(timeout=8.0) as cx:
            r = await cx.get(
                f"{_gateway_url()}/webhooks/deliveries",
                headers={"X-Internal-Token": _gateway_token()},
                params={"limit": limit})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"gateway unreachable: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code,
                            f"deliveries failed: {r.text[:200]}")
    body = r.json()
    received = {row["delivery_id"]: row async for row
                  in col(RAMP_WEBHOOK_EVENTS).find(
                      {}, {"_id": 0, "delivery_id": 1, "processed": 1,
                            "event_type": 1, "received_at": 1})}
    items = body.get("items") or []
    diff = []
    for it in items:
        dlv = it.get("deliveryId") or it.get("delivery_id")
        diff.append({**it,
                      "received": dlv in received,
                      "processed": received.get(dlv, {}).get("processed", False)})
    return {"items": diff, "mode": body.get("mode"),
              "note": body.get("note"),
              "received_count": len(received),
              "delivered_count": len(items)}


# ---------------------------------------------------------------------------
# Section F — ARSa chain selection (Phase 17)
#
# A wallet in Andes is keyed by (asset, chain). ARSa-stellar and ARSa-base
# are distinct tokens on distinct chains with separate balances. The chain
# selector decides where NEW wallets get minted; it never moves or
# converts existing balances. Two scopes are supported:
#
#   * Global default (scope == "global") — applies to every org without an
#     override. Surfaced + edited from /admin/integraciones/rampa.
#   * Per-account override (`ramp_accounts.arsa_chain_override`) — single
#     account opts out of the org default.
# ---------------------------------------------------------------------------
class ArsaChainConfigOut(BaseModel):
    default: str                       # "stellar" | "base"
    allowed: list[str]                 # subset of ARSA_CHAINS
    source: str                        # "org_override"|"global"|"env_default"


class ArsaChainConfigUpdate(BaseModel):
    default: str = Field(..., pattern="^(stellar|base)$")
    allowed: Optional[list[str]] = Field(
        default=None,
        description="Subset of ['stellar','base'] this org is allowed to use",
    )


@router.get("/arsa-chain", response_model=ArsaChainConfigOut)
async def get_arsa_chain_config(
        org_id: Optional[str] = Query(
            None,
            description="If provided, returns the org's effective config "
                        "(falls back to global)."),
        user: CurrentUser = Depends(get_current_user)):
    """Read the active ARSa chain config (global or org-scoped)."""
    _require_backoffice(user)
    if not org_id:
        # Global-only view (called from the rampa integrations page)
        glob = await col(RAMP_PROVIDER_CONFIG).find_one(
            {"scope": "global"},
            {"_id": 0, "default_arsa_chain": 1,
              "allowed_arsa_chains": 1}) or {}
        import os
        default = (glob.get("default_arsa_chain")
                     or (os.environ.get("ANDES_DEFAULT_CHAIN")
                         or DEFAULT_ARSA_CHAIN).lower())
        if default not in ARSA_CHAINS:
            default = DEFAULT_ARSA_CHAIN
        return ArsaChainConfigOut(
            default=default,
            allowed=glob.get("allowed_arsa_chains") or ARSA_CHAINS,
            source=("global" if glob.get("default_arsa_chain")
                       else "env_default"))
    cfg = await get_org_arsa_chain_config(org_id)
    return ArsaChainConfigOut(default=cfg["default"],
                                 allowed=cfg["allowed"],
                                 source=cfg["source"])


@router.put("/arsa-chain", response_model=ArsaChainConfigOut)
async def set_global_arsa_chain(body: ArsaChainConfigUpdate,
                                     user: CurrentUser = Depends(get_current_user)):
    """Set the global default ARSa chain. Affects only NEW wallets."""
    _require_write(user)
    if body.default not in ARSA_CHAINS:
        raise HTTPException(400, f"default must be one of {ARSA_CHAINS}")
    allowed = body.allowed or ARSA_CHAINS
    bad = [c for c in allowed if c not in ARSA_CHAINS]
    if bad:
        raise HTTPException(400, f"unsupported chains: {bad}")

    prev = await col(RAMP_PROVIDER_CONFIG).find_one({"scope": "global"},
                                                          {"_id": 0})
    update = {
        "default_arsa_chain":  body.default,
        "allowed_arsa_chains": allowed,
        "updated_by":          user.email or user.user_id or "system",
        "updated_at":          _now_iso(),
    }
    await col(RAMP_PROVIDER_CONFIG).update_one(
        {"scope": "global"},
        {"$set": update,
          "$setOnInsert": {"scope": "global",
                            "provider": "andeslabs", "mode": "real",
                            "enabled": True}},
        upsert=True)
    reset_registry()
    await log_action(actor=user,
                       action="admin.ramp.arsa_chain.set_global",
                       resource_type="ramp_provider_config",
                       resource_id="global",
                       metadata={"before": {
                            "default": (prev or {}).get("default_arsa_chain"),
                            "allowed": (prev or {}).get("allowed_arsa_chains"),
                       }, "after": {"default": body.default,
                                      "allowed": allowed}})
    return ArsaChainConfigOut(default=body.default, allowed=allowed,
                                 source="global")


class ArsaChainOverrideOut(BaseModel):
    end_customer_id: str
    effective_chain: str               # the chain that will be used
    source: str                        # "account_override"|"org_override"|
                                       # "global"|"env_default"
    override: Optional[str] = None     # the stored override (may be null)
    has_wallet_on_other_chain: bool = False
    wallet_chain: Optional[str] = None


class ArsaChainOverrideUpdate(BaseModel):
    override: Optional[str] = Field(
        None, pattern="^(stellar|base)$",
        description="Null/missing → clear the override and use org default.")


@router.get("/accounts/{end_customer_id}/arsa-chain",
              response_model=ArsaChainOverrideOut)
async def get_account_arsa_chain(end_customer_id: str,
                                       org_id: Optional[str] = Query(None),
                                       user: CurrentUser =
                                            Depends(get_current_user)):
    _require_backoffice(user)
    flt = {"end_customer_id": end_customer_id}
    if org_id: flt["org_id"] = org_id
    acc = await col(RAMP_ACCOUNTS).find_one(
        flt, {"_id": 0, "org_id": 1, "arsa_chain_override": 1, "id": 1})
    if not acc:
        raise HTTPException(404, "ramp account not found")
    eff = await resolve_arsa_chain_with_source(
        acc["org_id"], end_customer_id)
    wal = await col(RAMP_WALLETS).find_one(
        {"ramp_account_id": acc["id"], "asset": "arsa"},
        {"_id": 0, "chain": 1})
    wal_chain = (wal or {}).get("chain")
    return ArsaChainOverrideOut(
        end_customer_id=end_customer_id,
        effective_chain=eff["chain"],
        source=eff["source"],
        override=acc.get("arsa_chain_override"),
        has_wallet_on_other_chain=bool(wal_chain
                                            and wal_chain != eff["chain"]),
        wallet_chain=wal_chain)


@router.put("/accounts/{end_customer_id}/arsa-chain",
              response_model=ArsaChainOverrideOut)
async def set_account_arsa_chain(end_customer_id: str,
                                       body: ArsaChainOverrideUpdate,
                                       org_id: Optional[str] = Query(None),
                                       user: CurrentUser =
                                            Depends(get_current_user)):
    _require_write(user)
    flt = {"end_customer_id": end_customer_id}
    if org_id: flt["org_id"] = org_id
    acc = await col(RAMP_ACCOUNTS).find_one(
        flt, {"_id": 0, "org_id": 1, "arsa_chain_override": 1, "id": 1})
    if not acc:
        raise HTTPException(404, "ramp account not found")

    new_override = body.override   # may be None to clear
    if new_override and new_override not in ARSA_CHAINS:
        raise HTTPException(400, f"unsupported chain: {new_override}")

    prev_override = acc.get("arsa_chain_override")
    await col(RAMP_ACCOUNTS).update_one(
        {"id": acc["id"]},
        {"$set": {"arsa_chain_override": new_override,
                    "updated_at": _now_iso()}})

    await log_action(actor=user,
                       action="admin.ramp.arsa_chain.set_account",
                       resource_type="ramp_account",
                       resource_id=acc["id"],
                       metadata={"org_id": acc["org_id"],
                                  "end_customer_id": end_customer_id,
                                  "before": prev_override,
                                  "after":  new_override})

    eff = await resolve_arsa_chain_with_source(acc["org_id"],
                                                    end_customer_id)
    wal = await col(RAMP_WALLETS).find_one(
        {"ramp_account_id": acc["id"], "asset": "arsa"},
        {"_id": 0, "chain": 1})
    wal_chain = (wal or {}).get("chain")
    return ArsaChainOverrideOut(
        end_customer_id=end_customer_id,
        effective_chain=eff["chain"],
        source=eff["source"],
        override=new_override,
        has_wallet_on_other_chain=bool(wal_chain
                                            and wal_chain != eff["chain"]),
        wallet_chain=wal_chain)

# ---------------------------------------------------------------------------
# Section G — Phase 15.2 — Stuck movements + manual mark-failed
#
# Behaviour: movements in `Pending` / `TransferPending` past a threshold are
# NOT auto-transitioned. Backoffice operators see them, can re-sync against
# the gateway/Andes, and (only) then mark them Failed manually with a reason.
# Marking Failed releases the (frozen) ARSa caps and audit-logs the actor.
# ---------------------------------------------------------------------------
_STUCK_STATUSES = ("Pending", "TransferPending", "Processing")


class StuckMovementOut(BaseModel):
    id: str
    org_id: Optional[str] = None
    kind: str
    status: str
    asset: Optional[str] = None
    chain: Optional[str] = None
    amount: Optional[str] = None
    country: Optional[str] = None
    end_customer_id: Optional[str] = None
    external_id: Optional[str] = None
    prosper_tx_id: Optional[str] = None
    occurred_at: Optional[str] = None
    created_at: Optional[str] = None
    age_hours: float


class MarkFailedIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500,
                         description="Operator-provided reason. Required.")
    refund_balance: bool = Field(
        True,
        description="Whether to refund the pre-debited ARSa balance (default true).")


@router.get("/movements/stuck", response_model=list[StuckMovementOut])
async def list_stuck_movements(
        threshold_hours: float = Query(24.0, ge=0.0,
            description="Movements older than this and still in Pending/"
                          "TransferPending/Processing are returned."),
        limit: int = Query(200, le=500),
        kind: Optional[str] = Query(
            None, pattern="^(withdrawal|transfer|intl_offramp|deposit)$"),
        org_id_q: Optional[str] = Query(None, alias="org_id"),
        user: CurrentUser = Depends(get_current_user)):
    _require_backoffice(user)
    cutoff = (datetime.now(timezone.utc) -
                timedelta(hours=threshold_hours)).isoformat()
    flt: dict = {"status": {"$in": list(_STUCK_STATUSES)},
                  "created_at": {"$lt": cutoff}}
    if kind:    flt["kind"] = kind
    if org_id_q: flt["org_id"] = org_id_q
    rows = await col(RAMP_MOVEMENTS).find(flt, {"_id": 0}).sort(
        "created_at", 1).to_list(limit)
    items: list[StuckMovementOut] = []
    now = datetime.now(timezone.utc)
    # Index end_customer_id from ramp_accounts
    account_ids = list({r.get("ramp_account_id") for r in rows
                          if r.get("ramp_account_id")})
    accs = {} if not account_ids else {
        a["id"]: a["end_customer_id"]
        for a in await col(RAMP_ACCOUNTS).find(
            {"id": {"$in": account_ids}},
            {"_id": 0, "id": 1, "end_customer_id": 1}).to_list(len(account_ids))
    }
    for r in rows:
        try:
            created = datetime.fromisoformat(
                str(r.get("created_at") or "").replace("Z", "+00:00"))
            age_h = round((now - created).total_seconds() / 3600.0, 1)
        except Exception:
            age_h = 0.0
        items.append(StuckMovementOut(
            id=r.get("id", ""),
            org_id=r.get("org_id"),
            kind=r.get("kind", ""),
            status=r.get("status", ""),
            asset=r.get("asset"),
            chain=r.get("chain"),
            amount=r.get("amount") or r.get("from_amount"),
            country=r.get("country"),
            end_customer_id=accs.get(r.get("ramp_account_id", ""), None),
            external_id=r.get("external_id"),
            prosper_tx_id=r.get("prosper_tx_id"),
            occurred_at=r.get("occurred_at"),
            created_at=r.get("created_at"),
            age_hours=age_h))
    return items


@router.post("/movements/{movement_id}/resync")
async def resync_movement(movement_id: str,
                                user: CurrentUser = Depends(get_current_user)):
    """Optional: re-fetch the real-state from gateway before deciding.
    For withdrawals/deposits — pulls `fiat.movements`; for transfers —
    `wallets/transfers?userId=…`; for intl_offramp — `intl/offramp?userId=…`.
    Best-effort; never mutates the movement itself."""
    _require_backoffice(user)
    mv = await col(RAMP_MOVEMENTS).find_one({"id": movement_id}, {"_id": 0})
    if not mv:
        raise HTTPException(404, "movement not found")

    gateway_url = os.environ.get("ANDES_GATEWAY_URL",
                                       "http://localhost:8090").rstrip("/")
    gateway_tok = os.environ.get("GATEWAY_INTERNAL_TOKEN",
                                       "dev-internal-token-change-me")
    pu = mv.get("provider_user_id")
    kind = mv.get("kind")
    path = None
    if kind == "transfer":     path = f"/wallets/transfers?userId={pu}"
    elif kind == "intl_offramp": path = f"/intl/offramp?userId={pu}"
    elif kind in ("withdrawal", "deposit"): path = f"/fiat/movements?userId={pu}"
    if not path:
        return {"ok": False, "reason": f"resync not supported for kind={kind}"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.get(f"{gateway_url}{path}",
                                  headers={"X-Internal-Token": gateway_tok})
        gw_items = r.json() if r.status_code == 200 else []
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"gateway error: {e}"}

    # Look up matching external_id in gateway response
    ext_id = mv.get("external_id")
    matched = None
    if isinstance(gw_items, list):
        for it in gw_items:
            if (it.get("transactionId") == ext_id or it.get("id") == ext_id
                  or it.get("wallet_transaction_id") == ext_id):
                matched = it
                break
    return {"ok": True, "kind": kind, "external_id": ext_id,
              "gateway_status": (matched or {}).get("status"),
              "gateway_payload": matched}


@router.post("/movements/{movement_id}/mark-failed",
                response_model=StuckMovementOut)
async def mark_movement_failed(movement_id: str,
                                     body: MarkFailedIn,
                                     user: CurrentUser =
                                          Depends(get_current_user)):
    """Manually mark a stuck movement as Failed. ONLY finance_admin / super_admin.
    Releases the (frozen) ARSa caps for withdrawals/transfers/intl_offramps
    when `refund_balance=true` (default)."""
    _require_write(user)   # finance_admin or super_admin
    mv = await col(RAMP_MOVEMENTS).find_one({"id": movement_id}, {"_id": 0})
    if not mv:
        raise HTTPException(404, "movement not found")
    if mv.get("status") in ("Success", "Failed"):
        raise HTTPException(409,
            f"movement is already in a terminal state ({mv['status']})")

    prev_status = mv.get("status")
    set_doc: dict = {
        "status":       "Failed",
        "fail_reason":  body.reason,
        "failed_by":    user.email or user.user_id or "system",
        "failed_at":    _now_iso(),
        "updated_at":   _now_iso(),
    }
    await col(RAMP_MOVEMENTS).update_one(
        {"id": movement_id}, {"$set": set_doc})

    # Refund balance if this movement debited a wallet (withdrawal / transfer /
    # intl_offramp PYG). Deposits don't refund (we never debited).
    refunded = False
    if body.refund_balance and mv.get("kind") in ("withdrawal", "transfer",
                                                      "intl_offramp"):
        amount = float(mv.get("amount") or mv.get("from_amount") or 0)
        if amount > 0 and mv.get("ramp_account_id"):
            asset = mv.get("asset", "arsa")
            chain = mv.get("chain", "stellar")
            prev = await col(RAMP_BALANCES).find_one(
                {"ramp_account_id": mv["ramp_account_id"],
                  "asset": asset, "chain": chain},
                {"_id": 0, "balance": 1})
            new_bal = float((prev or {}).get("balance") or 0) + amount
            await col(RAMP_BALANCES).update_one(
                {"ramp_account_id": mv["ramp_account_id"],
                  "asset": asset, "chain": chain},
                {"$set": {"balance": str(new_bal), "as_of": _now_iso()}},
                upsert=True)
            refunded = True

    await log_action(actor=user, action="admin.ramp.movement.mark_failed",
                       resource_type="ramp_movement",
                       resource_id=movement_id,
                       metadata={"org_id": mv.get("org_id"),
                                  "reason": body.reason,
                                  "before_status": prev_status,
                                  "after_status": "Failed",
                                  "kind": mv.get("kind"),
                                  "refunded": refunded,
                                  "amount": mv.get("amount")
                                              or mv.get("from_amount")})

    # Re-fetch + return as StuckMovementOut
    fresh = await col(RAMP_MOVEMENTS).find_one({"id": movement_id}, {"_id": 0})
    now = datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(
            str((fresh or {}).get("created_at") or "").replace("Z", "+00:00"))
        age_h = round((now - created).total_seconds() / 3600.0, 1)
    except Exception:
        age_h = 0.0
    return StuckMovementOut(
        id=(fresh or {}).get("id", movement_id),
        org_id=(fresh or {}).get("org_id"),
        kind=(fresh or {}).get("kind", ""),
        status=(fresh or {}).get("status", "Failed"),
        asset=(fresh or {}).get("asset"),
        chain=(fresh or {}).get("chain"),
        amount=(fresh or {}).get("amount") or (fresh or {}).get("from_amount"),
        country=(fresh or {}).get("country"),
        end_customer_id=None,
        external_id=(fresh or {}).get("external_id"),
        prosper_tx_id=(fresh or {}).get("prosper_tx_id"),
        occurred_at=(fresh or {}).get("occurred_at"),
        created_at=(fresh or {}).get("created_at"),
        age_hours=age_h)

