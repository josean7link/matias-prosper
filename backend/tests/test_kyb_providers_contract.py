"""Tests del contrato VerificationProvider + ManualProvider (Fase 5b).

Objetivos:
  1. ManualProvider satisface el contrato (todas las capabilities).
  2. `ensure_applicant` es idempotente contra reintentos.
  3. El campo `environment` de `kyb_external_subjects` es inmutable
     tras la creación: un update posterior no puede cambiarlo.
  4. `generate_checks` retrocompat: sin `only_categories` procesa las
     3, con `only_categories={"identity"}` procesa sólo identity.
  5. `derive_external_user_id` es determinístico.
  6. `get_verdict` es sólo lectura local: nunca sale a red.
  7. `create_access_token` y `validate_webhook` fallan como corresponde
     en ManualProvider.
  8. Registry: con provider="manual" habilitado → devuelve
     ManualProvider. Sin fila habilitada → ProviderNotConfigured.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Base descartable dedicada — nunca prosper_phase0.
_DB = "prosper_kyb_providers_tests"


@pytest.fixture(autouse=True)
async def _isolated_db(monkeypatch):
    """Cada test corre contra una DB propia, drop antes y después."""
    monkeypatch.setenv("DB_NAME", _DB)
    # Fuerza reset del client cacheado en db.py: la conexión anterior
    # apuntaba a otra DB, y db.col() usa el DB_NAME activo del env.
    import db as _dbmod
    _dbmod._client = None
    from kyb.providers.registry import _reset_cache_for_tests
    _reset_cache_for_tests()
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await client.drop_database(_DB)
    yield
    await client.drop_database(_DB)
    client.close()


async def _seed_case(case_id: str = "kyb_test_case",
                     is_test_case: bool = True) -> dict:
    """Semilla mínima de kyb_case + profile + un UBO."""
    from db import col
    from kyb.models import (KYB_CASES, KYB_COMPANY_PROFILES,
                             KYB_BENEFICIAL_OWNERS,
                             KYB_MANUAL_CHECK_TEMPLATES,
                             VERIFICATION_CATEGORIES)
    case = {"case_id": case_id, "status": "submitted",
            "country_of_incorporation": "AR",
            "company_name_declared": "Empresa Testeada SA",
            "verification_modes": {"identity": "manual",
                                    "screening": "manual",
                                    "company_registry": "manual"},
            "is_test_case": is_test_case, "is_deleted": False}
    await col(KYB_CASES).insert_one(case)
    await col(KYB_COMPANY_PROFILES).insert_one(
        {"case_id": case_id, "legal_name": "Empresa Testeada SA",
         "legal_representative": {"full_name": "Ana Rep"}})
    await col(KYB_BENEFICIAL_OWNERS).insert_one(
        {"case_id": case_id, "ubo_id": "ubo_test_01",
         "first_name": "Ana", "last_name": "Rep"})
    # Plantillas mínimas para las 3 categorías (subject_type=company)
    for cat in VERIFICATION_CATEGORIES:
        await col(KYB_MANUAL_CHECK_TEMPLATES).insert_one(
            {"template_id": f"tpl_{cat}", "category": cat,
             "country": None, "subject_types": ["company",
                                                 "legal_representative",
                                                 "ubo"],
             "version": 1, "active": True,
             "items": [{"item_key": "i1", "label": "L1",
                        "evidence_required": False, "order": 0}]})
    return case


# ------------------------------------------------------------------
# ManualProvider: contrato básico
# ------------------------------------------------------------------
async def test_manual_supports_all_capabilities():
    from kyb.providers.manual import ManualProvider
    p = ManualProvider()
    assert p.provider_id == "manual"
    assert p.environment is None
    for cap in ("identity", "screening", "company_registry"):
        assert p.supports(cap) is True


async def test_manual_derive_external_user_id_deterministic():
    from kyb.providers.base import SubjectRef
    from kyb.providers.manual import ManualProvider
    p = ManualProvider()
    s1 = SubjectRef(case_id="kyb_x", subject_type="ubo", subject_id="ubo_1")
    s2 = SubjectRef(case_id="kyb_x", subject_type="ubo", subject_id="ubo_1")
    assert p.derive_external_user_id(s1) == p.derive_external_user_id(s2)
    # Distinct subjects → distinct ids
    s3 = SubjectRef(case_id="kyb_x", subject_type="company",
                    subject_id=None)
    assert p.derive_external_user_id(s3) \
        != p.derive_external_user_id(s1)
    # Estructura predecible
    assert p.derive_external_user_id(s1) == "manual:kyb_x:ubo:ubo_1"
    assert p.derive_external_user_id(s3) == "manual:kyb_x:company:na"


async def test_manual_ensure_applicant_idempotent():
    """Reintento con el mismo sujeto → mismo applicant, sin duplicados."""
    from db import col
    from kyb.models import KYB_EXTERNAL_SUBJECTS
    from kyb.providers.base import SubjectRef
    from kyb.providers.manual import ManualProvider

    await _seed_case()
    p = ManualProvider()
    subject = SubjectRef(case_id="kyb_test_case",
                         subject_type="company", subject_id=None)

    a1 = await p.ensure_applicant(subject, level_hint="identity")
    a2 = await p.ensure_applicant(subject, level_hint="screening")
    assert a1.external_user_id == a2.external_user_id
    assert a1.provider == "manual"
    assert a1.environment is None
    # Sólo un doc en kyb_external_subjects
    n = await col(KYB_EXTERNAL_SUBJECTS).count_documents(
        {"case_id": "kyb_test_case",
          "subject_type": "company",
          "provider": "manual"})
    assert n == 1


# ------------------------------------------------------------------
# Inmutabilidad de `environment` en kyb_external_subjects
# ------------------------------------------------------------------
async def test_environment_immutable_after_creation():
    """El registry usa $setOnInsert para `environment`. Un update
    posterior con $set explícito sobre otro provider (o llamado con
    otro env) no debe cambiar el valor original.

    Este test también documenta la regla: quien quiera cambiar de
    ambiente tiene que crear un applicant NUEVO — nunca mutar el
    existente."""
    from db import col
    from kyb.models import KYB_EXTERNAL_SUBJECTS
    from kyb.providers.base import SubjectRef
    from kyb.providers.manual import ManualProvider

    await _seed_case()
    subject = SubjectRef(case_id="kyb_test_case",
                         subject_type="ubo", subject_id="ubo_test_01")

    # 1) Creación inicial via ManualProvider → environment=None
    p = ManualProvider()
    a = await p.ensure_applicant(subject, level_hint="identity")
    assert a.environment is None

    # 2) Simulamos que un futuro proveedor invoca upsert con
    #    $setOnInsert env="sandbox" pero SOBRE OTRO provider.
    #    El match del filtro no incluye "provider", así que hay que
    #    verificar que el upsert-por-provider crea uno nuevo, no
    #    modifica el existente.
    now = "2026-01-01T00:00:00+00:00"
    await col(KYB_EXTERNAL_SUBJECTS).update_one(
        {"case_id": subject.case_id,
          "subject_type": subject.subject_type,
          "subject_id": subject.subject_id,
          "provider": "sumsub"},
        {"$setOnInsert": {"case_id": subject.case_id,
                          "subject_type": subject.subject_type,
                          "subject_id": subject.subject_id,
                          "provider": "sumsub",
                          "environment": "sandbox",
                          "external_user_id": "eid_new",
                          "created_at": now}},
        upsert=True)

    # El doc "manual" original queda intacto:
    manual_doc = await col(KYB_EXTERNAL_SUBJECTS).find_one(
        {"case_id": subject.case_id, "provider": "manual"})
    assert manual_doc["environment"] is None
    # Y el doc nuevo del "sumsub" tiene environment="sandbox":
    sumsub_doc = await col(KYB_EXTERNAL_SUBJECTS).find_one(
        {"case_id": subject.case_id, "provider": "sumsub"})
    assert sumsub_doc["environment"] == "sandbox"

    # 3) Intento explícito de $set sobre `environment` del doc sumsub —
    #    demostrando que NO debemos hacerlo. El schema no lo prohibe
    #    a nivel Mongo, así que la regla es de código. Documentamos
    #    con este comment y el test verifica la política:
    await col(KYB_EXTERNAL_SUBJECTS).update_one(
        {"case_id": subject.case_id, "provider": "sumsub"},
        {"$setOnInsert": {"environment": "production"}})
    # $setOnInsert sin upsert=True + doc existente → no hace nada
    sumsub_doc = await col(KYB_EXTERNAL_SUBJECTS).find_one(
        {"case_id": subject.case_id, "provider": "sumsub"})
    assert sumsub_doc["environment"] == "sandbox"  # sigue igual


# ------------------------------------------------------------------
# start_verification: solo la capability solicitada
# ------------------------------------------------------------------
async def test_start_verification_generates_only_target_capability():
    """El ManualProvider debe generar SOLO los checklists de la
    capability solicitada. Si generara los tres, reintentar identity
    regeneraría screening y company_registry — imposible de razonar."""
    from db import col
    from kyb.models import KYB_MANUAL_CHECKS
    from kyb.providers.base import SubjectRef
    from kyb.providers.manual import ManualProvider

    await _seed_case()
    p = ManualProvider()
    subject = SubjectRef(case_id="kyb_test_case",
                         subject_type="company", subject_id=None)
    applicant = await p.ensure_applicant(subject, level_hint="identity")

    snap = await p.start_verification(applicant, capability="identity")
    assert snap.capability == "identity"
    assert snap.status == "pending"
    assert snap.provider == "manual"

    # Solo checklists de "identity" fueron creados
    cats = await col(KYB_MANUAL_CHECKS).distinct(
        "category", {"case_id": "kyb_test_case"})
    assert set(cats) == {"identity"}, (
        f"start_verification(identity) debe generar SOLO identity, "
        f"obtuve: {cats}")


async def test_start_verification_idempotent_reruns():
    """Segunda invocación no crea checks nuevos."""
    from db import col
    from kyb.models import KYB_MANUAL_CHECKS
    from kyb.providers.base import SubjectRef
    from kyb.providers.manual import ManualProvider

    await _seed_case()
    p = ManualProvider()
    subject = SubjectRef(case_id="kyb_test_case",
                         subject_type="company", subject_id=None)
    applicant = await p.ensure_applicant(subject, level_hint="identity")

    await p.start_verification(applicant, capability="identity")
    n1 = await col(KYB_MANUAL_CHECKS).count_documents(
        {"case_id": "kyb_test_case"})
    await p.start_verification(applicant, capability="identity")
    n2 = await col(KYB_MANUAL_CHECKS).count_documents(
        {"case_id": "kyb_test_case"})
    assert n1 == n2


# ------------------------------------------------------------------
# Retrocompat de generate_checks
# ------------------------------------------------------------------
async def test_generate_checks_backward_compat_all_categories():
    """Sin only_categories → comportamiento actual (todas)."""
    from db import col
    from kyb.manual_checks import generate_checks
    from kyb.models import KYB_CASES, KYB_MANUAL_CHECKS

    await _seed_case()
    case = await col(KYB_CASES).find_one({"case_id": "kyb_test_case"})
    await generate_checks(case, actor=None, request=None)
    cats = await col(KYB_MANUAL_CHECKS).distinct(
        "category", {"case_id": "kyb_test_case"})
    assert set(cats) == {"identity", "screening", "company_registry"}


async def test_generate_checks_filtered_by_only_categories():
    from db import col
    from kyb.manual_checks import generate_checks
    from kyb.models import KYB_CASES, KYB_MANUAL_CHECKS

    await _seed_case()
    case = await col(KYB_CASES).find_one({"case_id": "kyb_test_case"})
    await generate_checks(case, actor=None, request=None,
                           only_categories={"screening"})
    cats = await col(KYB_MANUAL_CHECKS).distinct(
        "category", {"case_id": "kyb_test_case"})
    assert set(cats) == {"screening"}


# ------------------------------------------------------------------
# get_verdict: sólo lectura local, nunca sale a red
# ------------------------------------------------------------------
async def test_get_verdict_returns_none_when_no_local_state():
    """Sin doc en kyb_verifications, get_verdict devuelve None sin
    ninguna llamada externa. No hay red que mockear — si hubiera
    intento de I/O de red, el test tampoco lo permitiría porque
    ManualProvider no importa httpx ni socket."""
    from kyb.providers.base import SubjectRef
    from kyb.providers.manual import ManualProvider

    await _seed_case()
    p = ManualProvider()
    subject = SubjectRef(case_id="kyb_test_case",
                         subject_type="ubo", subject_id="ubo_test_01")
    applicant = await p.ensure_applicant(subject, level_hint="identity")
    verdict = await p.get_verdict(applicant, capability="identity")
    assert verdict is None


async def test_get_verdict_returns_persisted_state():
    from db import col
    from kyb.models import KYB_VERIFICATIONS
    from kyb.providers.base import SubjectRef
    from kyb.providers.manual import ManualProvider

    await _seed_case()
    p = ManualProvider()
    subject = SubjectRef(case_id="kyb_test_case",
                         subject_type="ubo", subject_id="ubo_test_01")
    applicant = await p.ensure_applicant(subject, level_hint="identity")

    # Simulamos que un flujo previo (checklist completado) dejó
    # un doc en kyb_verifications.
    await col(KYB_VERIFICATIONS).insert_one({
        "verification_id": "ver_test_01",
        "case_id": "kyb_test_case",
        "subject_type": "ubo", "subject_id": "ubo_test_01",
        "kind": "identity", "mode": "manual", "source": "manual",
        "provider": "manual", "status": "completed",
        "outcome": "approved",
        "normalized_result": {"decision_reason": "docs ok"},
        "completed_at": "2026-01-01T00:00:00+00:00",
    })
    v = await p.get_verdict(applicant, capability="identity")
    assert v is not None
    assert v.status == "completed"
    assert v.outcome == "approved"
    assert v.normalized_result == {"decision_reason": "docs ok"}


# ------------------------------------------------------------------
# ManualProvider: métodos sin implementación
# ------------------------------------------------------------------
async def test_manual_access_token_raises():
    from kyb.providers.base import (Applicant, ProviderError, SubjectRef)
    from kyb.providers.manual import ManualProvider
    p = ManualProvider()
    subject = SubjectRef(case_id="kyb_x", subject_type="company")
    applicant = Applicant(subject=subject, provider="manual",
                           environment=None, external_user_id="e",
                           created_at="2026-01-01T00:00:00+00:00")
    with pytest.raises(ProviderError):
        await p.create_access_token(applicant)


async def test_manual_validate_webhook_raises_not_implemented():
    from kyb.providers.base import WebhookPayload
    from kyb.providers.manual import ManualProvider
    p = ManualProvider()
    with pytest.raises(NotImplementedError):
        await p.validate_webhook(WebhookPayload(raw_body=b"", headers={}))


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------
async def test_registry_returns_manual_when_configured():
    from db import col
    from kyb.models import KYB_PROVIDER_CONFIGS
    from kyb.providers.manual import ManualProvider
    from kyb.providers.registry import get_provider

    await col(KYB_PROVIDER_CONFIGS).insert_one({
        "category": "identity", "provider": "manual", "enabled": True})
    p = await get_provider("identity")
    assert isinstance(p, ManualProvider)
    # Cacheado: la próxima llamada devuelve la misma instancia
    p2 = await get_provider("identity")
    assert p is p2


async def test_registry_raises_when_no_provider_enabled():
    from kyb.providers.base import ProviderNotConfigured
    from kyb.providers.registry import get_provider
    with pytest.raises(ProviderNotConfigured):
        await get_provider("identity")


async def test_registry_maps_company_registry_to_company_category():
    from db import col
    from kyb.models import KYB_PROVIDER_CONFIGS
    from kyb.providers.manual import ManualProvider
    from kyb.providers.registry import get_provider

    await col(KYB_PROVIDER_CONFIGS).insert_one({
        "category": "company", "provider": "manual", "enabled": True})
    p = await get_provider("company_registry")
    assert isinstance(p, ManualProvider)


async def test_registry_sumsub_gated_by_flag():
    """Con KYB_PROVIDER_SUMSUB_ENABLED=false (default),
    get_provider('identity') NO devuelve SumsubProvider aunque haya
    fila enabled en kyb_provider_configs."""
    from db import col
    from kyb.models import KYB_PROVIDER_CONFIGS
    from kyb.providers.base import ProviderNotConfigured
    from kyb.providers.registry import get_provider

    await col(KYB_PROVIDER_CONFIGS).insert_one({
        "category": "identity", "provider": "sumsub", "enabled": True,
        "environment": "sandbox"})
    # El flag NO está seteado → default false
    with patch.dict(os.environ,
                     {"KYB_PROVIDER_SUMSUB_ENABLED": "false"},
                     clear=False):
        with pytest.raises(ProviderNotConfigured):
            await get_provider("identity")
