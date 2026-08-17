"""Modelos y enums del módulo KYB (Fase 1).

Convenciones heredadas del repo (`backend/models.py`):
  * timestamps como strings ISO-8601 UTC timezone-aware (`utc_now()`).
  * ids con prefijo + uuid4().hex[:12].
Única excepción: `kyb_provider_calls.created_at` es BSON Date porque el
índice TTL de Mongo solo funciona sobre Date.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from models import utc_now

# ---------------------------------------------------------------------------
# Nombres de colecciones (todas prefijo kyb_)
# ---------------------------------------------------------------------------
KYB_CASES              = "kyb_cases"           # existente — se extiende
KYB_COMPANY_PROFILES   = "kyb_company_profiles"
KYB_BENEFICIAL_OWNERS  = "kyb_beneficial_owners"
KYB_DOCUMENTS          = "kyb_documents"
KYB_EXTERNAL_SUBJECTS  = "kyb_external_subjects"
KYB_VERIFICATIONS      = "kyb_verifications"
KYB_SCREENING_HITS     = "kyb_screening_hits"
KYB_SHARED_LINKS       = "kyb_shared_links"
KYB_PROVIDER_CONFIGS   = "kyb_provider_configs"
KYB_RISK_MODEL         = "kyb_risk_model"
KYB_PROVIDER_CALLS     = "kyb_provider_calls"
KYB_TEAM_INVITATIONS   = "kyb_team_invitations"      # F8 — invitaciones de equipo
KYB_RISK_MODEL_VERSIONS = "kyb_risk_model_versions"  # F7 — historial versionado
KYB_REGISTRY_REVIEWS   = "kyb_registry_reviews"      # F7 — revisión campo a campo

# ---------------------------------------------------------------------------
# Enums / vocabularios
# ---------------------------------------------------------------------------
PURPOSES = ["YIELD_ARS", "YIELD_USD", "EMBEDDED_EARN",
            "CORPORATE_TREASURY", "OTHER"]
FUNDS_ORIGIN_TYPES = ["OWN_TREASURY", "CLIENT_FUNDS", "MIXED"]
FUNDS = ["PROSPER_ARS", "PROSPER_USD"]
LEGAL_STRUCTURES = ["SA", "SRL", "SAS", "SAU", "COOPERATIVA",
                    "ASOCIACION_CIVIL", "OTRA"]

CASE_STATUSES = ["draft", "in_progress", "submitted", "screening",
                 "under_review", "info_required", "approved", "rejected",
                 "expired"]
PRIORITIES = ["normal", "critical"]
REOPEN_REASONS = ["periodic_review", "provider_alert", "admin"]
SECTION_KEYS = ["tax_identification", "legal_representative",
                "company_data", "documentation", "team"]
SECTION_STATUSES = ["pending", "completed", "observed", "resubmitted"]

DOCUMENT_SLOTS = ["tax_registration_certificate", "constitutive_document",
                  "funds_origin_evidence", "authorities_appointment",
                  "company_proof_of_address", "ubo_document_front",
                  "ubo_document_back", "manual_check_evidence", "additional"]

VERIFICATION_KINDS = ["identity", "screening", "company_registry"]
VERIFICATION_MODES = ["manual", "automatic"]
VERIFICATION_STATUSES = ["pending", "in_progress", "completed", "failed",
                         "not_configured"]
SUBJECT_TYPES = ["company", "legal_representative", "ubo"]
CONTROL_TYPES = ["OWNERSHIP", "CONTROL_BODY"]
UPLOAD_VIAS = ["owner", "shared_link"]
PROVIDER_CATEGORIES = ["identity", "screening", "company"]


def new_case_id() -> str:
    return f"kyb_{uuid.uuid4().hex[:12]}"


def new_subject_ref() -> str:
    return f"sub_{uuid.uuid4().hex[:12]}"


def _new(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class KybTimestamps(BaseModel):
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# kyb_cases
# ---------------------------------------------------------------------------
class SectionState(BaseModel):
    status: Literal["pending", "completed", "observed",
                    "resubmitted"] = "pending"
    completed_at: Optional[str] = None
    observation: Optional[str] = None
    observed_by: Optional[str] = None
    observed_at: Optional[str] = None


def default_sections() -> Dict[str, dict]:
    return {k: SectionState().model_dump() for k in SECTION_KEYS}


class VerificationModes(BaseModel):
    identity: str = "manual"
    screening: str = "manual"
    company_registry: str = "manual"


class RiskState(BaseModel):
    model_config = {"protected_namespaces": ()}

    level: Optional[str] = None
    score: Optional[float] = None
    factors: List[dict] = []
    model_version: Optional[str] = None
    computed_at: Optional[str] = None
    override: Optional[dict] = None


class Resolution(BaseModel):
    decision: str
    reason_code: Optional[str] = None
    notes: Optional[str] = None
    by: Optional[str] = None
    second_approver: Optional[str] = None


class LegacyOrigin(BaseModel):
    source_id: str
    migrated_at: str
    original_status: Optional[str] = None


class ApplicantPhone(BaseModel):
    country_code: Optional[str] = None
    number: Optional[str] = None


class KybCase(KybTimestamps):
    case_id: str = Field(default_factory=new_case_id)
    org_id: Optional[str] = None
    status: str = "draft"
    priority: Literal["normal", "critical"] = "normal"
    country_of_incorporation: Optional[str] = None   # ISO-3166 alpha-2
    applicant_email: Optional[str] = None            # inmutable tras crear
    applicant_name: Optional[str] = None
    applicant_phone: Optional[ApplicantPhone] = None
    company_name_declared: Optional[str] = None
    sections: Dict[str, SectionState] = Field(
        default_factory=lambda: {k: SectionState() for k in SECTION_KEYS})
    verification_modes: VerificationModes = Field(
        default_factory=VerificationModes)
    risk: Optional[RiskState] = None
    reopen_reason: Optional[Literal["periodic_review", "provider_alert",
                                    "admin"]] = None
    assigned_to: Optional[str] = None
    submitted_at: Optional[str] = None
    resolved_at: Optional[str] = None
    next_review_at: Optional[str] = None
    expires_at: Optional[str] = None
    resolution: Optional[Resolution] = None
    # DDJJ vigente del cuadro societario; None si fue invalidada por una
    # mutación posterior. El historial conserva cada acknowledgment con
    # qué cambio lo invalidó (Fase 4).
    ubo_confirmation: Optional[dict] = None
    ubo_confirmation_history: List[dict] = []
    suspended: Optional[dict] = None                 # {at, by, reason}
    legacy_origin: Optional[LegacyOrigin] = None
    is_deleted: bool = False
    # Fase 5b — marca de caso de prueba. Cuando True, sólo puede
    # asociarse con applicants en `environment="sandbox"`. Cuando False,
    # sólo con `environment="production"`. Inmutable operacionalmente
    # (el backoffice no expone endpoint para cambiarlo).
    is_test_case: bool = False


# ---------------------------------------------------------------------------
# kyb_company_profiles
# ---------------------------------------------------------------------------
class LegalAcceptance(BaseModel):
    document_key: str
    version: str
    content_hash: str
    accepted_at: str
    ip: Optional[str] = None
    user_agent: Optional[str] = None


class LegalRepresentative(BaseModel):
    country_of_residence: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    tax_id: Optional[str] = None                      # CUIT/CUIL normalizado


class RegisteredAddress(BaseModel):
    raw: Optional[str] = None
    street: Optional[str] = None
    number: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class Operations(BaseModel):
    estimated_monthly_volume_usd: Optional[float] = None
    purposes: List[str] = []
    purpose_other: Optional[str] = None
    funds_subscribed: List[str] = []


class FundsOrigin(BaseModel):
    type: Optional[str] = None                        # FUNDS_ORIGIN_TYPES
    client_funds_ratio: Optional[float] = None
    license_type: Optional[str] = None
    license_number: Optional[str] = None
    has_aml_policy: Optional[bool] = None
    compliance_officer_name: Optional[str] = None
    end_user_kyc_description: Optional[str] = None
    segregated_assets: Optional[bool] = None


class KybCompanyProfile(KybTimestamps):
    case_id: str
    tax_id: Optional[str] = None
    tax_id_locked: bool = False
    legal_acceptances: List[LegalAcceptance] = []
    legal_representative: Optional[LegalRepresentative] = None
    legal_name: Optional[str] = None
    legal_structure: Optional[str] = None             # LEGAL_STRUCTURES
    legal_structure_other: Optional[str] = None
    activity_description: Optional[str] = None
    registration_number: Optional[str] = None
    registration_date: Optional[str] = None
    website: Optional[str] = None
    registered_address: Optional[RegisteredAddress] = None
    operations: Optional[Operations] = None
    funds_origin: Optional[FundsOrigin] = None
    is_uif_obliged_subject: Optional[bool] = None
    uif_registration_number: Optional[str] = None
    tax_residences: List[dict] = []
    fatca_crs: Optional[dict] = None
    recently_incorporated_declared: Optional[bool] = None


# ---------------------------------------------------------------------------
# kyb_beneficial_owners
# ---------------------------------------------------------------------------
class KybBeneficialOwner(KybTimestamps):
    ubo_id: str = Field(default_factory=lambda: _new("ubo"))
    case_id: str
    control_type: Literal["OWNERSHIP", "CONTROL_BODY"] = "OWNERSHIP"
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    birth_date: Optional[str] = None
    nationality: Optional[str] = None
    address: Optional[str] = None
    marital_status: Optional[str] = None
    profession: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    document_number: Optional[str] = None
    tax_id: Optional[str] = None
    ownership_percentage: Optional[float] = None
    relationship_start_date: Optional[str] = None
    is_obliged_subject: Optional[bool] = None
    is_pep: Optional[bool] = None
    document_front_id: Optional[str] = None
    document_back_id: Optional[str] = None
    # Vínculo declarativo por coincidencia de tax_id con el representante
    # legal — no fusiona datos: permite al orquestador reutilizar el mismo
    # sujeto externo (un solo applicant por persona).
    is_also_legal_representative: bool = False
    screening_status: Optional[str] = None
    identity_status: Optional[str] = None


# ---------------------------------------------------------------------------
# kyb_documents
# ---------------------------------------------------------------------------
class KybDocument(KybTimestamps):
    document_id: str = Field(default_factory=lambda: _new("doc"))
    case_id: str
    slot: str                                         # DOCUMENT_SLOTS
    version: int = 1                                  # incremental por slot
    is_current: bool = True
    filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    storage_key: Optional[str] = None                 # capa Fase 0.5
    sha256: Optional[str] = None
    description: Optional[str] = None
    uploaded_by: Optional[str] = None
    uploaded_via: Literal["owner", "shared_link"] = "owner"
    shared_link_id: Optional[str] = None
    ubo_id: Optional[str] = None                      # solo slots ubo_*
    check_id: Optional[str] = None                    # solo manual_check_evidence
    # Evidencia descartada: NO se borra (trazabilidad) — queda marcada,
    # no satisface requisitos de ítems y en la exportación (F7) va en
    # sección aparte. {at, by, reason}
    discarded: Optional[dict] = None


# ---------------------------------------------------------------------------
# kyb_external_subjects
# ---------------------------------------------------------------------------
class KybExternalSubject(KybTimestamps):
    subject_ref: str = Field(default_factory=new_subject_ref)
    case_id: str
    subject_type: Literal["company", "legal_representative", "ubo"]
    subject_id: Optional[str] = None
    provider: Optional[str] = None
    # Fase 5b — ambiente del proveedor donde vive este applicant.
    # "sandbox" | "production" | None (manual). INMUTABLE tras la
    # creación: el registry usa `$setOnInsert` en el upsert, nunca `$set`.
    # Regla de coherencia:
    #   - kyb_cases.is_test_case=False ↔ environment="production"
    #   - kyb_cases.is_test_case=True  ↔ environment="sandbox"
    #   - manual                        ↔ environment=None
    environment: Optional[str] = None
    external_user_id: Optional[str] = None
    provider_applicant_id: Optional[str] = None
    level_name: Optional[str] = None
    review_status: Optional[str] = None
    review_answer: Optional[str] = None
    review_reject_type: Optional[str] = None
    moderation_comment: Optional[str] = None
    client_comment: Optional[str] = None
    reject_labels: List[str] = []
    last_webhook_at: Optional[str] = None
    last_synced_at: Optional[str] = None


# ---------------------------------------------------------------------------
# kyb_verifications
# ---------------------------------------------------------------------------
class KybVerification(KybTimestamps):
    verification_id: str = Field(default_factory=lambda: _new("ver"))
    case_id: str
    subject_ref: Optional[str] = None
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    kind: Literal["identity", "screening", "company_registry"]
    mode: Literal["manual", "automatic"] = "manual"
    source: Literal["provider", "manual"] = "manual"
    performed_by: Optional[str] = None
    provider: Optional[str] = None
    provider_reference: Optional[str] = None
    status: Literal["pending", "in_progress", "completed", "failed",
                    "not_configured"] = "pending"
    outcome: Optional[str] = None
    normalized_result: Optional[dict] = None
    raw_response_ref: Optional[str] = None            # puntero a storage
    requested_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    # Fase 5b — idempotencia + ordenamiento del webhook receiver.
    # `provider_event_id`: llave junto con `provider_reference` (el
    # applicant_id) para deduplicar. `provider_event_ts` para descartar
    # eventos fuera de orden por applicant.
    provider_event_id: Optional[str] = None
    provider_event_ts: Optional[str] = None


# ---------------------------------------------------------------------------
# kyb_screening_hits
# ---------------------------------------------------------------------------
class KybScreeningHit(KybTimestamps):
    hit_id: str = Field(default_factory=lambda: _new("hit"))
    case_id: str
    verification_id: Optional[str] = None
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None
    list_type: Optional[str] = None
    list_name: Optional[str] = None
    matched_name: Optional[str] = None
    match_score: Optional[float] = None
    is_blocking: bool = False
    details: Optional[dict] = None
    source: Literal["provider", "manual"] = "manual"
    detected_after_approval: bool = False
    provider_hit_id: Optional[str] = None
    resolution: Optional[dict] = None
    provider_sync: Optional[dict] = None


# ---------------------------------------------------------------------------
# kyb_shared_links
# ---------------------------------------------------------------------------
class KybSharedLink(KybTimestamps):
    link_id: str = Field(default_factory=lambda: _new("lnk"))
    case_id: str
    token_hash: str                                   # SHA-256; nunca el claro
    scope: List[str] = []
    created_by: Optional[str] = None
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    last_used_at: Optional[str] = None
    use_count: int = 0


# ---------------------------------------------------------------------------
# kyb_provider_configs
# ---------------------------------------------------------------------------
class KybProviderConfig(KybTimestamps):
    category: Literal["identity", "screening", "company"]
    provider: str
    enabled: bool = False
    environment: Optional[str] = None
    credentials_encrypted: Optional[str] = None       # secret_box (Fase 0.5)
    credentials_last4: Optional[str] = None
    settings: Dict[str, Any] = {}
    last_health_check: Optional[dict] = None
    updated_by: Optional[str] = None


# ---------------------------------------------------------------------------
# kyb_risk_model — documento único versionado
# ---------------------------------------------------------------------------
class KybRiskModel(KybTimestamps):
    version: int = 1
    active: bool = False                              # F7 — solo una activa
    factors: List[dict] = []
    thresholds: Dict[str, Any] = {}
    review_months: Dict[str, int] = {}
    updated_by: Optional[str] = None


# ---------------------------------------------------------------------------
# kyb_provider_calls — telemetría, TTL 30 días (created_at es BSON Date)
# ---------------------------------------------------------------------------
class KybProviderCall(BaseModel):
    provider: str
    direction: Literal["outbound", "webhook"]
    endpoint: Optional[str] = None
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    ok: Optional[bool] = None
    error_code: Optional[str] = None
    signature_valid: Optional[bool] = None


# ---------------------------------------------------------------------------
# Fase 5a — modos de verificación + checklists manuales
# ---------------------------------------------------------------------------
KYB_VERIFICATION_MODES     = "kyb_verification_modes"
KYB_MANUAL_CHECK_TEMPLATES = "kyb_manual_check_templates"
KYB_MANUAL_CHECKS          = "kyb_manual_checks"

VERIFICATION_CATEGORIES = ["identity", "screening", "company_registry"]
CATEGORY_MODES = ["manual", "automatic", "mock"]
# Estados de verificación por categoría de un caso. Los tres estados de
# caída (failed/inconclusive/not_found) generan checklist manual (5b).
CATEGORY_STATES = ["manual", "automatic", "automatic_pending_result",
                   "automatic_failed", "automatic_inconclusive",
                   "automatic_not_found", "manual_forced", "not_configured"]
CHECK_TRIGGERS = ["mode_manual", "fallback_failed", "fallback_inconclusive",
                  "fallback_not_found", "forced_by_admin"]
CHECK_STATUSES = ["pending", "in_progress", "completed"]


class TemplateItem(BaseModel):
    item_key: str
    label: str
    description: str = ""
    source_url: Optional[str] = None
    evidence_required: bool = False
    # F7 — un hit en este ítem bloquea la aprobación por default.
    # El analista puede promover/despromover un hit puntual desde
    # Screening (auditado).
    blocks_on_hit: bool = False
    possible_outcomes: List[str] = []
    order: int = 0


class KybManualCheckTemplate(KybTimestamps):
    template_id: str
    category: Literal["identity", "screening", "company_registry"]
    country: Optional[str] = None          # None = aplica a todos
    subject_types: List[str] = []          # company|legal_representative|ubo
    version: int = 1
    active: bool = True
    items: List[TemplateItem] = []
    updated_by: Optional[str] = None


class CheckItem(BaseModel):
    item_key: str
    label: str
    description: Optional[str] = None      # copiado del template (render)
    source_url: Optional[str] = None
    evidence_required: bool = False
    blocks_on_hit: bool = False            # F7 — copiado del template
    possible_outcomes: List[str] = []
    order: int = 0
    outcome: Optional[str] = None
    notes: Optional[str] = None
    evidence_document_ids: List[str] = []
    completed_by: Optional[str] = None
    completed_at: Optional[str] = None


class KybManualCheck(KybTimestamps):
    check_id: str = Field(default_factory=lambda: _new("chk"))
    case_id: str
    category: Literal["identity", "screening", "company_registry"]
    subject_type: Literal["company", "legal_representative", "ubo"]
    subject_id: str
    subject_name: Optional[str] = None
    template_id: str
    template_version: int
    status: Literal["pending", "in_progress", "completed"] = "pending"
    trigger: Literal["mode_manual", "fallback_failed",
                     "fallback_inconclusive", "fallback_not_found",
                     "forced_by_admin"] = "mode_manual"
    items: List[CheckItem] = []
    contributors: List[str] = []           # base del maker-checker
    completed_by: Optional[str] = None
    completed_at: Optional[str] = None
