"""VerificationProvider — contrato del proveedor de verificación KYB.

Sigue el patrón de `services/storage/backend.py`: ABC + tipos compartidos
en un solo archivo, implementaciones en archivos separados del mismo
paquete (`manual.py`, `sumsub.py`).

El contrato se expresa en términos del dominio Prosper, no de un
proveedor particular. Producir resultados normalizados: los shapes
mapean 1:1 a lo que `kyb_verifications` y `kyb_screening_hits` ya
guardan hoy (ver `kyb/models.py:328` y `kyb/models.py:353`)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional


# ---------------------------------------------------------------------------
# Errores tipados. El orquestador (`_dispatch_category`) captura Exception
# y devuelve ok=False; estos tipos permiten al receptor de webhooks y al
# backoffice distinguir causas puntuales.
# ---------------------------------------------------------------------------
class ProviderError(RuntimeError):
    """Base de cualquier fallo del proveedor. Nunca se serializa hacia el
    cliente HTTP externo — el orquestador la log-and-drops via
    `log_action`."""


class ProviderNotConfigured(ProviderError):
    """Faltan credenciales o el proveedor está deshabilitado (enabled=False
    en `kyb_provider_configs`)."""


class ProviderEnvironmentMismatch(ProviderError):
    """El sujeto/applicant referenciado pertenece a un ambiente distinto
    del que declara el caso (`kyb_cases.is_test_case` vs
    `kyb_external_subjects.environment`), o del ambiente activo global
    (`SUMSUB_ENVIRONMENT`). El receptor de webhooks lo traduce a HTTP
    409."""


class ProviderSignatureInvalid(ProviderError):
    """HMAC del webhook no valida. El mensaje es genérico por diseño:
    nunca debe incluir fragmentos de la firma recibida ni de la
    esperada. El detalle del mismatch va al log interno vía
    `logger.warning`. El receptor de webhooks lo traduce a HTTP 401."""


class ProviderTransientError(ProviderError):
    """Fallos recuperables (5xx del proveedor, timeouts). El caller puede
    reintentar; el estado del caso queda `in_progress`."""


# ---------------------------------------------------------------------------
# Vocabulario del dominio — mapea 1:1 a `kyb_verifications`.
# ---------------------------------------------------------------------------
SubjectType = Literal["company", "legal_representative", "ubo"]
Capability = Literal["identity", "screening", "company_registry"]
Environment = Literal["sandbox", "production"]

VerificationStatus = Literal["pending", "in_progress", "completed",
                             "failed", "not_configured"]

VerificationOutcome = Literal[
    "approved",           # sujeto verificado sin observaciones
    "approved_with_hits", # aprobado pero con hits de screening no bloqueantes
    "rejected",           # sujeto rechazado por el proveedor
    "inconclusive",       # provider no puede decidir
    "not_found",          # company_registry: entidad no existe
    "pending_review",     # el analista debe intervenir
]


@dataclass(frozen=True)
class SubjectRef:
    """Identidad canónica de un sujeto verificable dentro de un caso.
    Alineado con `kyb_verifications.subject_type/subject_id`.

    `subject_id` es opcional: para `company` y `legal_representative` no
    hay id externo (se derivan del caso), sólo `ubo` tiene ubo_id."""
    case_id: str
    subject_type: SubjectType
    subject_id: Optional[str] = None


@dataclass
class Applicant:
    """Persistente del proveedor. Se guarda en `kyb_external_subjects`.

    Campos:
      - `provider`: "manual" o "sumsub" (o los que vengan). Se persiste
        en `kyb_external_subjects.provider`.
      - `environment`: "sandbox" | "production" | None (None para
        ManualProvider — no aplica). INMUTABLE tras la creación: el
        registry usa `$setOnInsert` en el upsert, nunca `$set`.
      - `external_user_id`: determinístico, derivado del caso y del
        sujeto (nunca aleatorio). Idempotente frente a reintentos.
      - `provider_applicant_id`: el id que asigna el proveedor externo.
        None para ManualProvider."""
    subject: SubjectRef
    provider: str
    environment: Optional[Environment]
    external_user_id: str
    provider_applicant_id: Optional[str] = None
    level_name: Optional[str] = None
    created_at: str = ""


@dataclass
class AccessToken:
    """Token efímero para el SDK del cliente. No se persiste (es de un
    solo uso, TTL corto)."""
    token: str
    expires_at: str
    external_user_id: str
    level_name: str


@dataclass
class ScreeningHit:
    """Hit de screening — mapea 1:1 a `kyb_screening_hits` (models.py:353)."""
    list_type: str
    list_name: str
    matched_name: str
    match_score: Optional[float] = None
    is_blocking: bool = False
    provider_hit_id: Optional[str] = None
    details: dict = field(default_factory=dict)


@dataclass
class VerificationSnapshot:
    """Snapshot completo de un veredicto — es lo que `start_verification`
    y `validate_webhook` producen y lo que se persiste en
    `kyb_verifications`.

    `provider_event_id` + `provider_event_ts` sostienen la idempotencia
    (`(event_id, applicant_id)` como llave) y el ordenamiento monotónico
    por applicant que el receptor de webhooks necesita para descartar
    eventos fuera de orden."""
    subject: SubjectRef
    capability: Capability
    provider: str
    provider_reference: Optional[str] = None
    status: VerificationStatus = "pending"
    outcome: Optional[VerificationOutcome] = None
    normalized_result: dict = field(default_factory=dict)
    raw_response_ref: Optional[str] = None
    screening_hits: list[ScreeningHit] = field(default_factory=list)
    provider_event_id: Optional[str] = None
    provider_event_ts: Optional[str] = None
    error: Optional[str] = None


@dataclass
class WebhookPayload:
    """Payload crudo del webhook — el receptor captura body + headers
    y se los pasa al provider. El contrato NO decide el shape del body
    (formatos varían entre providers); el provider parsea."""
    raw_body: bytes
    headers: dict[str, str]


# ---------------------------------------------------------------------------
# ABC — capacidades del proveedor
# ---------------------------------------------------------------------------
class VerificationProvider(ABC):
    """Contrato de un proveedor de verificación KYB.

    Instancias son inmutables tras __init__: `provider_id` y
    `environment` se fijan una sola vez. Concurrent-safe (el registry
    cachea una instancia por (provider, environment))."""

    provider_id: str
    environment: Optional[Environment]

    @abstractmethod
    def supports(self, capability: Capability) -> bool:
        """True si el proveedor cubre esa capacidad. `ManualProvider`
        soporta las tres. `SumsubProvider` soporta identity + screening
        (comparten applicant), no company_registry."""
        ...

    @abstractmethod
    def derive_external_user_id(self, subject: SubjectRef) -> str:
        """Determinístico. Nunca aleatorio. Idempotente frente a
        reintentos: la misma tupla (subject.case_id, subject.subject_type,
        subject.subject_id) siempre produce el mismo id.

        `ManualProvider` retorna algo canónico (`manual:{case_id}:{sub}`)
        aunque no se use externamente."""
        ...

    @abstractmethod
    async def ensure_applicant(self, subject: SubjectRef,
                                *, level_hint: Capability) -> Applicant:
        """Idempotente. Si ya existe applicant en `kyb_external_subjects`
        para (case_id, subject_type, subject_id, provider, environment),
        devuelve el existente. Si no, lo crea del lado del proveedor,
        lo persiste con `$setOnInsert` sobre `environment` (inmutable),
        y devuelve el objeto.

        `level_hint` sirve para elegir el nivel (SUMSUB_LEVEL_*) cuando
        el proveedor distingue niveles por tipo de sujeto."""
        ...

    @abstractmethod
    async def create_access_token(self, applicant: Applicant,
                                    *, ttl_seconds: int = 600) -> AccessToken:
        """Token efímero para el SDK web. TTL por default 10 min.
        `ManualProvider` no tiene SDK: lanza `ProviderError`."""
        ...

    @abstractmethod
    async def start_verification(self, applicant: Applicant,
                                    capability: Capability,
                                    *, trigger: str = "orchestrator"
                                    ) -> VerificationSnapshot:
        """Inicia (o consulta el estado de) una verificación para la
        capability indicada. Idempotente: no crea corridas paralelas
        para la misma (capability, applicant) en el mismo caso.
        Persiste un doc en `kyb_verifications` con `status="pending"` o
        `"in_progress"`, devuelve el snapshot.

        Sólo procesa la capability solicitada — nunca las tres. Esto
        preserva la idempotencia del reintento y soporta casos con
        modos duales (identidad automática + registry manual)."""
        ...

    @abstractmethod
    async def get_verdict(self, applicant: Applicant,
                            capability: Capability
                            ) -> Optional[VerificationSnapshot]:
        """SÓLO LECTURA local. Nunca llama al proveedor. Devuelve el
        último veredicto conocido persistido en `kyb_verifications`
        para (case_id, subject, capability, provider), o None si nunca
        hubo.

        Toda información que venga del proveedor entra por
        `start_verification` o por `validate_webhook`, que sí persisten.
        Un método de lectura que produzca efectos de red es difícil de
        razonar y de testear."""
        ...

    @abstractmethod
    async def validate_webhook(self, payload: WebhookPayload
                                ) -> tuple[Applicant, VerificationSnapshot]:
        """Valida firma HMAC del payload contra el secret del ambiente
        del applicant referenciado en el evento (NO contra el ambiente
        global). Parsea el body y devuelve (applicant, snapshot).

        Lanza:
          - `ProviderSignatureInvalid` si HMAC no valida. El mensaje es
            genérico ("invalid webhook signature"); el detalle va al log
            interno.
          - `ProviderEnvironmentMismatch` si el applicant pertenece a
            otro ambiente que el que declara el caso.
          - `ProviderError` si el body no parsea o falta campo obligatorio.

        `ManualProvider` no tiene webhook: lanza `NotImplementedError`
        para señalarlo claramente al caller."""
        ...
