"""RealProsperAdapter — talks to Prosper Stellar via the new CMS partner API.

The Prosper CMS backend lives at ``https://cmsback.protocol-prosper.io`` and
exposes a partner-scoped namespace ``/api/v1/cms/*``:

    POST  /api/v1/auth/login            {username, password}
                                        → {token, createdAt, expiresAt}

    GET   /api/v1/cms/treasury          → {balanceUSDC, balanceXLM}
    GET   /api/v1/cms/users             → [{userId, email, address, cashin}]
    POST  /api/v1/cms/cashin            {prosperId, cashin:"end"|"month"}
                                        → {address, balanceUSDC, balanceXLM}
    GET   /api/v1/cms/staking           → [{id, hash, owner, memo,
                                            principalAmount, start,
                                            maturityPrincipal,
                                            scheduleInterest, rate,
                                            payoutAssetInterest,
                                            payoutAssetPrincipal,
                                            claimedInterest,
                                            principalRedeemed, email}]

This replaces the legacy ``/api/v1/alfred/*`` namespace. The CMS protocol is
the **native** Prosper integration surface: prosperId-driven (no email lookup),
treasury reads return a flat shape, and staking records carry per-deposit
``memo`` identifiers so a single client can hold many parallel stakings.

We keep the same `ProsperAdapter` interface so the rest of the backend
(routes/onramp_flow.py, ensure_org_prosper_wallet, etc.) works unchanged.

Mapping of methods → CMS endpoints:
  create_user_wallet(ref, tx) →  POST /cms/cashin
                                 (cashin upserts the wallet under prosperId)
  get_user_balances(id)       →  GET  /cms/users  + Horizon lookup
  get_user_transactions(id)   →  GET  /cms/staking  (filtered by owner address)
  get_treasury()              →  GET  /cms/treasury
  deposit / withdraw / transfer →  not exposed in partner namespace; staking
                                   is initiated by the user transferring funds
                                   directly to their wallet (with the per-
                                   staking memo). These methods raise so the
                                   UI surfaces "feature pending" rather than
                                   silently moving money.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx

from .adapter import (
    BalancesResp, ProsperAdapter, ProsperError, TokenOpResp, WalletResp,
)

logger = logging.getLogger("prosper.stellar")

# CMS base — mainnet only. Per product decision (Feb 2026) we go straight
# to mainnet; no separate test env is provided by Prosper.
CMS_BASE = "https://cmsback.protocol-prosper.io"


def _base() -> str:
    return (os.environ.get("PROSPER_API_BASE") or CMS_BASE).rstrip("/")


def _user() -> str: return os.environ.get("PROSPER_API_USER", "")
def _pass() -> str: return os.environ.get("PROSPER_API_PASS", "")


# Refresh the JWT this many seconds before its real expiry, to absorb clock
# skew + a slow request that might be in-flight when the token expires.
_JWT_EARLY_REFRESH_SECONDS = 60


class RealProsperAdapter(ProsperAdapter):
    """Real HTTP adapter — CMS namespace (`/api/v1/cms/*`)."""

    def __init__(self, mode: str):
        self.mode = mode
        self._jwt: Optional[str] = None
        self._jwt_expires_at: float = 0.0   # unix seconds
        if not _user() or not _pass():
            raise ProsperError(
                "PROSPER_API_USER / PROSPER_API_PASS missing — set them or "
                "switch PROSPER_MODE=mock")
        logger.info("RealProsperAdapter ready (CMS, mode=%s, base=%s, user=%s)",
                     mode, _base(), _user())

    # ---------------------------------------------------------------------
    # Auth — POST /api/v1/auth/login
    # ---------------------------------------------------------------------
    async def _login(self) -> str:
        async with httpx.AsyncClient(timeout=15.0) as cx:
            r = await cx.post(f"{_base()}/api/v1/auth/login",
                               json={"username": _user(), "password": _pass()})
        if r.status_code >= 400:
            raise ProsperError(
                f"Prosper CMS login failed: {r.status_code} {r.text[:200]}")
        try:
            body = r.json()
        except ValueError as e:
            raise ProsperError("Prosper CMS login returned non-JSON") from e
        token = body.get("token") or body.get("accessToken") or body.get("jwt")
        if not token:
            raise ProsperError(f"CMS login OK but no token in response: {body}")
        self._jwt = token
        self._jwt_expires_at = _parse_expiry(body.get("expiresAt"))
        return token

    async def _ensure_jwt(self) -> str:
        if (self._jwt
                and (self._jwt_expires_at - _JWT_EARLY_REFRESH_SECONDS)
                    > time.time()):
            return self._jwt
        return await self._login()

    async def _request(self, method: str, path: str,
                        json_body: dict | None = None,
                        _retry: bool = False,
                        ok_404: bool = False) -> dict | list:
        jwt = await self._ensure_jwt()
        url = f"{_base()}{path}"
        headers = {"Authorization": f"Bearer {jwt}",
                    "Content-Type":  "application/json",
                    "Accept":        "application/json",
                    "User-Agent":    "prosper-backend/0.4-cms"}
        async with httpx.AsyncClient(timeout=30.0) as cx:
            try:
                r = await cx.request(method, url, headers=headers,
                                       json=json_body)
            except httpx.HTTPError as e:
                raise ProsperError(f"Network error: {e}") from e
        if r.status_code == 401 and not _retry:
            self._jwt = None
            self._jwt_expires_at = 0.0
            return await self._request(method, path, json_body,
                                          _retry=True, ok_404=ok_404)
        if r.status_code == 404 and ok_404:
            return {}
        if r.status_code >= 400:
            preview = r.text[:300].replace("\n", " ")
            logger.warning("Prosper CMS %s %s → %s · %s",
                            method, path, r.status_code, preview)
            raise ProsperError(
                f"Prosper CMS {r.status_code} on {path}: {preview}")
        if not r.text:
            return {}
        try:
            return r.json()
        except ValueError as e:
            raise ProsperError(
                f"Prosper CMS returned non-JSON for {path}: "
                f"{r.text[:200]!r}") from e

    # ---------------------------------------------------------------------
    # Wallet provisioning — POST /cms/cashin {prosperId, cashin}
    # ---------------------------------------------------------------------
    async def _find_user_by_prosper_id(self, prosper_id: str) -> dict | None:
        """List /cms/users and find the record matching prosperId.

        Live response shape (Feb 2026) groups users by integration:
            {"prosper": [{"prosperId", "address", "cashin"}, …],
             "alfred":  [{"userId", "email", "address", "cashin"}, …]}
        Doc response shape (README v2.0) is a flat array:
            [{"userId", "email", "address", "cashin"}, …]
        We accept both and search across all entries.
        """
        users = await self._request("GET", "/api/v1/cms/users")
        if isinstance(users, dict):
            buckets = []
            for k in ("prosper", "alfred", "items"):
                v = users.get(k)
                if isinstance(v, list):
                    buckets.extend(v)
            candidates = buckets
        elif isinstance(users, list):
            candidates = users
        else:
            return None

        pid = str(prosper_id).strip()
        for u in candidates:
            if not u:
                continue
            if str(u.get("prosperId", "")).strip() == pid:
                return u
            if str(u.get("userId", "")).strip() == pid:
                return u
            if "@" in pid and (u.get("email") or "").lower() == pid.lower():
                return u
        return None

    async def list_cms_users(self) -> dict:
        """Raw passthrough of `GET /cms/users` for the admin Staking module.

        Returns the raw partner response plus a flattened `items` list
        (the live API groups rows by integration; the doc shape is flat).
        Formatting is the frontend's job.
        """
        users = await self._request("GET", "/api/v1/cms/users")
        items: list[dict] = []
        if isinstance(users, dict):
            for k in ("prosper", "alfred", "items"):
                v = users.get(k)
                if isinstance(v, list):
                    items.extend({**u, "integration": k} for u in v if u)
        elif isinstance(users, list):
            items = [u for u in users if u]
        return {"items": items, "raw": users}

    async def create_cms_user(self, *, email: str) -> dict:
        """CMS v2.0 (Jun 2026) removed `POST /cliente/users`.

        Registration is now implicit: `POST /cms/cashin {prosperId, cashin}`
        creates the account AND assigns the wallet in one step.
        """
        raise ProsperError(
            "El CMS v2.0 eliminó el alta de cuenta separada — usá una "
            "solicitud de cash-in (crea la cuenta y asigna la wallet en "
            "un solo paso)")

    # ---------------------------------------------------------------------
    # Wallet provisioning — POST /cms/cashin {prosperId, cashin}
    # ---------------------------------------------------------------------
    async def _find_user_by_prosper_id_and_modality(
            self, prosper_id: str, modality: str) -> dict | None:
        """List /cms/users and find the entry matching prosperId × modality.

        Critical for the CMS protocol: the partner creates ONE wallet per
        (prosperId, cashin) pair, so a single prosperId can have multiple
        rows in /cms/users — one per modality. We MUST filter by both
        `prosperId` and `cashin` to get the correct address.

        Background (Feb 2026, partner-side bug): `POST /cms/cashin`
        returns the WRONG address in its response when a second modality
        is requested for an already-registered prosperId — it echoes the
        first wallet ever created instead of the new one. The truth lives
        in `GET /cms/users`, so this lookup is the source of truth.
        """
        users = await self._request("GET", "/api/v1/cms/users")
        if isinstance(users, dict):
            buckets = []
            for k in ("prosper", "alfred", "items"):
                v = users.get(k)
                if isinstance(v, list):
                    buckets.extend(v)
            candidates = buckets
        elif isinstance(users, list):
            candidates = users
        else:
            return None

        pid = str(prosper_id).strip()
        mod = (modality or "").strip().lower()
        for u in candidates:
            if not u:
                continue
            row_pid = str(u.get("prosperId") or u.get("userId") or "").strip()
            row_email = str(u.get("email") or "").strip().lower()
            row_mod = str(u.get("cashin") or "").strip().lower()
            if row_mod == mod and (row_pid == pid
                                     or (row_email and row_email == pid.lower())):
                return u
        return None

    async def create_user_wallet(self, *, user_reference_id,
                                   prosper_tx_id,
                                   modality: str = "end") -> WalletResp:
        """Provision a Stellar wallet for (prosperId, modality).

        `user_reference_id` IS the prosperId.

        The CMS protocol assigns ONE wallet per (prosperId, cashin) pair.
        Source of truth for the address is `GET /cms/users` filtered by
        both fields — NOT the body returned by `POST /cms/cashin` (which
        is partner-side bugged and echoes the first wallet ever created
        for the prosperId).
        """
        prosper_id = str(user_reference_id).strip()
        modality   = (modality or "end").lower()
        if modality not in ("end", "month"):
            modality = "end"

        # 1) Idempotent: if a user row for THIS (prosperId, modality)
        # exists, return early. This is the fast path — we never refetch
        # the address from a body that we know is unreliable.
        existing = await self._find_user_by_prosper_id_and_modality(
            prosper_id, modality)
        if existing and existing.get("address"):
            logger.info("Prosper CMS wallet already provisioned: "
                         "prosperId=%s modality=%s → %s",
                         prosper_id, modality, existing["address"])
            return WalletResp(
                address=existing["address"], tx_hash="", ledger="",
                status="ready",
                raw={"reused": True, "user": existing,
                      "cashin_modality": modality,
                      "source": "cms_users"})

        # 2) Provision via cashin endpoint (CMS v2.0: registration is
        #    implicit — `POST /cms/cashin {prosperId, cashin}` creates the
        #    account AND the wallet in one step; CashinDto per Swagger).
        cashin_resp = await self._request("POST", "/api/v1/cms/cashin",
                                            {"prosperId": prosper_id,
                                             "cashin":    modality})

        # 3) Re-read /cms/users — partner POST body may echo the wrong
        #    address (the one of the FIRST modality ever created for this
        #    prosperId). The list endpoint is the authoritative source.
        u = await self._find_user_by_prosper_id_and_modality(
            prosper_id, modality)
        addr = (u or {}).get("address") or ""

        # 4) Final fallback — accept the POST body's address only if the
        #    list lookup failed completely (extremely rare; would mean
        #    the partner created the row but returned it inconsistently).
        if not addr and isinstance(cashin_resp, dict):
            addr = (cashin_resp.get("address")
                      or (cashin_resp.get("wallet") or {}).get("address")
                      or "")

        return WalletResp(
            address=addr, tx_hash="", ledger="",
            status="ready" if addr else "pending",
            raw={"cashin":         cashin_resp,
                  "prosper_id":     prosper_id,
                  "cashin_modality": modality,
                  "source":          "cms_users" if u else "cashin_body",
                  "users_row":       u})

    # ---------------------------------------------------------------------
    # Balances — read Stellar Horizon directly for the org's wallet
    # ---------------------------------------------------------------------
    async def get_user_balances(self, user_id: str) -> BalancesResp:
        prosper_id = str(user_id).strip()
        u = await self._find_user_by_prosper_id(prosper_id)
        if not u or not u.get("address"):
            return BalancesResp(address="", balance_prosper="0",
                                balance_xlm="0",
                                raw={"reason": "wallet_not_provisioned"})

        addr = u["address"]
        horizon = os.environ.get("STELLAR_HORIZON_URL",
                                   "https://horizon.stellar.org").rstrip("/")
        async with httpx.AsyncClient(timeout=12.0) as cx:
            r = await cx.get(f"{horizon}/accounts/{addr}")
        if r.status_code == 404:
            return BalancesResp(address=addr, balance_prosper="0",
                                balance_xlm="0",
                                raw={"reason": "horizon_404", "address": addr})
        if r.status_code >= 400:
            raise ProsperError(f"Horizon {r.status_code}: {r.text[:200]}")

        data = r.json() or {}
        usdcp_code = os.environ.get("PROSPER_ASSET_CODE", "USDCP")
        usdcp_issuer = os.environ.get("PROSPER_ISSUER_PUBLIC_KEY", "")
        xlm = "0"
        prosper_bal = "0"
        for b in data.get("balances", []):
            if b.get("asset_type") == "native":
                xlm = b.get("balance", "0")
            elif (b.get("asset_code") == usdcp_code
                    and (not usdcp_issuer or b.get("asset_issuer") == usdcp_issuer)):
                prosper_bal = b.get("balance", "0")
        return BalancesResp(
            address=addr, balance_prosper=prosper_bal, balance_xlm=xlm,
            raw={"horizon": data, "cms_user": u})

    # ---------------------------------------------------------------------
    # Treasury — GET /api/v1/cms/treasury
    # Live shape (observed Feb 2026):
    #   {"treasury": {"address": "G…", "balanceUSDC": "12.25",
    #                  "balanceARSA": "100"}}
    # Doc shape (README v2.0):
    #   {"balanceUSDC": <int>, "balanceXLM": <int>}
    # We accept both and surface a stable normalized dict upstream.
    # ---------------------------------------------------------------------
    async def get_treasury(self) -> dict:
        resp = await self._request("GET", "/api/v1/cms/treasury")
        # Unwrap if nested under `treasury`.
        body = resp.get("treasury") if isinstance(resp, dict) \
                and isinstance(resp.get("treasury"), dict) else resp
        if isinstance(body, dict):
            return {
                "address":     body.get("address"),
                "balanceUSDC": body.get("balanceUSDC")
                                or body.get("balance_usdc") or 0,
                "balanceARSA": body.get("balanceARSA")
                                or body.get("balanceARSa")
                                or body.get("balance_arsa") or 0,
                "balanceXLM":  body.get("balanceXLM")
                                or body.get("balance_xlm") or 0,
                "raw":         resp,
            }
        return {"balanceUSDC": 0, "balanceARSA": 0, "balanceXLM": 0,
                 "raw": resp}

    # ---------------------------------------------------------------------
    # Staking — GET /api/v1/cms/staking (new in CMS, replaces /alfred/staking)
    #
    # Live shape (observed Feb 2026):
    #   [{"id", "email", "wallet", "hashDeposito", "hashStaking",
    #     "memoStaking", "principalAmount", "start", "maturityPrincipal",
    #     "scheduleInterest": [...], "porcentajeAnual", "payoutAssetPrincipal",
    #     "payoutAssetInterest", "tokenInteres", "claimedInterest",
    #     "interesesAcumulados", "proyectado", "contractoId",
    #     "principalRedeemed", "proximaFechaMonto", "interesCada24Horas",
    #     "createdAt", "updatedAt", "deletedAt"}, …]
    #
    # Doc shape (README v2.0) uses Anglo names: {hash, owner, memo, rate, …}.
    # We surface a normalized dict with BOTH families of keys so callers can
    # use whichever they prefer; .raw keeps the source verbatim.
    # ---------------------------------------------------------------------
    @staticmethod
    def _normalize_staking(r: dict) -> dict:
        if not isinstance(r, dict):
            return {}
        n = dict(r)  # preserve raw fields
        n.setdefault("hash",    r.get("hashStaking") or r.get("hash"))
        n.setdefault("owner",   r.get("wallet")      or r.get("owner"))
        n.setdefault("memo",    r.get("memoStaking") or r.get("memo"))
        n.setdefault("rate",    r.get("porcentajeAnual") or r.get("rate"))
        n.setdefault("payoutAssetInterest",
                       r.get("payoutAssetInterest")
                       or r.get("tokenInteres"))
        n.setdefault("created_at", r.get("createdAt") or r.get("created_at"))
        return n

    async def get_staking_records(self, *, owner_address: str | None = None,
                                    email: str | None = None) -> list[dict]:
        """Return staking records (normalized) for either an address or email.

        The CMS endpoint returns the full list (per partner). We filter
        client-side because the API does not expose query params yet.
        """
        rows = await self._request("GET", "/api/v1/cms/staking", ok_404=True)
        if not isinstance(rows, list):
            return []
        out = [self._normalize_staking(r) for r in rows]
        if owner_address:
            owner_lc = owner_address.strip().lower()
            out = [r for r in out
                    if (r.get("owner") or "").lower() == owner_lc]
        if email:
            email_lc = email.strip().lower()
            out = [r for r in out
                    if (r.get("email") or "").lower() == email_lc]
        return out

    # ---------------------------------------------------------------------
    # Methods not (yet) exposed in the partner namespace.
    # In the CMS protocol, staking starts when the user transfers funds to
    # their assigned wallet with a per-staking memo. Direct mint/withdraw
    # is not exposed to partners.
    # ---------------------------------------------------------------------
    async def deposit_tokens(self, *, user_reference_id, amount,
                              prosper_tx_id) -> TokenOpResp:
        raise ProsperError(
            "deposit_tokens is not exposed in the CMS partner namespace — "
            "stakings are created when the client transfers funds to its "
            "assigned wallet using its per-staking memo")

    async def withdraw_tokens(self, *, user_reference_id, amount,
                                prosper_tx_id) -> TokenOpResp:
        raise ProsperError(
            "withdraw_tokens is not exposed in the CMS partner namespace — "
            "principal/yield is settled at maturity by the protocol")

    async def transfer_tokens(self, *, amount, from_user_id, to_user_id,
                                prosper_tx_id, metadata=None) -> TokenOpResp:
        raise ProsperError(
            "transfer_tokens is not exposed in the CMS partner namespace")

    async def get_user_transactions(self, user_id: str) -> dict:
        """Return the staking records owned by this prosperId.

        Resolves the user's Stellar address via /cms/users first, then
        filters /cms/staking by `owner`. This matches the "memo per
        staking" model: one client → one wallet → many stakings, each
        identified by its unique on-chain memo.
        """
        prosper_id = str(user_id).strip()
        u = await self._find_user_by_prosper_id(prosper_id)
        addr = (u or {}).get("address", "")
        records = await self.get_staking_records(owner_address=addr) if addr else []
        return {"staking": records, "address": addr}

    async def get_assets(self) -> dict:
        treasury = await self.get_treasury()
        return {
            "asset_code": os.environ.get("PROSPER_ASSET_CODE", "USDCP"),
            "issuer":     os.environ.get("PROSPER_ISSUER_PUBLIC_KEY", ""),
            "distribution_contract": os.environ.get(
                "PROSPER_DISTRIBUTION_PUBLIC_KEY", ""),
            "treasury": {
                "balanceUSDC": treasury.get("balanceUSDC"),
                "balanceXLM":  treasury.get("balanceXLM"),
            },
        }

    # ---------------------------------------------------------------------
    # Health check — login + treasury probe.
    # ---------------------------------------------------------------------
    async def health_check(self) -> dict:
        try:
            await self._login()
            t = await self.get_treasury()
            return {"ok": True, "mode": self.mode,
                     "jwt_expires_at": self._jwt_expires_at,
                     "treasury_address": t.get("address"),
                     "treasury_usdc": t.get("balanceUSDC"),
                     "treasury_arsa": t.get("balanceARSA"),
                     "treasury_xlm":  t.get("balanceXLM")}
        except ProsperError as e:
            return {"ok": False, "mode": self.mode, "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_expiry(value) -> float:
    if not value:
        return time.time() + 2 * 3600
    try:
        from datetime import datetime
        iso = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(iso).timestamp()
    except Exception:
        return time.time() + 2 * 3600
