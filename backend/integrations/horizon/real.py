"""RealHorizonAdapter — pulls `/payments` from Stellar Horizon.

Single global cursor design (per the Deposit Engine plan):

    GET {STELLAR_HORIZON_URL}/payments
        ?cursor=<paging_token>
        &limit=<n>
        &order=asc
        &include_failed=false

Horizon's pagination is monotonic — `paging_token` is a 64-bit value
that always grows. We persist it in Mongo (collection
`deposit_watcher_cursors`) so reboots resume from the same place.

This adapter is **read-only**. It never signs or submits Stellar
transactions. The Deposit Engine is strictly a detector.

NOTE: Horizon is blocked from preview/CI. This adapter is only
exercised when `HORIZON_MODE=real` AND the container has network egress
to Horizon. Tests use the MockHorizonAdapter instead.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from .adapter import (AccountBalance, HorizonAdapter, HorizonError,
                       Payment, PaymentsPage)
from .mock import _normalize  # re-use the same normalization

logger = logging.getLogger("prosper.horizon.real")


def _horizon_base() -> str:
    return (os.environ.get("STELLAR_HORIZON_URL")
              or "https://horizon.stellar.org").rstrip("/")


class RealHorizonAdapter(HorizonAdapter):
    """HTTP adapter over Stellar Horizon's `/payments` endpoint."""

    mode = "real"

    def __init__(self) -> None:
        base = _horizon_base()
        if not base.startswith(("http://", "https://")):
            raise HorizonError(
                f"STELLAR_HORIZON_URL must be a full http(s) URL, got {base!r}")
        logger.info("RealHorizonAdapter ready (base=%s)", base)

    async def fetch_payments(self, *, cursor: str, limit: int = 200
                              ) -> PaymentsPage:
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit or 200), 200)),
            "order": "asc",
            "include_failed": "false",
        }
        if cursor:
            params["cursor"] = cursor
        url = f"{_horizon_base()}/payments"
        try:
            async with httpx.AsyncClient(timeout=20.0) as cx:
                r = await cx.get(url, params=params,
                                    headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise HorizonError(f"network error against Horizon: {e}") from e
        if r.status_code >= 400:
            preview = r.text[:300].replace("\n", " ")
            raise HorizonError(
                f"Horizon {r.status_code} on /payments: {preview}")
        try:
            body = r.json()
        except ValueError as e:
            raise HorizonError(
                f"Horizon /payments returned non-JSON: {r.text[:200]!r}") from e

        records = (body.get("_embedded") or {}).get("records") or []
        payments: list[Payment] = []
        for raw in records:
            op_type = raw.get("type")
            # Horizon emits all op types under `/payments`. We only consume
            # value-bearing ones; everything else (e.g. account_merge) is
            # ignored at the source so the watcher never sees them.
            if op_type not in ("payment",
                                  "path_payment_strict_send",
                                  "path_payment_strict_receive"):
                continue
            try:
                payments.append(_normalize(raw))
            except HorizonError as e:
                logger.warning("RealHorizonAdapter: skipping malformed "
                                  "record (%s): %r", e, raw.get("id"))
                continue
        next_cursor = payments[-1].paging_token if payments else cursor
        return PaymentsPage(payments=payments, next_cursor=next_cursor)

    async def health_check(self) -> dict:
        url = f"{_horizon_base()}/"
        try:
            async with httpx.AsyncClient(timeout=10.0) as cx:
                r = await cx.get(url, headers={"Accept": "application/json"})
            ok = r.status_code < 400
            body = r.json() if ok else {"status_code": r.status_code}
            return {"ok":   ok,
                     "mode": "real",
                     "base": _horizon_base(),
                     "horizon_version": body.get("horizon_version"),
                     "core_version":    body.get("core_version"),
                     "history_latest_ledger": body.get(
                         "history_latest_ledger")}
        except httpx.HTTPError as e:
            return {"ok": False, "mode": "real", "base": _horizon_base(),
                     "error": str(e)[:200]}

    async def get_account_balances(self, *, address: str
                                    ) -> list[AccountBalance]:
        if not address:
            return []
        url = f"{_horizon_base()}/accounts/{address}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as cx:
                r = await cx.get(url,
                                    headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            logger.warning("Horizon /accounts network error for %s: %s",
                              address, e)
            return []
        if r.status_code == 404:
            # Unfunded / never-activated account — treat as zero, not an
            # error. The UI simply shows 0.
            return []
        if r.status_code >= 400:
            logger.warning("Horizon /accounts %s → HTTP %s: %s",
                              address, r.status_code, r.text[:200])
            return []
        try:
            body = r.json()
        except ValueError:
            return []
        out: list[AccountBalance] = []
        for b in body.get("balances") or []:
            t = (b.get("asset_type") or "").lower()
            if t == "native":
                out.append(AccountBalance(asset_code="",
                                            asset_issuer="",
                                            balance=str(b.get("balance", "0"))))
            else:
                out.append(AccountBalance(
                    asset_code=str(b.get("asset_code") or ""),
                    asset_issuer=str(b.get("asset_issuer") or ""),
                    balance=str(b.get("balance", "0"))))
        return out
