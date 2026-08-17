"""ManualProvider — envuelve el camino de checklists manuales existente
(`kyb.manual_checks.generate_checks`) y cumple el contrato
`VerificationProvider`.

Su razón de ser: garantizar que la interfaz no quedó moldeada a un
solo proveedor. Además da un `subject_ref` estable — si un caso mañana
pasa de modo manual a automático, el sujeto ya existe en
`kyb_external_subjects` y la transición no requiere inventar una
identidad nueva a mitad de camino."""
from __future__ import annotations

from typing import Optional

from db import col
from kyb.models import (KYB_CASES, KYB_EXTERNAL_SUBJECTS, KYB_VERIFICATIONS)
from kyb.providers.base import (Applicant, AccessToken, Capability,
                                ProviderError, SubjectRef,
                                VerificationProvider, VerificationSnapshot,
                                WebhookPayload)
from models import utc_now


class ManualProvider(VerificationProvider):
    """Comportamiento:
      - `supports(cap)` → True para las tres capabilities.
      - `derive_external_user_id` → canónico y determinístico.
      - `ensure_applicant` → persiste con `provider="manual"`,
        `environment=None`, `provider_applicant_id=None`. Se comporta
        idempotente por (case_id, subject_type, subject_id, provider).
      - `create_access_token` → `ProviderError` (manual no tiene SDK).
      - `start_verification(applicant, cap)` → invoca
        `generate_checks(case, actor, request, only_categories={cap})`
        para producir SOLO el checklist de la capability solicitada.
      - `get_verdict(applicant, cap)` → lee `kyb_verifications` local.
      - `validate_webhook` → `NotImplementedError` (manual no tiene
        webhook)."""

    provider_id = "manual"
    environment: Optional[str] = None

    def supports(self, capability: Capability) -> bool:
        return capability in ("identity", "screening", "company_registry")

    def derive_external_user_id(self, subject: SubjectRef) -> str:
        # Determinístico, canónico. No se usa fuera del provider.
        sid = subject.subject_id or "na"
        return f"manual:{subject.case_id}:{subject.subject_type}:{sid}"

    async def ensure_applicant(self, subject: SubjectRef,
                                *, level_hint: Capability) -> Applicant:
        eid = self.derive_external_user_id(subject)
        now = utc_now()
        # upsert idempotente. `environment` NUNCA se toca en un update
        # posterior — lo garantizamos con `$setOnInsert`.
        q = {"case_id": subject.case_id,
             "subject_type": subject.subject_type,
             "subject_id": subject.subject_id,
             "provider": self.provider_id}
        set_on_insert = {
            "case_id": subject.case_id,
            "subject_type": subject.subject_type,
            "subject_id": subject.subject_id,
            "provider": self.provider_id,
            "environment": None,          # inmutable — manual no aplica
            "external_user_id": eid,
            "provider_applicant_id": None,
            "level_name": None,
            "created_at": now,
        }
        set_on_update = {"updated_at": now,
                          "last_synced_at": now}
        await col(KYB_EXTERNAL_SUBJECTS).update_one(
            q, {"$setOnInsert": set_on_insert, "$set": set_on_update},
            upsert=True)
        return Applicant(
            subject=subject, provider=self.provider_id,
            environment=None, external_user_id=eid,
            provider_applicant_id=None, level_name=None,
            created_at=now)

    async def create_access_token(self, applicant: Applicant,
                                    *, ttl_seconds: int = 600
                                    ) -> AccessToken:
        raise ProviderError("manual provider has no SDK access token")

    async def start_verification(self, applicant: Applicant,
                                    capability: Capability,
                                    *, trigger: str = "orchestrator"
                                    ) -> VerificationSnapshot:
        """Ejerce el path manual sólo para la capability solicitada.
        Idempotente: `generate_checks` deduplica por
        (case_id, category, subject_id)."""
        from kyb.manual_checks import generate_checks
        case = await col(KYB_CASES).find_one(
            {"case_id": applicant.subject.case_id}, {"_id": 0})
        if not case:
            raise ProviderError(
                f"case {applicant.subject.case_id!r} not found")
        # Se filtra por capability en generate_checks (parámetro nuevo,
        # backward-compatible con los 3 callers existentes).
        await generate_checks(case, actor=None, request=None,
                               only_categories={capability})
        return VerificationSnapshot(
            subject=applicant.subject,
            capability=capability,
            provider=self.provider_id,
            provider_reference=None,
            status="pending",
            outcome=None,
            normalized_result={"mode": "manual", "trigger": trigger},
        )

    async def get_verdict(self, applicant: Applicant,
                            capability: Capability
                            ) -> Optional[VerificationSnapshot]:
        # Sólo LECTURA local. Nunca sale a red.
        kind = ("company_registry" if capability == "company_registry"
                else capability)
        doc = await col(KYB_VERIFICATIONS).find_one({
            "case_id": applicant.subject.case_id,
            "subject_type": applicant.subject.subject_type,
            "subject_id": applicant.subject.subject_id,
            "kind": kind,
            "provider": self.provider_id,
        }, {"_id": 0}, sort=[("completed_at", -1), ("requested_at", -1)])
        if not doc:
            return None
        return VerificationSnapshot(
            subject=applicant.subject,
            capability=capability,
            provider=self.provider_id,
            provider_reference=doc.get("provider_reference"),
            status=doc.get("status", "pending"),
            outcome=doc.get("outcome"),
            normalized_result=doc.get("normalized_result") or {},
            raw_response_ref=doc.get("raw_response_ref"),
            provider_event_id=doc.get("provider_event_id"),
            provider_event_ts=doc.get("provider_event_ts"),
            error=doc.get("error"),
        )

    async def validate_webhook(self, payload: WebhookPayload
                                ) -> tuple[Applicant, VerificationSnapshot]:
        raise NotImplementedError(
            "manual provider has no webhook — this method should never be "
            "called on ManualProvider. The receiver dispatches by "
            "content-type / route, not by provider instance.")
