"""VerificationProvider — abstracción para proveedores de verificación
KYB (Fase 5b). El patrón sigue backend/services/storage/backend.py."""

from kyb.providers.base import (  # noqa: F401
    Applicant,
    AccessToken,
    Capability,
    Environment,
    ProviderEnvironmentMismatch,
    ProviderError,
    ProviderNotConfigured,
    ProviderSignatureInvalid,
    ProviderTransientError,
    ScreeningHit,
    SubjectRef,
    SubjectType,
    VerificationOutcome,
    VerificationProvider,
    VerificationSnapshot,
    VerificationStatus,
    WebhookPayload,
)
from kyb.providers.registry import get_provider  # noqa: F401
