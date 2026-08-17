"""Andes KYC docs submission — shared helper for re-upload paths.

Used by:

  * `routes/client_kyc.POST /client/me/andes-kyc-docs`  — self-service
    portal widget for individuals trapped in `kyc_docs_required` /
    `kyc_pending_andes`.
  * `routes/ramp_routes.retry_account` (when files supplied)        —
    admin backoffice fallback that uploads docs on behalf of a user.

This helper REUSES the `provider_user_id` already persisted in
`ramp_accounts` and DOES NOT create new account/wallet — it only calls
the gateway `POST /fiat` (multipart) and reacts to the response.

Idempotency: Redis lock (TTL 60s) per org_id, with mongo fallback.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from db import (
    col, ORGANIZATIONS, ONBOARDING_APPLICATIONS, RAMP_ACCOUNTS,
    RAMP_FIAT_ACCOUNTS, USERS,
)
from audit import log_action

logger = logging.getLogger("prosper.andes_kyc")

_FRIENDLY_REJECT_TOKENS = (
    "unsupported image", "image type", "no nítida", "nítidez",
    "blurry", "low quality", "image quality",
)


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AndesKycError(Exception):
    """Raised by submit_andes_kyc_docs. Carries an HTTP status + friendly msg."""
    def __init__(self, status: int, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retryable = retryable


async def _acquire_lock(org_id: str) -> Optional[str]:
    """Return a lock token if acquired (caller releases it). None if already held."""
    token = secrets.token_hex(8)
    key = f"andes_kyc_lock:{org_id}"
    try:
        import server as srv  # noqa: PLC0415
        if srv.redis_client is not None:
            ok = await srv.redis_client.set(key, token, nx=True, ex=60)
            if ok:
                return token
            return None
    except Exception:  # noqa: BLE001
        pass
    # Mongo fallback: locks collection with TTL index. Best-effort dedupe.
    iso = _iso()
    try:
        res = await col("locks").update_one(
            {"_id": key, "$or": [{"expires_at": {"$lt": iso}},
                                  {"expires_at": {"$exists": False}}]},
            {"$set": {"_id": key, "token": token,
                       "expires_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}},
            upsert=True)
        if res.upserted_id or res.modified_count:
            return token
        return None
    except Exception:  # noqa: BLE001
        # If lock infra is broken, fall back to no dedupe — better to proceed
        # than to block the user. Andes calls are idempotent at user_id.
        logger.warning("andes_kyc lock infra unavailable; proceeding without dedupe")
        return "no-lock"


async def _release_lock(org_id: str, token: Optional[str]) -> None:
    if not token or token == "no-lock":
        return
    key = f"andes_kyc_lock:{org_id}"
    try:
        import server as srv  # noqa: PLC0415
        if srv.redis_client is not None:
            cur = await srv.redis_client.get(key)
            if cur == token:
                await srv.redis_client.delete(key)
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        await col("locks").delete_one({"_id": key, "token": token})
    except Exception:  # noqa: BLE001
        pass


def _validate_file(name: str, content: bytes) -> None:
    """Legacy adapter — delegates to the public `file_validator` module.

    Kept as an internal shim so the Andes KYC production path is not
    reshuffled during Fase 0.5 (behaviour identical: same size limits,
    same allowed types, same error text on failure).
    """
    from services.file_validator import validate_file, FileValidationError
    try:
        validate_file(name, content)
    except FileValidationError as e:
        # Preserve the original AndesKycError(422, ...) contract.
        raise AndesKycError(422, str(e))


async def submit_andes_kyc_docs(
    *, org_id: str,
    files: dict[str, tuple[str, bytes, str]],  # name -> (filename, bytes, ctype)
    actor: Any | None = None,
    source: str = "client_widget",
) -> dict:
    """Submit KYC docs to Andes for an org already provisioned in
    `ramp_accounts`. Reuses `provider_user_id`. Returns a state dict.

    Raises `AndesKycError` for retryable user-facing failures.
    """
    # 1. Dedupe lock.
    lock_token = await _acquire_lock(org_id)
    if lock_token is None:
        raise AndesKycError(409,
            "Ya hay un envío en curso para esta cuenta. Esperá un momento "
            "y volvé a intentar.")

    try:
        # 2. Validate the 3 expected files.
        required = ("face", "id_front", "id_back")
        missing = [k for k in required if k not in files]
        if missing:
            raise AndesKycError(422,
                f"Faltan documentos: {', '.join(missing)}")
        for k in required:
            _validate_file(k, files[k][1])

        # 3. Resolve ramp_account → provider_user_id.
        ramp = await col(RAMP_ACCOUNTS).find_one(
            {"org_id": org_id}, {"_id": 0}) or {}
        if not ramp or not ramp.get("provider_user_id"):
            raise AndesKycError(422,
                "Tu cuenta Andes aún no está creada. Contactá soporte "
                "si esto persiste.")
        provider_user_id = ramp["provider_user_id"]
        chain = ramp.get("wallet_chain") or "stellar"

        # 4. Resolve org + application for the body.
        org_doc = await col(ORGANIZATIONS).find_one(
            {"org_id": org_id}, {"_id": 0}) or {}
        if org_doc.get("type") != "personal":
            raise AndesKycError(409,
                "Este flujo es para personas. Las cuentas business "
                "tienen otro proceso — contactá soporte.")
        app_doc = await col(ONBOARDING_APPLICATIONS).find_one(
            {"org_id": org_id, "applicant_type": "individual",
             "is_deleted": False},
            {"_id": 0}, sort=[("created_at", -1)]) or {}
        if not app_doc:
            raise AndesKycError(422,
                "No encontramos tu application individual. Contactá soporte.")
        indiv = app_doc.get("individual") or {}
        for f in ("last_name", "cuit", "phone", "birthdate"):
            if not indiv.get(f):
                raise AndesKycError(422,
                    f"Falta el campo '{f}' en tu application. "
                    f"Contactá soporte.")

        # 5. POST to gateway. NO logs of file content.
        gw_url = os.environ.get("ANDES_GATEWAY_URL", "http://localhost:8090")
        gw_tok = os.environ.get("GATEWAY_INTERNAL_TOKEN", "")
        headers = {"X-Internal-Token": gw_tok}
        form_data = {
            "user_id":   provider_user_id,
            "chain":     chain,
            "email":     app_doc.get("contact_email") or org_doc.get("primary_email", ""),
            "cuit":      indiv["cuit"],
            "name":      app_doc.get("contact_name") or org_doc.get("legal_name", ""),
            "last_name": indiv["last_name"],
            "phone":     indiv["phone"],
            "birthdate": indiv["birthdate"],
        }
        files_multipart = {k: files[k] for k in required}

        bytes_total = sum(len(b) for _, b, _ in files.values())
        await log_action(actor=actor, action="andes.kyc.docs.submitted",
                         resource_type="organization",
                         resource_id=org_id,
                         metadata={"source": source,
                                   "bytes_total": bytes_total,
                                   "provider_user_id": provider_user_id})

        async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=120.0,
                                        write=60.0, pool=30.0)) as cx:
            r = await cx.post(f"{gw_url}/fiat",
                              data=form_data, files=files_multipart,
                              headers=headers)
        if r.status_code >= 400:
            body_lc = r.text.lower()
            if any(t in body_lc for t in _FRIENDLY_REJECT_TOKENS):
                # Reject for quality — RETRYABLE. DO NOT mark
                # kyc_docs_uploaded_at, leave onboarding_status in
                # kyc_docs_required so the user can try again.
                raise AndesKycError(422,
                    "Las fotos no pasaron el control de calidad. "
                    "Probá de nuevo con más luz y los 4 bordes del DNI "
                    "visibles.", retryable=True)
            raise AndesKycError(502,
                f"andes fiat.create: {r.text[:200]}")

        fiat_resp = r.json()
        onb = (fiat_resp.get("onboarding_status")
                or fiat_resp.get("onboardingStatus") or "pending_approval")
        cvu = fiat_resp.get("cvu")
        alias = fiat_resp.get("alias")
        fiat_account_id = fiat_resp.get("fiat_account_id")

        # 6. Persist ramp_fiat_accounts row (idempotent on fiat_account_id).
        iso = _iso()
        if fiat_account_id:
            await col(RAMP_FIAT_ACCOUNTS).update_one(
                {"org_id": org_id, "fiat_account_id": fiat_account_id},
                {"$set": {
                    "org_id": org_id, "fiat_account_id": fiat_account_id,
                    "ramp_account_id": ramp.get("id"),
                    "cvu": cvu, "alias": alias,
                    "account_type": "user",
                    "onboarding_status": onb,
                    "status": "active" if cvu else "pending",
                    "updated_at": iso,
                }, "$setOnInsert": {
                    "id": "rfa_" + secrets.token_hex(6),
                    "created_at": iso, "is_deleted": False,
                }},
                upsert=True)

        # 7. Branch on Andes response.
        approved = onb in ("approved", "completed")
        if approved:
            new_ra_status = "approved"
            new_ra_msg = None
        else:
            # Async path: Andes accepted the docs but emits CVU OOB. The
            # webhook `fiat.account.created` will activate the user.
            new_ra_status = "kyc_docs_submitted"
            new_ra_msg = ("Documentos enviados a Andes. Estamos esperando "
                          "la emisión de tu CVU, suele tardar unos minutos.")

        await col(RAMP_ACCOUNTS).update_one(
            {"org_id": org_id},
            {"$set": {
                "cvu": cvu or ramp.get("cvu"),
                "alias": alias or ramp.get("alias"),
                "cvu_status": "completed" if cvu else "pending",
                "onboarding_status": new_ra_status,
                "onboarding_message": new_ra_msg,
                "updated_at": iso,
            }})

        # Mark the application as having uploaded docs (success-only).
        await col(ONBOARDING_APPLICATIONS).update_one(
            {"application_id": app_doc["application_id"]},
            {"$set": {"kyc_docs_uploaded_at": iso,
                       "andes_onboarding_status": onb,
                       "updated_at": iso}})

        activation_state: dict = {}
        if approved:
            from services.activation import on_identity_approved
            activation_state = await on_identity_approved(
                org_id=org_id,
                andes_user_id=provider_user_id,
                cvu=cvu, alias=alias,
                fiat_account_id=fiat_account_id,
                source=f"andes_kyc.{source}",
            )

        await log_action(actor=actor, action="andes.kyc.docs.result",
                         resource_type="organization",
                         resource_id=org_id,
                         metadata={"onboarding_status": onb,
                                   "cvu_emitted": bool(cvu),
                                   "activated": activation_state.get("activated", False)})

        return {
            "ok": True,
            "onboarding_status":  onb,
            "ramp_account_status": new_ra_status,
            "cvu":                cvu,
            "alias":              alias,
            "andes_kyc_status":   activation_state.get("andes_kyc_status") or (
                                    "approved" if approved else "pending"),
            "sanctions_status":   activation_state.get("sanctions_status") or "pending",
            "kyb_status":         activation_state.get("kyb_status") or "pending",
            "activated":          activation_state.get("activated", False),
            "can_operate":        activation_state.get("activated", False),
            "next":               ("portal" if activation_state.get("activated")
                                    else "wait_sanctions" if approved
                                    else "wait_webhook"),
        }
    finally:
        await _release_lock(org_id, lock_token)
