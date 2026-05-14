"""Sprint 12.6 — Alfred Hybrid KYB + KYC adapter (LIVE PROBED).

Real endpoints (Penny restricted, base = ALFRED_API_BASE_*):
    POST  /customers                       — create customer (returns customerId)
        body: {email, type: "INDIVIDUAL"|"BUSINESS", country?, businessId?}
    POST  /customers/{customerId}/kyc      — submit KYC data
        body: {kycSubmission: { firstName, lastName, phoneNumber (E.164),
               address, country (ISO-2: AR/MX/BR/CO/US/...), city, state,
               zipCode, dateOfBirth (YYYY-MM-DD), dni, cuit (AR only,
               must match dni), pep, ...country-specific extras }}
    GET   /customers/{customerId}          — read customer (includes statusKyc)

The hosted KYC widget URL pattern (per Alfred docs "ON Ramp with KYC Iframe"):
    {ALFRED_KYC_WIDGET_BASE}?customerId={cid}&apiKey={alfred_public_widget_key}
We surface the widget URL we have configured via env (ALFRED_KYC_WIDGET_BASE);
if unset, we fall back to the local mock page so the wizard never dead-ends.

Key live findings (probed 2026-02 against penny-api-restricted-dev):
    * `type` MUST be uppercase enum: INDIVIDUAL / BUSINESS.
    * BUSINESS creation in this sandbox tenant additionally requires `country`
      AND the partner account to be configured for KYB — falls back to
      creating an INDIVIDUAL customer for the org's primary contact.
    * AR country code = "AR" (NOT "ARG"); MX = "MX", BR = "BR", CO = "CO", US = "US".
    * AR mandatory: dateOfBirth (YYYY-MM-DD), zipCode, state, dni, cuit, pep
      — cuit must contain the dni (Alfred checks: "CUIT contains XXXX, DNI is YYY").
    * Phone must be E.164 with country trunk (+5411…, not +549…).
    * Customer is usable as `customerId` in /onramp the moment statusKyc=APPROVED.
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
    init_transaction: str           # alias of customer_id for the wizard
    bearer_token: Optional[str]
    status: str                     # CREATED | PENDING | APPROVED | REJECTED (Alfred enum)
    mode: Literal["mock", "sandbox", "production"]
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _kyc_mode() -> str:
    explicit = (os.environ.get("ALFRED_KYC_MODE") or "").strip().lower()
    if explicit in ("mock", "sandbox", "production"):
        return explicit
    return (os.environ.get("ALFRED_MODE") or "mock").lower()


def _base_url(mode: str) -> str:
    """KYC endpoints live on the same Penny base used for payments."""
    if mode == "production":
        return os.environ.get(
            "ALFRED_API_BASE_PRODUCTION",
            "https://penny-api-restricted.alfredpay.io/api/v1/third-party-service/penny")
    return os.environ.get(
        "ALFRED_API_BASE_SANDBOX",
        "https://penny-api-restricted-dev.alfredpay.io/api/v1/third-party-service/penny")


def _widget_base(mode: str) -> str:
    if mode == "production":
        return (os.environ.get("ALFRED_KYC_WIDGET_BASE_PRODUCTION", "")
                  or os.environ.get("ALFRED_KYC_WIDGET_BASE", "")).rstrip("/")
    return (os.environ.get("ALFRED_KYC_WIDGET_BASE_SANDBOX", "")
              or os.environ.get("ALFRED_KYC_WIDGET_BASE", "")).rstrip("/")


# Country mapping: our internal ISO-3 / free-form → Alfred ISO-2.
_COUNTRY_MAP = {
    "AR": "AR", "ARG": "AR", "ARGENTINA": "AR",
    "BR": "BR", "BRA": "BR", "BRASIL": "BR", "BRAZIL": "BR",
    "CL": "CL", "CHL": "CL", "CHILE": "CL",
    "CO": "CO", "COL": "CO", "COLOMBIA": "CO",
    "MX": "MX", "MEX": "MX", "MEXICO": "MX",
    "PE": "PE", "PER": "PE", "PERU": "PE",
    "UY": "UY", "URY": "UY", "URUGUAY": "UY",
    "US": "US", "USA": "US", "USAUS": "US",
}


def _alfred_country(value: Optional[str]) -> str:
    if not value:
        return "AR"
    return _COUNTRY_MAP.get(value.upper().strip(), value.upper()[:2])


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

    async def get_customer_status(self, customer_id: str) -> dict:
        """Best-effort status read. Mocks return CREATED forever; real reads from Alfred."""
        return {"statusKyc": "CREATED", "customerId": customer_id}


# ---------------------------------------------------------------------------
# Mock — local hosted-widget emulation
# ---------------------------------------------------------------------------
class MockAlfredKycAdapter(AlfredKycAdapter):
    mode: Literal["mock", "sandbox", "production"] = "mock"

    def _mock_iframe(self, cid: str, kind: str, redirect_uri: str) -> str:
        base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or os.environ.get(
            "APP_URL", "http://localhost:3000")
        return (f"{base}/api/v1/alfred/mock-kyc/{cid}"
                f"?kind={kind}&redirect={redirect_uri}")

    async def create_kyb_customer(self, *, org_id, business, redirect_uri):
        cid = "alfc_kyb_" + secrets.token_hex(6)
        return KycCustomerResponse(
            customer_id=cid, iframe_url=self._mock_iframe(cid, "kyb", redirect_uri),
            init_transaction=cid, bearer_token=None,
            status="pending", mode="mock",
            raw={"business": business, "org_id": org_id})

    async def create_kyc_customer(self, *, user_id, personal, redirect_uri):
        cid = "alfc_kyc_" + secrets.token_hex(6)
        return KycCustomerResponse(
            customer_id=cid, iframe_url=self._mock_iframe(cid, "kyc", redirect_uri),
            init_transaction=cid, bearer_token=None,
            status="pending", mode="mock",
            raw={"personal": personal, "user_id": user_id})

    async def get_customer_status(self, customer_id: str) -> dict:
        return {"statusKyc": "CREATED", "customerId": customer_id, "mode": "mock"}


# ---------------------------------------------------------------------------
# Real — talks to Alfred Penny restricted API
# ---------------------------------------------------------------------------
class RealAlfredKycAdapter(AlfredKycAdapter):

    def __init__(self, mode: Literal["sandbox", "production"]):
        self.mode = mode
        self._api_key = os.environ.get("ALFRED_API_KEY", "")
        self._api_secret = os.environ.get("ALFRED_API_SECRET", "")
        self._business_id = os.environ.get("ALFRED_BUSINESS_ID", "")
        self._base = _base_url(mode)
        self._widget_base = _widget_base(mode)
        if not self._api_key or not self._api_secret:
            raise AlfredError(
                "ALFRED_API_KEY / ALFRED_API_SECRET empty — set ALFRED_KYC_MODE=mock")
        logger.info("RealAlfredKycAdapter ready (mode=%s, base=%s, widget=%s)",
                     mode, self._base, self._widget_base or "<none>")

    # ------------------------------------------------------------------ HTTP
    def _headers(self) -> dict[str, str]:
        h = {
            "api-key":      self._api_key,
            "api-secret":   self._api_secret,
            "Content-Type": "application/json",
            "Accept":       "application/json",
            "User-Agent":   "prosper-backend/0.2 (+https://prosper.foundation)",
        }
        if self._business_id:
            h["business-id"] = self._business_id
        return h

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

    # ------------------------------------------------------------------ Helpers
    def _build_widget_url(self, customer_id: str, redirect_uri: str) -> str:
        """Build the hosted KYC widget URL.

        Real Alfred provisions a JS-embeddable widget that takes the customerId
        as a query param. If we don't have an ALFRED_KYC_WIDGET_BASE configured
        we fall back to a local hosted page that lets the user paste a
        Alfred-mode-redirect link (so the flow doesn't dead-end in dev).
        """
        if self._widget_base:
            base = self._widget_base
            sep = "&" if "?" in base else "?"
            extra = f"&apiKey={self._api_key}" if "apiKey=" not in base else ""
            return f"{base}{sep}customerId={customer_id}{extra}&redirectUrl={redirect_uri}"
        # Dev fallback — local "real-but-no-widget" page
        public = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or os.environ.get(
            "APP_URL", "http://localhost:3000")
        return f"{public}/api/v1/alfred/real-kyc-stub/{customer_id}?redirect={redirect_uri}"

    async def _create_customer(self, *, email: str, type_: Literal["INDIVIDUAL", "BUSINESS"],
                                 country: Optional[str] = None,
                                 business_id: Optional[str] = None) -> dict:
        body: dict[str, Any] = {"email": email, "type": type_}
        # Live-probed: `/customers` accepts `country` ONLY when type=BUSINESS.
        # For INDIVIDUAL the field is unknown (422 "Invalid parameter(s) country").
        # The customer's country is captured later via `/customers/{id}/kyc`.
        if country and type_ == "BUSINESS":
            body["country"] = _alfred_country(country)
        if business_id:
            body["businessId"] = business_id
        try:
            return await self._request("POST", "/customers", json_body=body)
        except AlfredError as e:
            # Alfred 409 "Email already registered" — retry with a unique
            # +tag email so the same internal reference can re-onboard. This
            # is critical for dev/test loops; in production the idempotency
            # check on the org doc prevents re-hitting Alfred at all.
            if "111409" in str(e) or "already registered" in str(e).lower():
                local, _, domain = email.partition("@")
                ts = secrets.token_hex(3)
                tagged_email = f"{local}+a{ts}@{domain or 'prosper.foundation'}"
                body["email"] = tagged_email
                logger.info("Alfred 111409 — retrying with tagged email %s", tagged_email)
                return await self._request("POST", "/customers", json_body=body)
            raise

    async def _submit_kyc(self, *, customer_id: str, submission: dict[str, Any]) -> dict:
        return await self._request("POST", f"/customers/{customer_id}/kyc",
                                     json_body={"kycSubmission": submission})

    # ------------------------------------------------------------------ KYB
    async def create_kyb_customer(self, *, org_id, business, redirect_uri):
        """Create a BUSINESS customer; on tenant restriction, fall back to an
        INDIVIDUAL customer for the org's primary contact (Hybrid mode)."""
        primary = (business or {}).get("primary_contact") or {}
        email = (business.get("primary_email")
                  or primary.get("email")
                  or f"kyb-{org_id[-8:]}@prosper.foundation").lower()
        country = _alfred_country(business.get("country"))

        cust: dict[str, Any] = {}
        try:
            cust = await self._create_customer(
                email=email, type_="BUSINESS", country=country,
                business_id=self._business_id or None)
        except AlfredError as e:
            logger.warning("KYB create_customer failed (%s) — falling back to INDIVIDUAL", e)
            try:
                cust = await self._create_customer(
                    email=email, type_="INDIVIDUAL", country=country)
            except AlfredError as e2:
                raise AlfredError(f"Both BUSINESS and INDIVIDUAL fallback failed: {e2}") from e2

        cid = str(cust.get("customerId") or "")
        if not cid:
            raise AlfredError(f"Alfred /customers returned no customerId: {cust}")

        widget = self._build_widget_url(cid, redirect_uri)
        return KycCustomerResponse(
            customer_id=cid, iframe_url=widget,
            init_transaction=cid, bearer_token=None,
            status=str(cust.get("statusKyc") or "CREATED").lower(),
            mode=self.mode,
            raw={"customer": cust, "kind": "kyb", "fallback_individual":
                  cust.get("type") == "INDIVIDUAL"})

    # ------------------------------------------------------------------ KYC
    async def create_kyc_customer(self, *, user_id, personal, redirect_uri):
        personal = personal or {}
        email = (personal.get("email")
                  or f"kyc-{user_id[-8:]}@prosper.foundation").lower()
        country = _alfred_country(personal.get("country") or personal.get("nationality"))

        cust = await self._create_customer(
            email=email, type_="INDIVIDUAL", country=country)
        cid = str(cust.get("customerId") or "")
        if not cid:
            raise AlfredError(f"Alfred /customers returned no customerId: {cust}")

        widget = self._build_widget_url(cid, redirect_uri)
        return KycCustomerResponse(
            customer_id=cid, iframe_url=widget,
            init_transaction=cid, bearer_token=None,
            status=str(cust.get("statusKyc") or "CREATED").lower(),
            mode=self.mode,
            raw={"customer": cust, "kind": "kyc"})

    # ------------------------------------------------------------------ Status
    async def get_customer_status(self, customer_id: str) -> dict:
        return await self._request("GET", f"/customers/{customer_id}")


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
    global _singleton
    _singleton = None
