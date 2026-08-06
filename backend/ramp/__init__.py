"""Phase 13 — Ramp provider abstraction package.

Public surface:
    RampProvider                 — abstract base (provider.py)
    RampProviderRegistry         — resolves the active adapter (registry.py)
    NotSupportedByProvider       — raised when a provider lacks a capability
    DTOs / Enums / WebhookEvent  — re-exported from provider.py
"""
from .provider import (
    AvailableChain,
    FiatAccountParams,
    FiatAccountStatus,
    FiatAccountType,
    IntlQuote,
    KycFiles,
    NotSupportedByProvider,
    OnboardingStatus,
    OnrampInstructions,
    RampAccount,
    RampBalance,
    RampFiatAccount,
    RampMovement,
    RampOrder,
    RampProvider,
    RampProviderCapabilities,
    RampWallet,
    RampWebhookEvent,
    TxStatus,
    WalletAsset,
)
from .registry import RampProviderRegistry, get_registry

__all__ = [
    "AvailableChain",
    "FiatAccountParams",
    "FiatAccountStatus",
    "FiatAccountType",
    "IntlQuote",
    "KycFiles",
    "NotSupportedByProvider",
    "OnboardingStatus",
    "OnrampInstructions",
    "RampAccount",
    "RampBalance",
    "RampFiatAccount",
    "RampMovement",
    "RampOrder",
    "RampProvider",
    "RampProviderCapabilities",
    "RampProviderRegistry",
    "RampWallet",
    "RampWebhookEvent",
    "TxStatus",
    "WalletAsset",
    "get_registry",
]
