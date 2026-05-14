"""RealProsperAdapter — talks to the Prosper Stellar Protocol backend.

Endpoints (per https://apidev.protocol-prosper.io/api/docs — OpenAPI 3.0):

    POST   /api/v1/auth/login                          {username, password}
                                                       → {token, createdAt, expiresAt}
    POST   /api/v1/prosper/users/new                   NewUserDto
    POST   /api/v1/prosper/users/deposit               DepositDto
    POST   /api/v1/prosper/users/transfer              TransferDto
    DELETE /api/v1/prosper/users/retire                DepositDto   ← "withdraw"
    POST   /api/v1/prosper/tokens/mint                 MintDto
    POST   /api/v1/prosper/funds                       CreateFundDto
    GET    /api/v1/prosper/assets
    GET    /api/v1/prosper/users/{prosperId}/balances
    GET    /api/v1/prosper/users/{prosperId}/transactions

All Prosper endpoints require ``Authorization: Bearer <jwt>``. Tokens last
~3h; we cache them in-process + transparently re-login on 401.

Idempotency: replays with the same `prosperTxId` return the same result
(server guarantee). We never regenerate `prosperTxId` on retry.
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

DEV_BASE  = "https://apidev.protocol-prosper.io"
PROD_BASE = "https://api.protocol-prosper.io"  # placeholder — confirm at switch-time


def _base() -> str:
    return (os.environ.get("PROSPER_API_BASE") or DEV_BASE).rstrip("/")


def _user() -> str: return os.environ.get("PROSPER_API_USER", "")
def _pass() -> str: return os.environ.get("PROSPER_API_PASS", "")


# Refresh the JWT this many seconds before its real expiry, to absorb clock
# skew + a slow request that might be in-flight when the token expires.
_JWT_EARLY_REFRESH_SECONDS = 60


class RealProsperAdapter(ProsperAdapter):
    """Real HTTP adapter. JWT auto-refresh on 401 + soft TTL."""

    def __init__(self, mode: str):
        self.mode = mode
        self._jwt: Optional[str] = None
        self._jwt_expires_at: float = 0.0   # unix seconds
        if not _user() or not _pass():
            raise ProsperError(
                "PROSPER_API_USER / PROSPER_API_PASS missing — set them or "
                "switch PROSPER_MODE=mock")
        logger.info("RealProsperAdapter ready (mode=%s, base=%s, user=%s)",
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
                f"Prosper login failed: {r.status_code} {r.text[:200]}")
        try:
            body = r.json()
        except ValueError as e:
            raise ProsperError("Prosper login returned non-JSON") from e

        # The current API returns `{token, createdAt, expiresAt}`.
        token = body.get("token") or body.get("accessToken") or body.get("jwt")
        if not token:
            raise ProsperError(f"Login OK but no token in response: {body}")
        self._jwt = token
        self._jwt_expires_at = _parse_expiry(body.get("expiresAt"))
        return token

    async def _ensure_jwt(self) -> str:
        if (self._jwt
                and (self._jwt_expires_at - _JWT_EARLY_REFRESH_SECONDS)
                    > time.time()):
            return self._jwt
        return await self._login()

    # ---------------------------------------------------------------------
    # Low-level request
    # ---------------------------------------------------------------------
    async def _request(self, method: str, path: str,
                        json_body: dict | None = None,
                        _retry: bool = False) -> dict:
        jwt = await self._ensure_jwt()
        url = f"{_base()}{path}"
        headers = {"Authorization": f"Bearer {jwt}",
                    "Content-Type":  "application/json",
                    "Accept":        "application/json",
                    "User-Agent":    "prosper-backend/0.2"}
        async with httpx.AsyncClient(timeout=30.0) as cx:
            try:
                r = await cx.request(method, url, headers=headers,
                                       json=json_body)
            except httpx.HTTPError as e:
                raise ProsperError(f"Network error: {e}") from e

        if r.status_code == 401 and not _retry:
            # JWT might have been rotated / revoked server-side. Re-login once.
            self._jwt = None
            self._jwt_expires_at = 0.0
            return await self._request(method, path, json_body, _retry=True)

        if r.status_code >= 400:
            preview = r.text[:300].replace("\n", " ")
            logger.warning("Prosper %s %s → %s · %s",
                            method, path, r.status_code, preview)
            raise ProsperError(f"Prosper {r.status_code} on {path}: {preview}")
        if not r.text:
            return {}
        try:
            return r.json()
        except ValueError as e:
            raise ProsperError(
                f"Prosper returned non-JSON for {path}: {r.text[:200]!r}") from e

    # ---------------------------------------------------------------------
    # Users
    # ---------------------------------------------------------------------
    async def create_user_wallet(self, *, user_reference_id,
                                   prosper_tx_id) -> WalletResp:
        d = await self._request("POST", "/api/v1/prosper/users/new", {
            "userReferenceId": user_reference_id,
            "prosperTxId":     prosper_tx_id,
        })
        return WalletResp(
            address=d.get("address") or d.get("walletAddress") or "",
            tx_hash=d.get("txHash") or d.get("transactionHash") or "",
            ledger=str(d.get("ledger") or ""),
            status=d.get("status") or "",
            raw=d,
        )

    async def deposit_tokens(self, *, user_reference_id, amount,
                              prosper_tx_id) -> TokenOpResp:
        d = await self._request("POST", "/api/v1/prosper/users/deposit", {
            "userReferenceId": user_reference_id,
            "amount":          str(amount),
            "prosperTxId":     prosper_tx_id,
        })
        return _token_op(d)

    async def withdraw_tokens(self, *, user_reference_id, amount,
                                prosper_tx_id) -> TokenOpResp:
        # Per OpenAPI the withdrawal is exposed as `DELETE /users/retire`
        # with the same `DepositDto` body shape (Json body on DELETE is
        # legal per RFC 7231; the API accepts it).
        d = await self._request("DELETE", "/api/v1/prosper/users/retire", {
            "userReferenceId": user_reference_id,
            "amount":          str(amount),
            "prosperTxId":     prosper_tx_id,
        })
        return _token_op(d)

    async def transfer_tokens(self, *, amount, from_user_id, to_user_id,
                                prosper_tx_id, metadata=None) -> TokenOpResp:
        d = await self._request("POST", "/api/v1/prosper/users/transfer", {
            "amount":      str(amount),
            "fromUserId":  from_user_id,
            "toUserId":    to_user_id,
            "prosperTxId": prosper_tx_id,
            "metadata":    metadata or {},
        })
        return _token_op(d)

    async def get_user_balances(self, user_id: str) -> BalancesResp:
        d = await self._request(
            "GET", f"/api/v1/prosper/users/{user_id}/balances")
        return BalancesResp(
            address=d.get("address") or "",
            balance_prosper=str(d.get("balanceProsper") or d.get("PUSD") or "0"),
            balance_xlm=str(d.get("balanceXLM") or d.get("XLM") or "0"),
            raw=d,
        )

    async def get_user_transactions(self, user_id: str) -> dict:
        return await self._request(
            "GET", f"/api/v1/prosper/users/{user_id}/transactions")

    async def get_assets(self) -> dict:
        return await self._request("GET", "/api/v1/prosper/assets")

    # ---------------------------------------------------------------------
    # Health check — login + soft probe.
    # ---------------------------------------------------------------------
    async def health_check(self) -> dict:
        try:
            await self._login()
            return {"ok": True, "mode": self.mode,
                     "jwt_expires_at": self._jwt_expires_at}
        except ProsperError as e:
            return {"ok": False, "mode": self.mode, "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _token_op(d: dict) -> TokenOpResp:
    return TokenOpResp(
        tx_hash=d.get("txHash") or d.get("transactionHash") or "",
        ledger=str(d.get("ledger") or ""),
        status=d.get("status") or "",
        address=d.get("address"),
        balance=d.get("balance"),
        raw=d,
    )


def _parse_expiry(value) -> float:
    """Convert `expiresAt` from Prosper login into unix seconds. Falls back
    to "now + 2 hours" if the field is malformed (keep us safe-ish)."""
    if not value:
        return time.time() + 2 * 3600
    try:
        from datetime import datetime
        iso = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(iso).timestamp()
    except Exception:
        return time.time() + 2 * 3600
