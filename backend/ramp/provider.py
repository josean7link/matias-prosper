"""Phase 13 — `RampProvider` abstraction (PRD sections 2 & 9).

Every fiat-ramp provider (Alfred, Andes, future ones) implements this
contract. Domain code (positions, treasury, onboarding, UI) only ever talks
to a `RampProvider` instance returned by `RampProviderRegistry.resolve()`.

Adapters live under `ramp/adapters/`. Tests under `backend/tests/test_ramp_*`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional


# ---------------------------------------------------------------------------
# Enums (PRD §3.2)
# ---------------------------------------------------------------------------
class WalletAsset(str, Enum):
    ARSA = "arsa"
    USDT = "usdt"
    USDC = "usdc"


class AvailableChain(str, Enum):
    STELLAR    = "stellar"
    BASE       = "base"
    WORLDCHAIN = "worldchain"


class TxStatus(str, Enum):
    TRANSFER_PENDING = "TransferPending"
    PENDING          = "Pending"
    FAILED           = "Failed"
    SUCCESS          = "Success"


class FiatAccountStatus(str, Enum):
    PENDING   = "pending"
    COMPLETED = "completed"
    REJECTED  = "rejected"
    FAILED    = "failed"


class FiatAccountType(str, Enum):
    USER     = "user"
    BUSINESS = "business"


class FiatMovementType(str, Enum):
    WITHDRAWAL = "withdrawal"
    DEPOSIT    = "deposit"


class OnboardingStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED         = "approved"
    REJECTED         = "rejected"


ProviderId = Literal["alfred", "andeslabs"]


# ---------------------------------------------------------------------------
# DTOs — Capabilities, Account, Wallet, FiatAccount, Balance, Order…
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RampProviderCapabilities:
    id: ProviderId
    fiatRails: list[str]                 # e.g. ["AR_CVU"]
    producedAssets: list[WalletAsset]
    chains: list[AvailableChain]
    supportsDedicatedAccounts: bool      # CVU per end-customer
    supportsBalances: bool
    supportsOnramp: bool
    supportsOfframp: bool
    supportsInternationalOfframp: bool
    onrampModel: Literal["order", "deposit-driven"]


@dataclass
class RampAccount:
    """Mapping Prosper end_customer ⇄ provider user."""
    id: str
    org_id: str
    end_customer_id: str
    provider: str
    provider_user_id: str        # andes user_id / alfred customerId
    account_name: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RampWallet:
    id: str
    org_id: str
    ramp_account_id: str
    provider: str
    provider_user_id: str
    asset: WalletAsset
    chain: AvailableChain
    address: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class FiatAccountParams:
    org_id: str
    end_customer_id: str
    account_type: FiatAccountType
    chain: AvailableChain
    holder_name: str
    holder_tax_id: Optional[str] = None
    alias: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class KycFiles:
    """Bag of (filename → bytes) — provider decides which keys it consumes."""
    files: dict[str, bytes] = field(default_factory=dict)


@dataclass
class RampFiatAccount:
    id: str
    org_id: str
    ramp_account_id: str
    provider: str
    fiat_account_id: str
    account_type: FiatAccountType
    cvu: Optional[str] = None
    alias: Optional[str] = None
    holder_name: Optional[str] = None
    holder_tax_id: Optional[str] = None
    status: FiatAccountStatus = FiatAccountStatus.PENDING
    onboarding_status: OnboardingStatus = OnboardingStatus.PENDING_APPROVAL
    wallet_ref: Optional[dict[str, Any]] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RampBalance:
    asset: WalletAsset
    chain: AvailableChain
    balance: str                  # string (asset units) — avoid float drift
    as_of: Optional[datetime] = None


@dataclass
class OnrampInstructions:
    """Deposit-driven (Andes) returns CVU + alias for the user to transfer to.
    Order-based (Alfred) returns a depositAddress / paymentReference / etc.
    The frontend renders whatever fields are present."""
    cvu: Optional[str] = None
    alias: Optional[str] = None
    payment_reference: Optional[str] = None
    deposit_address: Optional[str] = None
    network: Optional[str] = None
    expires_at: Optional[datetime] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RampOrder:
    id: str
    provider: str
    external_id: str              # provider's order/transaction id
    status: TxStatus
    asset: WalletAsset
    chain: AvailableChain
    amount: str
    fail_reason: Optional[str] = None
    destination_cvu: Optional[str] = None
    destination_name: Optional[str] = None
    prosper_tx_id: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntlQuote:
    quote_id: str
    from_currency: str
    to_currency: str
    from_amount: str
    to_amount: str
    rate: str
    fee: str
    expires_at: Optional[datetime] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RampMovement:
    id: str
    org_id: str
    ramp_account_id: str
    provider: str
    external_id: str
    kind: FiatMovementType
    asset: WalletAsset
    chain: AvailableChain
    amount: str
    status: TxStatus
    fail_reason: Optional[str] = None
    destination_cvu: Optional[str] = None
    destination_name: Optional[str] = None
    prosper_tx_id: Optional[str] = None
    occurred_at: Optional[datetime] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RampWebhookEvent:
    delivery_id: str
    event_type: str
    payload: dict[str, Any]
    signature_valid: bool
    headers: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class NotSupportedByProvider(NotImplementedError):
    """Raised when business code calls a method the active provider doesn't
    support. The UI should branch on `provider.capabilities()` BEFORE calling,
    but we surface a clear error in case it doesn't."""


# ---------------------------------------------------------------------------
# RampProvider ABC (PRD §9)
# ---------------------------------------------------------------------------
class RampProvider(ABC):
    """Common surface implemented by every fiat-ramp adapter.

    Method names use snake_case (Python convention). The PRD interface uses
    camelCase TS naming — those map 1:1.
    """

    provider_id: ProviderId

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------
    @abstractmethod
    def capabilities(self) -> RampProviderCapabilities: ...

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    @abstractmethod
    async def create_account(self, *, org_id: str, end_customer_id: str,
                              display_name: Optional[str] = None) -> RampAccount: ...

    # ------------------------------------------------------------------
    # Wallets (on-chain)
    # ------------------------------------------------------------------
    @abstractmethod
    async def ensure_wallet(self, *, andes_user_id: str,
                              asset: WalletAsset,
                              chain: AvailableChain) -> RampWallet: ...

    # ------------------------------------------------------------------
    # Fiat accounts / CVU
    # ------------------------------------------------------------------
    @abstractmethod
    async def ensure_fiat_account(self, params: FiatAccountParams,
                                    files: Optional[KycFiles] = None,
                                    *,
                                    andes_user_id: Optional[str] = None
                                    ) -> RampFiatAccount: ...

    @abstractmethod
    async def get_funding_instructions(self, *, andes_user_id: str
                                          ) -> dict[str, Optional[str]]:
        """Returns at minimum ``{"cvu": str|None, "alias": str|None}``."""

    # ------------------------------------------------------------------
    # Balances
    # ------------------------------------------------------------------
    @abstractmethod
    async def get_balances(self, *, andes_user_id: str) -> list[RampBalance]: ...

    # ------------------------------------------------------------------
    # On-ramp (deposit-driven OR order-based depending on capabilities)
    # ------------------------------------------------------------------
    @abstractmethod
    async def initiate_onramp(self, *, andes_user_id: str,
                                **kwargs: Any) -> OnrampInstructions: ...

    # ------------------------------------------------------------------
    # Off-ramp (domestic fiat)
    # ------------------------------------------------------------------
    @abstractmethod
    async def initiate_offramp(self, *, andes_user_id: str,
                                 fiat_account_id: str, amount: float,
                                 to_cvu: Optional[str] = None,
                                 to_alias: Optional[str] = None) -> RampOrder: ...

    # ------------------------------------------------------------------
    # International off-ramp (ARS → BOB/PEN/PYG…)
    # ------------------------------------------------------------------
    @abstractmethod
    async def quote_international(self, **kwargs: Any) -> IntlQuote: ...

    @abstractmethod
    async def initiate_international_offramp(self, **kwargs: Any) -> RampOrder: ...

    # ------------------------------------------------------------------
    # Movements (fiat + on-chain transfers)
    # ------------------------------------------------------------------
    @abstractmethod
    async def list_movements(self, *, andes_user_id: Optional[str] = None,
                               filter: Optional[dict[str, Any]] = None
                               ) -> list[RampMovement]: ...

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------
    @abstractmethod
    def verify_webhook(self, raw_body: bytes,
                        headers: dict[str, str]) -> bool: ...

    @abstractmethod
    def parse_webhook(self, raw_body: bytes,
                       headers: Optional[dict[str, str]] = None
                       ) -> RampWebhookEvent: ...
