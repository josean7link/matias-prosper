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


class ProviderMisconfigured(RuntimeError):
    """Levantada cuando el ambiente es producción y falta configuración
    crítica (template_id / api_key / modo forzado a simulado). El caller
    debe traducirla a HTTP 503. Evita el vector histórico en el que la
    ausencia de credenciales en prod desviaba silenciosamente al
    simulador."""


def _env() -> str:
    return os.environ.get("AIPRISE_ENVIRONMENT", "sandbox").lower()


def base_url() -> str:
    return PROD_BASE_URL if _env() == "production" else SANDBOX_BASE_URL


def api_key() -> str:
    if _env() == "production":
        return os.environ.get("AIPRISE_API_KEY_PRODUCTION", "")
    return os.environ.get("AIPRISE_API_KEY_SANDBOX", "")


# NOTE: env var naming matches the admin_settings catalog
# (AIPRISE_TEMPLATE_KYC_ID / AIPRISE_TEMPLATE_KYB_ID). We also accept the
# legacy `AIPRISE_KYC_TEMPLATE_ID` / `AIPRISE_KYB_TEMPLATE_ID` for backward
# compatibility with already-set ops .env files.
def kyc_template_id() -> str:
    return (os.environ.get("AIPRISE_TEMPLATE_KYC_ID")
              or os.environ.get("AIPRISE_KYC_TEMPLATE_ID", "")).strip()


def kyb_template_id() -> str:
    return (os.environ.get("AIPRISE_TEMPLATE_KYB_ID")
              or os.environ.get("AIPRISE_KYB_TEMPLATE_ID", "")).strip()


def webhook_secret() -> str:
    return os.environ.get("AIPRISE_WEBHOOK_SECRET", "").strip()


# Phase 22+ — super_admin toggle persisted in `integration_settings.aiprise.mode`.
# Possible values:
#   * "real" / "sandbox" / "production" → use AiPrise live (templates +
#     api_key required; if missing we degrade to simulated and warn).
#   * "simulated"                       → force the local simulator
#     regardless of env vars; useful while testing.
# When the setting is missing (fresh install) the default is `sandbox`.
async def kyc_provider_mode() -> str:
    """Resolve the effective KYC/KYB provider mode (Mongo-persisted)."""
    try:
        from db import col, INTEGRATION_SETTINGS
        doc = await col(INTEGRATION_SETTINGS).find_one(
            {"provider": "aiprise"}, {"_id": 0, "mode": 1})
        return ((doc or {}).get("mode") or "sandbox").lower()
    except Exception as e:  # noqa: BLE001
        logger.warning("kyc_provider_mode lookup failed: %s — default sandbox", e)
        return "sandbox"


async def is_simulated_async(kind: Literal["kyc", "kyb"]) -> bool:
    """Async variant — honors the super_admin toggle in Mongo + falls back
    to the credential-presence check.

    Fail-safe en producción: si el ambiente es `production` y falta el
    template_id o la API key, NO caemos al simulador — subimos
    `ProviderMisconfigured` para que el caller (p.ej. /onboarding/apply)
    devuelva 503. Esto cierra el vector histórico en el que un template
    vacío en prod habilitaba una vía sin credenciales para autoaprobar
    orgs. Compañero del bloqueo por-construcción de /apply/simulate en
    prod (routes/onboarding.py:376)."""
    from kyb.verification_modes import kyb_environment
    mode = await kyc_provider_mode()
    if mode == "simulated":
        # Toggle Mongo explícito. En prod, prohibido: no arrastrar el
        # riesgo si un super_admin lo dejó puesto por error.
        if kyb_environment() == "production":
            raise ProviderMisconfigured(
                "AiPrise en modo 'simulated' no está permitido en "
                "producción. Cambiar el toggle en integration_settings.")
        return True
    # mode is real (sandbox/production); if creds are missing, degrade —
    # excepto en producción, donde fallamos duro.
    tid = kyc_template_id() if kind == "kyc" else kyb_template_id()
    if not tid or not api_key():
        if kyb_environment() == "production":
            raise ProviderMisconfigured(
                f"AiPrise {kind.upper()} sin template_id/api_key en "
                "producción — fallback simulator deshabilitado. "
                "Cargar credenciales.")
        logger.warning("[AIPRISE] mode=%s but %s template_id/api_key missing — "
                          "falling back to simulator. Cargar credenciales.",
                          mode, kind.upper())
        return True
    return False


def is_simulated(kind: Literal["kyc", "kyb"]) -> bool:
    """Sync legacy check — env-only, no Mongo toggle. Kept for callers that
    can't go async; new callers should use `is_simulated_async`."""
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
    # AiPrise expects `X-API-Key` (NOT `Authorization: Bearer`). Live-tested
    # 2026-05-14: Bearer → 401 "Bad credentials", X-API-Key → 200/403.
    return {
        "X-API-Key":    api_key(),
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "User-Agent":   "prosper-backend/0.2",
    }


# ---------------------------------------------------------------------------
# Live health probe — only meaningful when running against the live API.
# Calls verification with an empty template_id; AiPrise responds 403
# "template_id not associated" when auth is OK + creds invalid otherwise.
# ---------------------------------------------------------------------------
async def health_check() -> dict:
    if not api_key():
        return {"ok": False, "env": _env(),
                 "error": f"No API key for env={_env()}",
                 "simulated": True}
    payload = {"template_id": "__probe__", "client_reference_id": "__probe__"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"{base_url()}/verify/get_user_verification_url",
                json=payload, headers=_headers())
    except httpx.HTTPError as e:
        return {"ok": False, "env": _env(), "error": str(e)[:200]}

    # 401 = bad creds. 403 = template missing (auth ok). 2xx = template ok.
    if r.status_code == 401:
        return {"ok": False, "env": _env(),
                 "error": (r.text or "401 unauthorized")[:200]}
    return {"ok": True, "env": _env(), "status_code": r.status_code,
             "templates_configured": bool(kyc_template_id() and kyb_template_id())}


# ---------------------------------------------------------------------------
# Verification creation
# ---------------------------------------------------------------------------
async def create_user_verification(*, client_reference_id: str, user_data: dict,
                                   callback_url: str, redirect_uri: str) -> dict:
    """Create a KYC verification and return hosted_url + session id.

    Reads the super_admin `kyc_provider_mode` toggle from Mongo via
    `is_simulated_async`. When `simulated` (or when creds missing in
    real-mode) returns a local simulator session.
    """
    if await is_simulated_async("kyc"):
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
    """Create a KYB verification and return hosted_url + session id.

    Reads the super_admin `kyc_provider_mode` toggle from Mongo via
    `is_simulated_async` (same toggle controls KYC + KYB).
    """
    if await is_simulated_async("kyb"):
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
