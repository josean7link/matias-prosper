"""AiPrise KYC/KYB integration — async httpx client.

Environment is driven by AIPRISE_ENVIRONMENT ('sandbox' | 'production').

Modes:
  - LIVE: AIPRISE_KYC_TEMPLATE_ID / AIPRISE_KYB_TEMPLATE_ID configured.
          Real calls to api-sandbox.aiprise.com / api.aiprise.com.
  - SIMULATED: template IDs missing. We still return a usable hosted_url and
          verification_session_id pointing at our own /apply/simulate page so
          the end-to-end UX works locally. Marked `mode='simulated'` in the
          response and in the audit log.

Docs: https://docs.aiprise.com/docs/overview-3
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from typing import Any, Literal, Optional

import httpx

logger = logging.getLogger("prosper.aiprise")

SANDBOX_BASE_URL = "https://api-sandbox.aiprise.com/api/v1"
PROD_BASE_URL    = "https://api.aiprise.com/api/v1"


def _env() -> str:
    return os.environ.get("AIPRISE_ENVIRONMENT", "sandbox").lower()


def base_url() -> str:
    return PROD_BASE_URL if _env() == "production" else SANDBOX_BASE_URL


def api_key() -> str:
    if _env() == "production":
        return os.environ.get("AIPRISE_API_KEY_PRODUCTION", "")
    return os.environ.get("AIPRISE_API_KEY_SANDBOX", "")


def kyc_template_id() -> str:
    return os.environ.get("AIPRISE_KYC_TEMPLATE_ID", "").strip()


def kyb_template_id() -> str:
    return os.environ.get("AIPRISE_KYB_TEMPLATE_ID", "").strip()


def webhook_secret() -> str:
    return os.environ.get("AIPRISE_WEBHOOK_SECRET", "").strip()


def is_simulated(kind: Literal["kyc", "kyb"]) -> bool:
    tid = kyc_template_id() if kind == "kyc" else kyb_template_id()
    return not tid or not api_key()


def _simulate(kind: Literal["kyc", "kyb"], client_ref: str, redirect_uri: str) -> dict:
    sess_id = f"sim_{kind}_{secrets.token_hex(8)}"
    return {
        "verification_session_id": sess_id,
        "hosted_url": (
            f"/apply/simulate?session_id={sess_id}&kind={kind}"
            f"&ref={client_ref}&next={redirect_uri}"
        ),
        "mode": "simulated",
    }


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ---------------------------------------------------------------------------
# Verification creation
# ---------------------------------------------------------------------------
async def create_user_verification(*, client_reference_id: str, user_data: dict,
                                   callback_url: str, redirect_uri: str) -> dict:
    """Create a KYC verification and return hosted_url + session id."""
    if is_simulated("kyc"):
        logger.warning("[AIPRISE] KYC simulated (template_id or api_key missing)")
        return _simulate("kyc", client_reference_id, redirect_uri)

    payload = {
        "template_id":          kyc_template_id(),
        "client_reference_id":  client_reference_id,
        "callback_url":         callback_url,
        "redirect_uri":         redirect_uri,
        "user_data":            user_data,
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{base_url()}/verify/get_user_verification_url",
                         json=payload, headers=_headers())
        if r.status_code >= 400:
            logger.error("AiPrise KYC failed %s — %s", r.status_code, r.text[:400])
            raise AipriseError(r.status_code, r.text)
        data = r.json()
    return {
        "verification_session_id": data.get("verification_session_id")
                                   or data.get("session_id"),
        "hosted_url": data.get("hosted_url") or data.get("verification_url"),
        "mode": "live",
        "raw": data,
    }


async def create_business_verification(*, client_reference_id: str, business_data: dict,
                                       callback_url: str, redirect_uri: str) -> dict:
    """Create a KYB verification and return hosted_url + session id."""
    if is_simulated("kyb"):
        logger.warning("[AIPRISE] KYB simulated (template_id or api_key missing)")
        return _simulate("kyb", client_reference_id, redirect_uri)

    payload = {
        "template_id":          kyb_template_id(),
        "client_reference_id":  client_reference_id,
        "callback_url":         callback_url,
        "redirect_uri":         redirect_uri,
        "business_data":        business_data,
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{base_url()}/verify/get_business_verification_url",
                         json=payload, headers=_headers())
        if r.status_code >= 400:
            logger.error("AiPrise KYB failed %s — %s", r.status_code, r.text[:400])
            raise AipriseError(r.status_code, r.text)
        data = r.json()
    return {
        "verification_session_id": data.get("verification_session_id")
                                   or data.get("session_id"),
        "hosted_url": data.get("hosted_url") or data.get("verification_url"),
        "mode": "live",
        "raw": data,
    }


async def get_user_verification_result(verification_session_id: str) -> Optional[dict]:
    if verification_session_id.startswith("sim_"):
        return None
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            f"{base_url()}/verify/get_user_verification_result/{verification_session_id}",
            headers=_headers())
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise AipriseError(r.status_code, r.text)
        return r.json()


async def get_business_verification_result(verification_session_id: str) -> Optional[dict]:
    if verification_session_id.startswith("sim_"):
        return None
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            f"{base_url()}/verify/get_business_verification_result/{verification_session_id}",
            headers=_headers())
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise AipriseError(r.status_code, r.text)
        return r.json()


# ---------------------------------------------------------------------------
# Webhook signature verification (HMAC-SHA256 over raw body)
# ---------------------------------------------------------------------------
def verify_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    secret = webhook_secret()
    # In simulated mode (no secret configured) we accept any signature so the
    # dev simulator can drive the flow. In live mode the secret MUST be set.
    if not secret:
        return True
    if not signature_header:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    # AiPrise sends the hash hex-encoded; accept both raw and 'sha256=' prefix.
    given = signature_header.split("=", 1)[1] if "=" in signature_header else signature_header
    return hmac.compare_digest(expected, given.strip())


# ---------------------------------------------------------------------------
class AipriseError(Exception):
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        super().__init__(f"AiPrise {status}: {body!r}")
