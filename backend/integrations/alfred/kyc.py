"""Sprint 12.6 — Alfred Hybrid KYB + KYC adapter.

Alfred's KYC/KYB service lives on a SEPARATE host from the Penny payments
API (per https://alfredpay.readme.io/docs/sending-money-with-alfred):

    Payments (Penny):  ALFRED_API_BASE_SANDBOX
    KYC services:      ALFRED_KYC_BASE_SANDBOX
                       (default https://api-dev-services.alfredpay.app/api/v1)

The Alfred KYC flow boils down to:

    POST /third-party-service/my-info       -> {data.url}
        The URL embeds a token used as `initial_transaction` in subsequent
        calls AND as the public iframe URL for the hosted KYC widget.

    POST /third-party-service/login-sof-kyc -> {data.token}
        Bearer token authorising document uploads + status polling.

    (Hosted iframe collects ID + selfie + docs; on completion Alfred POSTs
     a webhook to ALFRED_WEBHOOK_SECRET-signed callback we configured at
     `/v1/admin/ops/sync-alfred-webhook`.)

This module exposes a two-mode adapter (real or mock) and persists the
resulting ``alfred_customer_id`` so that subsequent `/onramp` calls can
pass it as required by Penny (otherwise 422).
"""
from __future__ import annotations

import logging
import os
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import httpx

from .adapter import AlfredError

logger = logging.getLogger("prosper.alfred.kyc")


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
@dataclass
class KycCustomerResponse:
    customer_id: str
    iframe_url: str
    init_transaction: str   # passed as initial_transaction to /login-sof-kyc
    bearer_token: Optional[str]
    status: str             # pending | in_review | approved | rejected
    mode: Literal["mock", "sandbox", "production"]
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _kyc_mode() -> str:
    """`ALFRED_KYC_MODE` overrides `ALFRED_MODE` for the KYC subsystem so we
    can run Penny against sandbox while still using the mock KYC widget
    (handy while finalising the production Alfred KYC contract)."""
    explicit = (os.environ.get("ALFRED_KYC_MODE") or "").strip().lower()
    if explicit in ("mock", "sandbox", "production"):
        return explicit
    return (os.environ.get("ALFRED_MODE") or "mock").lower()


def _kyc_base(mode: str) -> str:
    if mode == "production":
        return os.environ.get(
            "ALFRED_KYC_BASE_PRODUCTION",
            "https://api-services.alfredpay.app/api/v1")
    return os.environ.get(
        "ALFRED_KYC_BASE_SANDBOX",
        "https://api-dev-services.alfredpay.app/api/v1")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------
class AlfredKycAdapter(ABC):
    mode: Literal["mock", "sandbox", "production"] = "mock"

    @abstractmethod
    async def create_kyb_customer(self, *, org_id: str,
                                   business: dict[str, Any],
                                   redirect_uri: str,
                                   ) -> KycCustomerResponse: ...

    @abstractmethod
    async def create_kyc_customer(self, *, user_id: str,
                                   personal: dict[str, Any],
                                   redirect_uri: str,
                                   ) -> KycCustomerResponse: ...


# ---------------------------------------------------------------------------
# Mock — used when no real KYC creds available or for fast E2E tests
# ---------------------------------------------------------------------------
class MockAlfredKycAdapter(AlfredKycAdapter):
    mode: Literal["mock", "sandbox", "production"] = "mock"

    async def create_kyb_customer(self, *, org_id, business, redirect_uri):
        cid = "alfc_kyb_" + secrets.token_hex(6)
        base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or os.environ.get(
            "APP_URL", "http://localhost:3000")
        iframe_url = f"{base}/api/v1/alfred/mock-kyc/{cid}?kind=kyb&redirect={redirect_uri}"
        return KycCustomerResponse(
            customer_id=cid, iframe_url=iframe_url,
            init_transaction=cid, bearer_token=None,
            status="pending", mode="mock",
            raw={"business": business, "org_id": org_id})

    async def create_kyc_customer(self, *, user_id, personal, redirect_uri):
        cid = "alfc_kyc_" + secrets.token_hex(6)
        base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or os.environ.get(
            "APP_URL", "http://localhost:3000")
        iframe_url = f"{base}/api/v1/alfred/mock-kyc/{cid}?kind=kyc&redirect={redirect_uri}"
        return KycCustomerResponse(
            customer_id=cid, iframe_url=iframe_url,
            init_transaction=cid, bearer_token=None,
            status="pending", mode="mock",
            raw={"personal": personal, "user_id": user_id})


# ---------------------------------------------------------------------------
# Real — talks to Alfred KYC service
# ---------------------------------------------------------------------------
class RealAlfredKycAdapter(AlfredKycAdapter):
    """Backed by Alfred's `api-dev-services.alfredpay.app` / `api-services` host."""

    def __init__(self, mode: Literal["sandbox", "production"]):
        self.mode = mode
        self._api_key = os.environ.get("ALFRED_API_KEY", "")
        self._api_secret = os.environ.get("ALFRED_API_SECRET", "")
        self._base = _kyc_base(mode)
        if not self._api_key or not self._api_secret:
            raise AlfredError(
                "ALFRED_API_KEY / ALFRED_API_SECRET empty — set ALFRED_KYC_MODE=mock")
        logger.info("RealAlfredKycAdapter ready (mode=%s, base=%s)", mode, self._base)

    def _headers(self) -> dict[str, str]:
        return {
            "api-key":      self._api_key,
            "api-secret":   self._api_secret,
            "Content-Type": "application/json",
            "Accept":       "application/json",
            "User-Agent":   "prosper-backend/0.2 (+https://prosper.foundation)",
        }

    async def _request(self, method: str, path: str,
                         json_body: dict | None = None) -> dict:
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=30.0) as cx:
            try:
                r = await cx.request(method, url, json=json_body,
                                       headers=self._headers())
            except httpx.HTTPError as e:
                logger.exception("alfred-kyc http error %s %s", method, path)
                raise AlfredError(f"Network error talking to Alfred KYC: {e}") from e
        if r.status_code >= 400:
            preview = r.text[:500].replace("\n", " ")
            logger.warning("Alfred-KYC %s %s -> %s · %s",
                            method, path, r.status_code, preview)
            raise AlfredError(f"Alfred KYC {r.status_code} on {path}: {preview}")
        try:
            return r.json() if r.text else {}
        except ValueError as e:
            raise AlfredError(
                f"Alfred KYC returned non-JSON for {path}: {r.text[:200]!r}") from e

    async def _init_my_info(self, *, type_: str, currency: str, user_handle: str,
                              amount: float = 0) -> dict:
        body = {
            "type":     type_,
            "balance":  amount,
            "currency": currency,
            "user":     user_handle,
            "chain":    os.environ.get("ALFRED_DEFAULT_CHAIN", "stellar"),
        }
        return await self._request("POST", "/third-party-service/my-info",
                                     json_body=body)

    async def _login_sof_kyc(self, *, init_transaction: str,
                                personal: dict[str, Any]) -> dict:
        body = {
            "initial_transaction": init_transaction,
            "phonenumber": personal.get("phone") or "+0000000000",
            "email":       personal.get("email") or "",
            "firstname":   personal.get("first_name") or "",
            "lastname":    personal.get("last_name") or "",
            "address":     personal.get("address") or "",
            "country":     personal.get("country") or "ARG",
            "city":        personal.get("city") or "",
            "zipcode":     personal.get("zip") or 0,
            "birthday":    personal.get("dob") or "",
        }
        return await self._request("POST", "/third-party-service/login-sof-kyc",
                                     json_body=body)

    async def _common(self, *, kind: Literal["kyb", "kyc"],
                        identifier: str,
                        personal: dict[str, Any],
                        redirect_uri: str) -> KycCustomerResponse:
        # 1) Init transaction — returns a URL whose last segment IS the token
        #    AND the public iframe URL the user navigates to.
        amount = float(personal.get("expected_amount") or 0)
        my_info = await self._init_my_info(
            type_=kind.upper(), currency="USDC",
            user_handle=f"@{identifier}",
            amount=amount)
        url = (((my_info or {}).get("data") or {}).get("url") or "").strip()
        if not url:
            raise AlfredError(
                "Alfred /my-info returned no URL — cannot start KYC")
        init_tx = url.rstrip("/").split("/")[-1]

        # 2) Exchange for a bearer token. Some Alfred environments accept
        #    this call with partial personal data — failures here are non-fatal
        #    because the user still completes the rest inside the iframe.
        bearer: Optional[str] = None
        try:
            login = await self._login_sof_kyc(
                init_transaction=init_tx, personal=personal)
            bearer = (((login or {}).get("data") or {}).get("token")
                      or login.get("token"))
        except AlfredError as e:
            logger.info("alfred-kyc login-sof-kyc skipped (%s) — iframe will collect data", e)

        return KycCustomerResponse(
            customer_id=init_tx,
            iframe_url=url,
            init_transaction=init_tx,
            bearer_token=bearer,
            status="pending",
            mode=self.mode,
            raw={"my_info": my_info, "kind": kind, "redirect_uri": redirect_uri})

    async def create_kyb_customer(self, *, org_id, business, redirect_uri):
        merged = {**(business or {}), **(business.get("primary_contact") or {})}
        return await self._common(
            kind="kyb", identifier=f"org-{org_id[-8:]}",
            personal=merged, redirect_uri=redirect_uri)

    async def create_kyc_customer(self, *, user_id, personal, redirect_uri):
        return await self._common(
            kind="kyc", identifier=f"usr-{user_id[-8:]}",
            personal=personal or {}, redirect_uri=redirect_uri)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_singleton: AlfredKycAdapter | None = None


def get_kyc_adapter() -> AlfredKycAdapter:
    global _singleton
    if _singleton is not None:
        return _singleton
    mode = _kyc_mode()
    if mode == "mock":
        _singleton = MockAlfredKycAdapter()
    else:
        try:
            _singleton = RealAlfredKycAdapter(mode=mode)  # type: ignore[arg-type]
        except AlfredError as e:
            logger.warning("Falling back to MockAlfredKycAdapter: %s", e)
            _singleton = MockAlfredKycAdapter()
    return _singleton


def current_kyc_mode() -> str:
    return get_kyc_adapter().mode


def reset_kyc_adapter() -> None:
    """Test/admin helper to drop the cached adapter (e.g. after env flip)."""
    global _singleton
    _singleton = None
