"""RealProsperAdapter — HTTP calls against the Prosper Stellar backend.

Endpoints (per Resumen_APIs_Prosper_-_Stellar_Protocol.docx):
    POST /v1/Auth/Login                    {correo, passwd} -> {jwt}
    POST /v1/users/new                     {userReferenceId, prosperTxId}
    POST /v1/users/deposit                 {userReferenceId|Address, amount, prosperTxId}
    POST /v1/users/withdraw                {userReferenceId|Address, amount, prosperTxId}
    POST /v1/tokens/transfer               {amount, fromUserId, toUserId, prosperTxId, metadata}
    GET  /v1/users/{userId}/balances       -> {address, balanceProsper, balanceXLM}
    GET  /v1/users/{userId}/transactions
    GET  /v1/assets/                       -> {Issue, Treasure}

Idempotency: replays with same prosperTxId return the same result (backend
guarantee). We do NOT regenerate prosperTxId on retry — the caller passes it.

JWT auth: cached in-process. On 401 we re-login transparently.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

from .adapter import (
    BalancesResp, ProsperAdapter, ProsperError, TokenOpResp, WalletResp,
)

logger = logging.getLogger("prosper.stellar")

DEV_BASE  = "http://lb-backend-develop-1915190402.us-west-2.elb.amazonaws.com"
PROD_BASE = ""   # filled at switch-time


def _base() -> str:
    return (os.environ.get("PROSPER_API_BASE") or DEV_BASE).rstrip("/")


def _user() -> str: return os.environ.get("PROSPER_API_USER", "")
def _pass() -> str: return os.environ.get("PROSPER_API_PASS", "")


class RealProsperAdapter(ProsperAdapter):
    """Real HTTP adapter. JWT auto-refresh on 401."""

    def __init__(self, mode: str):
        self.mode = mode
        self._jwt: Optional[str] = None
        if not _user() or not _pass():
            raise ProsperError(
                "PROSPER_API_USER / PROSPER_API_PASS missing — set them or "
                "switch PROSPER_MODE=mock")

    async def _login(self) -> str:
        async with httpx.AsyncClient(timeout=15.0) as cx:
            r = await cx.post(f"{_base()}/v1/Auth/Login",
                               json={"correo": _user(), "passwd": _pass()})
        if r.status_code >= 400:
            raise ProsperError(f"Login failed: {r.status_code} {r.text[:200]}")
        jwt = r.json().get("jwt")
        if not jwt:
            raise ProsperError("Login OK but no JWT in response")
        self._jwt = jwt
        return jwt

    async def _request(self, method: str, path: str,
                        json_body: dict | None = None,
                        _retry: bool = False) -> dict:
        if not self._jwt:
            await self._login()
        url = f"{_base()}{path}"
        headers = {"Authorization": f"Bearer {self._jwt}",
                    "Content-Type":  "application/json"}
        async with httpx.AsyncClient(timeout=20.0) as cx:
            try:
                r = await cx.request(method, url, headers=headers, json=json_body)
            except httpx.HTTPError as e:
                raise ProsperError(f"Network error: {e}") from e
        if r.status_code == 401 and not _retry:
            self._jwt = None
            return await self._request(method, path, json_body, _retry=True)
        if r.status_code >= 400:
            raise ProsperError(f"Prosper {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError as e:
            raise ProsperError("Prosper returned non-JSON") from e

    async def create_user_wallet(self, *, user_reference_id, prosper_tx_id) -> WalletResp:
        d = await self._request("POST", "/v1/users/new", {
            "userReferenceId": user_reference_id,
            "prosperTxId":     prosper_tx_id,
        })
        return WalletResp(address=d.get("address", ""), tx_hash=d.get("txHash", ""),
                           ledger=str(d.get("ledger", "")), status=d.get("status", ""),
                           raw=d)

    async def deposit_tokens(self, *, user_reference_id, amount, prosper_tx_id) -> TokenOpResp:
        d = await self._request("POST", "/v1/users/deposit", {
            "userReferenceId": user_reference_id,
            "amount":          str(amount),
            "prosperTxId":     prosper_tx_id,
        })
        return TokenOpResp(tx_hash=d.get("txHash", ""), ledger=str(d.get("ledger", "")),
                            status=d.get("status", ""), address=d.get("address"),
                            balance=d.get("balance"), raw=d)

    async def withdraw_tokens(self, *, user_reference_id, amount, prosper_tx_id) -> TokenOpResp:
        d = await self._request("POST", "/v1/users/withdraw", {
            "userReferenceId": user_reference_id,
            "amount":          str(amount),
            "prosperTxId":     prosper_tx_id,
        })
        return TokenOpResp(tx_hash=d.get("txHash", ""), ledger=str(d.get("ledger", "")),
                            status=d.get("status", ""), address=d.get("address"),
                            balance=d.get("balance"), raw=d)

    async def transfer_tokens(self, *, amount, from_user_id, to_user_id,
                                prosper_tx_id, metadata=None) -> TokenOpResp:
        d = await self._request("POST", "/v1/tokens/transfer", {
            "amount":        str(amount),
            "fromUserId":    from_user_id,
            "toUserId":      to_user_id,
            "prosperTxId":   prosper_tx_id,
            "metadata":      metadata or {},
        })
        return TokenOpResp(tx_hash=d.get("txHash", ""), ledger=str(d.get("ledger", "")),
                            status=d.get("status", ""), raw=d)

    async def get_user_balances(self, user_id: str) -> BalancesResp:
        d = await self._request("GET", f"/v1/users/{user_id}/balances")
        return BalancesResp(address=d.get("address", ""),
                             balance_prosper=str(d.get("balanceProsper", "0")),
                             balance_xlm=str(d.get("balanceXLM", "0")), raw=d)

    async def get_user_transactions(self, user_id: str) -> dict:
        return await self._request("GET", f"/v1/users/{user_id}/transactions")

    async def get_assets(self) -> dict:
        return await self._request("GET", "/v1/assets/")
