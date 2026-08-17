"""Índices del módulo KYB (Fase 1).

Solo se ejecuta con KYB_MODULE_ENABLED=true (gate en db.ensure_indexes).
NO toca ningún índice existente: los de kyb_cases legacy (org_id,
created_at, status, is_deleted, status+is_deleted) se conservan.
"""
from __future__ import annotations

from datetime import timedelta

from db import col

from .models import (KYB_BENEFICIAL_OWNERS, KYB_CASES, KYB_COMPANY_PROFILES,
                     KYB_DOCUMENTS, KYB_EXTERNAL_SUBJECTS, KYB_PROVIDER_CALLS,
                     KYB_PROVIDER_CONFIGS, KYB_SCREENING_HITS,
                     KYB_SHARED_LINKS, KYB_VERIFICATIONS)


async def ensure_kyb_indexes() -> None:
    # kyb_cases — solo índices NUEVOS (los existentes no se tocan).
    await col(KYB_CASES).create_index("case_id", unique=True, sparse=True)
    await col(KYB_CASES).create_index("assigned_to")
    await col(KYB_CASES).create_index("submitted_at")
    await col(KYB_CASES).create_index([("status", 1), ("priority", 1)])

    await col(KYB_COMPANY_PROFILES).create_index("case_id", unique=True)
    await col(KYB_COMPANY_PROFILES).create_index("tax_id", unique=True,
                                                 sparse=True)

    await col(KYB_BENEFICIAL_OWNERS).create_index("case_id")
    await col(KYB_BENEFICIAL_OWNERS).create_index("ubo_id", unique=True)

    await col(KYB_DOCUMENTS).create_index("case_id")
    await col(KYB_DOCUMENTS).create_index([("case_id", 1), ("slot", 1),
                                           ("is_current", 1)])
    await col(KYB_DOCUMENTS).create_index("document_id", unique=True)

    await col(KYB_EXTERNAL_SUBJECTS).create_index("subject_ref", unique=True)
    await col(KYB_EXTERNAL_SUBJECTS).create_index(
        [("case_id", 1), ("subject_type", 1), ("subject_id", 1)], unique=True)
    # sparse: los subjects nacen sin external_user_id hasta que el
    # proveedor lo asigna — unique a secas colisionaría en null.
    await col(KYB_EXTERNAL_SUBJECTS).create_index("external_user_id",
                                                  unique=True, sparse=True)
    await col(KYB_EXTERNAL_SUBJECTS).create_index("provider_applicant_id",
                                                  sparse=True)

    await col(KYB_VERIFICATIONS).create_index("case_id")
    await col(KYB_VERIFICATIONS).create_index("verification_id", unique=True)
    await col(KYB_VERIFICATIONS).create_index([("case_id", 1), ("kind", 1),
                                               ("subject_id", 1)])
    # Fase 5b — idempotencia del webhook receiver. La llave lógica es
    # (event_id, applicant_id); usamos provider_reference como stand-in
    # del applicant_id para no forzar una tercera columna. Sparse porque
    # los docs 5a no tienen provider_event_id.
    await col(KYB_VERIFICATIONS).create_index(
        [("provider_event_id", 1), ("provider_reference", 1)],
        unique=True, sparse=True,
        name="uniq_provider_event_idempotency")

    await col(KYB_SCREENING_HITS).create_index("case_id")
    await col(KYB_SCREENING_HITS).create_index("hit_id", unique=True)

    await col(KYB_SHARED_LINKS).create_index("link_id", unique=True)
    await col(KYB_SHARED_LINKS).create_index("token_hash", unique=True)
    await col(KYB_SHARED_LINKS).create_index("case_id")

    await col(KYB_PROVIDER_CONFIGS).create_index(
        [("category", 1), ("provider", 1)], unique=True)

    # Fase 5a — checklists manuales y plantillas.
    from .models import KYB_MANUAL_CHECKS, KYB_MANUAL_CHECK_TEMPLATES
    await col(KYB_MANUAL_CHECKS).create_index("check_id", unique=True)
    await col(KYB_MANUAL_CHECKS).create_index(
        [("case_id", 1), ("category", 1), ("subject_id", 1)])
    await col(KYB_MANUAL_CHECKS).create_index(
        [("case_id", 1), ("contributors", 1)])
    await col(KYB_MANUAL_CHECK_TEMPLATES).create_index(
        [("template_id", 1), ("version", 1)], unique=True)
    await col(KYB_MANUAL_CHECK_TEMPLATES).create_index(
        [("category", 1), ("country", 1), ("active", 1)])

    # Fase 2 — tokens de signup/activación (hash en reposo + TTL).
    from .tokens import KYB_SIGNUP_TOKENS
    await col(KYB_SIGNUP_TOKENS).create_index("token_hash", unique=True)
    await col(KYB_SIGNUP_TOKENS).create_index("case_id")
    await col(KYB_SIGNUP_TOKENS).create_index([("email", 1), ("kind", 1)])
    await col(KYB_SIGNUP_TOKENS).create_index(
        "expires_at", expireAfterSeconds=0,
        name="kyb_signup_tokens_expires_ttl")

    # Telemetría: TTL 30 días. `created_at` acá es BSON Date (única
    # excepción a la convención de ISO strings — el TTL de Mongo solo
    # funciona sobre Date).
    await col(KYB_PROVIDER_CALLS).create_index(
        "created_at",
        expireAfterSeconds=int(timedelta(days=30).total_seconds()),
        name="kyb_provider_calls_ttl_30d")

    # F7 — modelo de riesgo versionado + revisiones de registro
    from .models import KYB_REGISTRY_REVIEWS, KYB_RISK_MODEL_VERSIONS
    await col(KYB_RISK_MODEL_VERSIONS).create_index("version", unique=True)
    await col(KYB_RISK_MODEL_VERSIONS).create_index("active")
    await col(KYB_REGISTRY_REVIEWS).create_index(
        [("case_id", 1), ("field", 1)], unique=True)

    # F8 — team invitations (shared_links ya tiene índices arriba)
    from .models import KYB_TEAM_INVITATIONS
    await col(KYB_TEAM_INVITATIONS).create_index("token_hash", unique=True)
    await col(KYB_TEAM_INVITATIONS).create_index(
        [("case_id", 1), ("status", 1)])
    await col(KYB_TEAM_INVITATIONS).create_index("email")
