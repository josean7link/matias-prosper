"""SumsubProvider — implementación del contrato VerificationProvider
sobre Sumsub. Bloque 2 de la Fase 5b.

Selector de ambiente: `SUMSUB_ENVIRONMENT` con valores "sandbox" |
"production". El módulo valida config al arrancar vía `sumsub_startup_check`
(invocado desde server.py); si falta, el backend no arranca.

Credenciales resueltas desde `kyb_provider_configs` filtrando por
`environment`: el token del ambiente A nunca se usa con el secret del
ambiente B."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from db import col
from kyb.models import (KYB_CASES, KYB_EXTERNAL_SUBJECTS,
                         KYB_PROVIDER_CALLS, KYB_PROVIDER_CONFIGS,
                         KYB_VERIFICATIONS)
from kyb.providers.base import (Applicant, AccessToken, Capability,
                                 Environment,
                                 ProviderEnvironmentMismatch, ProviderError,
                                 ProviderNotConfigured,
                                 ProviderSignatureInvalid,
                                 ProviderTransientError,
                                 ScreeningHit, SubjectRef, SubjectType,
                                 VerificationOutcome, VerificationProvider,
                                 VerificationSnapshot, WebhookPayload)
from models import utc_now
from services.secret_box import decrypt as _secret_decrypt


logger = logging.getLogger("prosper.kyb.sumsub")

# Endpoints de Sumsub.
_BASE_URLS = {
    "sandbox":    "https://api.sumsub.com",   # sumsub usa el mismo host
    "production": "https://api.sumsub.com",   # y distingue por API key
}

_LEVEL_ENV_KEYS = {
    "company":              "SUMSUB_LEVEL_COMPANY",
    "legal_representative": "SUMSUB_LEVEL_INDIVIDUAL",
    "ubo":                  "SUMSUB_LEVEL_UBO",
}


# ---------------------------------------------------------------------------
# Startup validation — se invoca desde server.py al arranque. Si el
# proceso llega hasta acá y falla, el backend no arranca. Fail-fast.
# ---------------------------------------------------------------------------
async def sumsub_startup_check() -> dict:
    """Valida config al arrancar. Retorna un dict con `environment` y
    `status` (para el health check). NUNCA incluye credenciales."""
    env_ = os.environ.get("SUMSUB_ENVIRONMENT", "").strip().lower()
    if env_ not in ("sandbox", "production"):
        raise RuntimeError(
            "SUMSUB_ENVIRONMENT must be 'sandbox' or 'production' — got "
            f"{env_!r}. Backend refuses to start with a missing/invalid "
            "value.")

    # Si el flag global está apagado, no validamos credenciales del
    # provider (el registry corta antes de instanciar). Igual reportamos
    # el env.
    if os.environ.get("KYB_PROVIDER_SUMSUB_ENABLED", "false") \
            .strip().lower() != "true":
        return {"environment": env_, "status": "disabled_by_flag",
                "warning": None}

    # Con el flag encendido: en production, credenciales productivas son
    # obligatorias.
    if env_ == "production":
        try:
            await _load_credentials("production")
        except ProviderNotConfigured as e:
            raise RuntimeError(
                f"SUMSUB_ENVIRONMENT=production but production credentials "
                f"are missing: {e}. Backend refuses to start.") from e

    warning = None
    from kyb.verification_modes import kyb_environment
    if kyb_environment() == "production" and env_ == "sandbox":
        warning = ("app_environment=production but SUMSUB_ENVIRONMENT="
                    "sandbox — running with sandbox credentials against "
                    "prod app. This is the validation window state; make "
                    "sure it's intentional.")
        logger.warning("[SUMSUB] %s", warning)

    return {"environment": env_, "status": "ok", "warning": warning}


# ---------------------------------------------------------------------------
# Credential resolution — from kyb_provider_configs, encrypted at rest.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Credentials:
    api_key: str          # Sumsub App Token
    secret: str           # HMAC secret
    environment: str      # "sandbox" | "production" — inmutable


async def _load_credentials(environment: str) -> _Credentials:
    """Trae las credenciales del ambiente pedido desde
    `kyb_provider_configs`. Bloquea explícitamente cualquier intento de
    mezclar ambientes: filtra por `environment=environment`."""
    doc = await col(KYB_PROVIDER_CONFIGS).find_one(
        {"provider": "sumsub", "environment": environment,
          "enabled": True}, {"_id": 0})
    if not doc:
        raise ProviderNotConfigured(
            f"no enabled sumsub config for environment={environment!r}")

    enc = doc.get("credentials_encrypted")
    if not enc:
        raise ProviderNotConfigured(
            f"sumsub {environment} config has no credentials_encrypted")

    try:
        # Formato interno: JSON con {"api_key": ..., "secret": ...}.
        raw = _secret_decrypt(enc)
        creds = json.loads(raw)
        return _Credentials(
            api_key=creds["api_key"], secret=creds["secret"],
            environment=environment)
    except Exception as e:
        # NO exponer detalle del error criptográfico ni fragmentos de
        # credenciales. Log interno tampoco los muestra.
        logger.error("[SUMSUB] credential decrypt/parse failed for "
                     "environment=%s (details redacted)", environment)
        raise ProviderNotConfigured(
            f"cannot load sumsub credentials for {environment!r}") from e


# ---------------------------------------------------------------------------
# Signing — App Token flavor, HMAC-SHA256 header set.
# ---------------------------------------------------------------------------
def _sign_request(secret: str, ts: int, method: str, path: str,
                    body: bytes) -> str:
    msg = f"{ts}{method.upper()}{path}".encode() + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Telemetry — kyb_provider_calls (TTL 30d).
# ---------------------------------------------------------------------------
async def _log_call(direction: str, endpoint: str, status_code: Optional[int],
                     latency_ms: Optional[float], ok: bool,
                     error_code: Optional[str] = None,
                     signature_valid: Optional[bool] = None):
    """Sin cuerpos ni credenciales. Sólo metadata operacional."""
    try:
        await col(KYB_PROVIDER_CALLS).insert_one({
            "provider": "sumsub",
            "direction": direction,
            "endpoint": endpoint,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "ok": ok,
            "error_code": error_code,
            "signature_valid": signature_valid,
            "created_at": time.time(),
        })
    except Exception:
        # Nunca hacer que la telemetría rompa el flujo real.
        logger.exception("[SUMSUB] telemetry write failed")


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------
class SumsubProvider(VerificationProvider):
    provider_id = "sumsub"

    def __init__(self, environment: Environment):
        if environment not in ("sandbox", "production"):
            raise ProviderNotConfigured(
                f"invalid sumsub environment {environment!r}")
        self.environment = environment
        self._base_url = _BASE_URLS[environment]
        self._creds: Optional[_Credentials] = None

    # ---------------------- capabilities ----------------------
    def supports(self, capability: Capability) -> bool:
        # Sumsub cubre identity + screening (comparten applicant), no
        # company_registry.
        return capability in ("identity", "screening")

    def derive_external_user_id(self, subject: SubjectRef) -> str:
        """Determinístico: SHA-256(case_id|subject_type|subject_id).
        Idempotente para reintentos. Corto (32 chars, sumsub acepta hasta
        64) y no revela información del caso."""
        raw = f"{subject.case_id}|{subject.subject_type}|" \
              f"{subject.subject_id or 'na'}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ---------------------- credentials cache ----------------------
    async def _get_creds(self) -> _Credentials:
        if self._creds is None:
            self._creds = await _load_credentials(self.environment)
        return self._creds

    # ---------------------- HTTP shim ----------------------
    async def _request(self, method: str, path: str,
                        body: Optional[dict] = None) -> dict:
        """Wrapper de httpx firmado. Punto de mock en tests."""
        creds = await self._get_creds()
        raw = json.dumps(body).encode() if body is not None else b""
        ts = int(time.time())
        sig = _sign_request(creds.secret, ts, method, path, raw)
        headers = {
            "X-App-Token": creds.api_key,
            "X-App-Access-Sig": sig,
            "X-App-Access-Ts": str(ts),
            "Content-Type": "application/json",
        }
        url = self._base_url + path
        started = time.time()
        status: Optional[int] = None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.request(method, url, content=raw,
                                          headers=headers)
                status = r.status_code
                if r.status_code >= 500:
                    raise ProviderTransientError(
                        f"sumsub upstream {r.status_code} on {path}")
                if r.status_code >= 400:
                    raise ProviderError(
                        f"sumsub {r.status_code} on {path}")
                return r.json() if r.content else {}
        except httpx.HTTPError as e:
            raise ProviderTransientError(f"sumsub network error: {e}") from e
        finally:
            latency_ms = (time.time() - started) * 1000
            ok = status is not None and status < 400
            asyncio.create_task(_log_call(
                direction="outbound", endpoint=f"{method} {path}",
                status_code=status, latency_ms=latency_ms, ok=ok))

    # ---------------------- coherence checks ----------------------
    async def _assert_env_coherence(self, subject: SubjectRef) -> dict:
        """Enforza:
          - is_test_case=True  ↔ SUMSUB_ENVIRONMENT=sandbox
          - is_test_case=False ↔ SUMSUB_ENVIRONMENT=production
        Retorna el case doc si pasa."""
        case = await col(KYB_CASES).find_one({"case_id": subject.case_id},
                                               {"_id": 0})
        if not case:
            raise ProviderError(f"case {subject.case_id!r} not found")
        is_test = bool(case.get("is_test_case", False))
        if is_test and self.environment == "production":
            raise ProviderEnvironmentMismatch(
                "cannot use production applicant on a test case")
        if not is_test and self.environment == "sandbox":
            raise ProviderEnvironmentMismatch(
                "cannot use sandbox applicant on a production case")
        return case

    # ---------------------- ensure_applicant ----------------------
    async def ensure_applicant(self, subject: SubjectRef,
                                *, level_hint: Capability) -> Applicant:
        await self._assert_env_coherence(subject)
        eid = self.derive_external_user_id(subject)

        # 1) Existe ya en Mongo?
        existing = await col(KYB_EXTERNAL_SUBJECTS).find_one({
            "case_id": subject.case_id,
            "subject_type": subject.subject_type,
            "subject_id": subject.subject_id,
            "provider": self.provider_id})
        if existing:
            # Ambiente cruzado registrado → error tipado
            if existing.get("environment") != self.environment:
                raise ProviderEnvironmentMismatch(
                    "existing applicant belongs to a different "
                    "environment; refusing to re-use")
            return Applicant(
                subject=subject, provider=self.provider_id,
                environment=self.environment,
                external_user_id=existing["external_user_id"],
                provider_applicant_id=existing.get("provider_applicant_id"),
                level_name=existing.get("level_name"),
                created_at=existing.get("created_at", ""))

        # 2) Crear en Sumsub — nivel según sujeto
        level_name = os.environ.get(_LEVEL_ENV_KEYS[subject.subject_type], "")
        if not level_name:
            raise ProviderNotConfigured(
                f"missing env var {_LEVEL_ENV_KEYS[subject.subject_type]}")
        resp = await self._request("POST",
            f"/resources/applicants?levelName={level_name}",
            {"externalUserId": eid, "type": ("individual"
                if subject.subject_type != "company" else "company")})
        pid = resp.get("id")
        if not pid:
            raise ProviderError("sumsub did not return applicant id")

        now = utc_now()
        # 3) Persistir con $setOnInsert sobre environment (inmutable)
        await col(KYB_EXTERNAL_SUBJECTS).update_one({
            "case_id": subject.case_id,
            "subject_type": subject.subject_type,
            "subject_id": subject.subject_id,
            "provider": self.provider_id},
            {"$setOnInsert": {
                "case_id": subject.case_id,
                "subject_type": subject.subject_type,
                "subject_id": subject.subject_id,
                "provider": self.provider_id,
                "environment": self.environment,
                "external_user_id": eid,
                "provider_applicant_id": pid,
                "level_name": level_name,
                "created_at": now},
             "$set": {"updated_at": now, "last_synced_at": now}},
            upsert=True)

        from kyb.audit import kyb_audit
        await kyb_audit(event="kyb.provider.applicant_created",
                         case_id=subject.case_id, actor=None,
                         metadata={"provider": self.provider_id,
                                    "environment": self.environment,
                                    "subject_type": subject.subject_type,
                                    "subject_id": subject.subject_id,
                                    "external_user_id": eid,
                                    "provider_applicant_id": pid})
        return Applicant(
            subject=subject, provider=self.provider_id,
            environment=self.environment, external_user_id=eid,
            provider_applicant_id=pid, level_name=level_name,
            created_at=now)

    # ---------------------- create_access_token ----------------------
    async def create_access_token(self, applicant: Applicant,
                                    *, ttl_seconds: int = 600
                                    ) -> AccessToken:
        if applicant.environment != self.environment:
            raise ProviderEnvironmentMismatch(
                "applicant belongs to a different sumsub environment")
        level = applicant.level_name or ""
        resp = await self._request("POST",
            f"/resources/accessTokens?userId={applicant.external_user_id}"
            f"&levelName={level}&ttlInSecs={ttl_seconds}", None)
        token = resp.get("token")
        if not token:
            raise ProviderError("sumsub did not return access token")
        # NUNCA persistimos el token. Auditamos su emisión sin el valor.
        from kyb.audit import kyb_audit
        await kyb_audit(event="kyb.provider.token_generated",
                         case_id=applicant.subject.case_id, actor=None,
                         metadata={"provider": self.provider_id,
                                    "environment": self.environment,
                                    "external_user_id":
                                        applicant.external_user_id,
                                    "ttl_seconds": ttl_seconds})
        return AccessToken(
            token=token,
            expires_at=utc_now(),   # sumsub no devuelve exp; TTL cliente
            external_user_id=applicant.external_user_id,
            level_name=level)

    # ---------------------- start_verification ----------------------
    async def start_verification(self, applicant: Applicant,
                                    capability: Capability,
                                    *, trigger: str = "orchestrator"
                                    ) -> VerificationSnapshot:
        if not self.supports(capability):
            raise ProviderError(
                f"sumsub does not support capability={capability!r}")
        await self._assert_env_coherence(applicant.subject)
        if applicant.environment != self.environment:
            raise ProviderEnvironmentMismatch(
                "applicant belongs to a different sumsub environment")

        # Persistir el disparo del verification en kyb_verifications.
        now = utc_now()
        # Sumsub inicia el flujo cuando el cliente sube docs vía SDK.
        # Aquí registramos que el proceso quedó "in_progress" del lado
        # nuestro, y esperamos el webhook.
        v = {
            "verification_id": f"ver_sumsub_{applicant.external_user_id}"
                                f"_{capability}",
            "case_id": applicant.subject.case_id,
            "subject_type": applicant.subject.subject_type,
            "subject_id": applicant.subject.subject_id,
            "kind": capability, "mode": "automatic", "source": "provider",
            "provider": self.provider_id,
            "provider_reference": applicant.provider_applicant_id,
            "status": "in_progress",
            "requested_at": now, "updated_at": now,
        }
        await col(KYB_VERIFICATIONS).update_one(
            {"verification_id": v["verification_id"]},
            {"$set": v, "$setOnInsert": {"created_at": now}}, upsert=True)
        return VerificationSnapshot(
            subject=applicant.subject, capability=capability,
            provider=self.provider_id,
            provider_reference=applicant.provider_applicant_id,
            status="in_progress",
            normalized_result={"mode": "automatic", "trigger": trigger})

    # ---------------------- get_verdict ----------------------
    async def get_verdict(self, applicant: Applicant,
                            capability: Capability
                            ) -> Optional[VerificationSnapshot]:
        """SOLO LECTURA local, nunca sale a red. Documentado en el
        contrato base.py."""
        doc = await col(KYB_VERIFICATIONS).find_one({
            "case_id": applicant.subject.case_id,
            "subject_type": applicant.subject.subject_type,
            "subject_id": applicant.subject.subject_id,
            "kind": capability, "provider": self.provider_id,
        }, {"_id": 0}, sort=[("completed_at", -1), ("requested_at", -1)])
        if not doc:
            return None
        return VerificationSnapshot(
            subject=applicant.subject, capability=capability,
            provider=self.provider_id,
            provider_reference=doc.get("provider_reference"),
            status=doc.get("status", "pending"),
            outcome=doc.get("outcome"),
            normalized_result=doc.get("normalized_result") or {},
            raw_response_ref=doc.get("raw_response_ref"),
            provider_event_id=doc.get("provider_event_id"),
            provider_event_ts=doc.get("provider_event_ts"),
            error=doc.get("error"))

    # ---------------------- validate_webhook ----------------------
    _REVIEW_TO_OUTCOME = {
        "GREEN":  "approved",
        "RED":    "rejected",
    }

    async def validate_webhook(self, payload: WebhookPayload
                                ) -> tuple[Applicant, VerificationSnapshot]:
        # Parse first (para saber a qué applicant se refiere y por lo
        # tanto contra qué secret validar).
        try:
            event = json.loads(payload.raw_body)
        except Exception as e:
            raise ProviderError(f"invalid webhook body: {e}") from e

        applicant_id = event.get("applicantId")
        external_user_id = event.get("externalUserId")
        if not applicant_id or not external_user_id:
            raise ProviderError("webhook missing applicant identifiers")

        # Ubicar el applicant local: acá se decide contra QUÉ secret
        # (ambiente) validar la firma. El ambiente activo global NO
        # decide — sí la persistencia del applicant.
        sub_doc = await col(KYB_EXTERNAL_SUBJECTS).find_one({
            "provider": self.provider_id,
            "external_user_id": external_user_id,
            "provider_applicant_id": applicant_id})
        if not sub_doc:
            raise ProviderError("unknown applicant on webhook")

        applicant_env = sub_doc.get("environment")
        creds = await _load_credentials(applicant_env)

        # Firma HMAC contra el secret del ambiente del applicant.
        received = (payload.headers.get("x-payload-digest")
                    or payload.headers.get("x-app-access-sig") or "")
        expected = hmac.new(
            creds.secret.encode(), payload.raw_body,
            hashlib.sha256).hexdigest()
        signature_valid = hmac.compare_digest(received, expected)

        # Telemetría del webhook — sin firma, sin body.
        asyncio.create_task(_log_call(
            direction="webhook", endpoint="/webhooks/sumsub",
            status_code=None, latency_ms=None, ok=signature_valid,
            signature_valid=signature_valid))

        if not signature_valid:
            # Detalle al log interno — sin fragmentos.
            logger.warning("[SUMSUB] invalid webhook signature for "
                            "applicant_env=%s applicant_id=%s "
                            "(details redacted)",
                            applicant_env, applicant_id)
            raise ProviderSignatureInvalid("invalid webhook signature")

        # Ambiente cruzado detectado tarde: si el applicant es de un
        # env distinto al activo global, es 409 (bloque 3 lo traduce).
        if applicant_env != self.environment:
            raise ProviderEnvironmentMismatch(
                f"applicant belongs to sumsub environment "
                f"{applicant_env!r} but active is {self.environment!r}")

        # Coherencia con is_test_case del caso.
        case = await col(KYB_CASES).find_one({"case_id": sub_doc["case_id"]},
                                                {"is_test_case": 1})
        if case is not None:
            is_test = bool(case.get("is_test_case", False))
            if is_test and applicant_env == "production":
                raise ProviderEnvironmentMismatch(
                    "webhook for production applicant on a test case")
            if not is_test and applicant_env == "sandbox":
                raise ProviderEnvironmentMismatch(
                    "webhook for sandbox applicant on a production case")

        # Armar el snapshot — sin persistir. Bloque 3 hará la escritura
        # con idempotencia sobre (provider_event_id, provider_reference).
        review = event.get("reviewResult") or {}
        review_answer = review.get("reviewAnswer")
        outcome: Optional[VerificationOutcome] = self._REVIEW_TO_OUTCOME.get(
            review_answer)
        status = "completed" if outcome else "in_progress"

        applicant = Applicant(
            subject=SubjectRef(case_id=sub_doc["case_id"],
                                subject_type=sub_doc["subject_type"],
                                subject_id=sub_doc.get("subject_id")),
            provider=self.provider_id,
            environment=applicant_env,
            external_user_id=external_user_id,
            provider_applicant_id=applicant_id,
            level_name=sub_doc.get("level_name"),
            created_at=sub_doc.get("created_at", ""))

        snapshot = VerificationSnapshot(
            subject=applicant.subject,
            capability="identity",   # sumsub agrupa identity+screening
            provider=self.provider_id,
            provider_reference=applicant_id,
            status=status, outcome=outcome,
            normalized_result={"review_answer": review_answer,
                                "reject_labels": review.get("rejectLabels")
                                    or []},
            provider_event_id=event.get("id"),
            provider_event_ts=event.get("createdAtMs")
                                or event.get("createdAt"))
        return applicant, snapshot
