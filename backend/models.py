"""Pydantic schemas for the Prosper platform."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict, EmailStr
import uuid


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else uuid.uuid4().hex[:12]


Environment = Literal["sandbox", "production"]
OrgType = Literal["partner", "institutional", "internal"]
UserRole = Literal[
    "super_admin", "ops", "compliance", "finance",
    "client_admin", "client_user", "developer", "viewer"
]
OnboardingStatus = Literal["draft", "submitted", "under_review", "approved", "rejected", "needs_info"]
ComplianceStatus = Literal["pending", "approved", "escalated", "rejected"]
FundStatus = Literal["active", "paused", "closed"]
ProductStatus = Literal["active", "paused", "closed"]
PositionStatus = Literal["pending", "active", "matured", "redeemed", "cancelled"]
TxStatus = Literal["pending", "submitted", "confirmed", "failed", "retrying"]
TxType = Literal[
    "mint", "burn", "subscribe", "redeem", "transfer",
    "deposit", "withdraw", "lock", "claim", "fund", "fee"
]
AlertSeverity = Literal["info", "warning", "critical"]


# ---------- Auth / User ----------
class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    platform_role: UserRole = "viewer"  # global platform role
    org_id: Optional[str] = None  # primary org
    is_internal: bool = False  # Prosper staff
    mfa_enabled: bool = False
    created_at: datetime = Field(default_factory=now_utc)


# ---------- Organizations ----------
class Organization(BaseModel):
    model_config = ConfigDict(extra="ignore")
    org_id: str
    name: str
    legal_name: Optional[str] = None
    type: OrgType = "partner"
    country: Optional[str] = None
    tax_id: Optional[str] = None
    website: Optional[str] = None
    contact_email: Optional[str] = None
    status: Literal["active", "suspended", "pending"] = "active"
    environment: Environment = "sandbox"
    aum_usd: float = 0.0
    active_investors: int = 0
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OrgUser(BaseModel):
    org_user_id: str
    org_id: str
    user_id: str
    email: str
    name: str
    role: UserRole
    status: Literal["active", "invited", "suspended"] = "active"
    created_at: datetime = Field(default_factory=now_utc)


# ---------- Onboarding / Compliance ----------
class OnboardingCase(BaseModel):
    case_id: str
    org_id: Optional[str] = None
    applicant_name: str
    applicant_email: str
    applicant_type: Literal["individual", "entity"] = "individual"
    country: Optional[str] = None
    status: OnboardingStatus = "submitted"
    assigned_to: Optional[str] = None  # internal user_id
    sla_due: Optional[datetime] = None
    risk_score: Optional[float] = None
    progress: int = 0  # 0..100
    notes: Optional[str] = None
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ComplianceReview(BaseModel):
    review_id: str
    case_id: str
    reviewer_id: Optional[str] = None
    kyc_status: ComplianceStatus = "pending"
    kyb_status: Optional[ComplianceStatus] = None
    aml_check: Optional[ComplianceStatus] = None
    sanctions_check: Optional[ComplianceStatus] = None
    pep_check: Optional[ComplianceStatus] = None
    travel_rule: Optional[ComplianceStatus] = None
    decision: Optional[ComplianceStatus] = None
    comments: Optional[str] = None
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


# ---------- Funds / Products ----------
class Fund(BaseModel):
    fund_id: str
    code: str  # e.g. "PROS"
    name: str
    underlying: str  # e.g. "Quirón PyMEs"
    issuer_address: Optional[str] = None
    treasury_address: Optional[str] = None
    home_domain: Optional[str] = None
    total_supply: float = 0.0
    circulating_supply: float = 0.0
    nav_per_token: float = 1.0
    currency: str = "USD"
    status: FundStatus = "active"
    regulator: Optional[str] = None
    rating: Optional[str] = None
    environment: Environment = "sandbox"
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


class Product(BaseModel):
    product_id: str
    fund_id: str
    name: str
    kind: Literal["term_staking", "liquid", "structured"] = "term_staking"
    term_days: Optional[int] = None
    apr_bps: int = 0  # basis points
    min_amount: float = 0.0
    max_amount: Optional[float] = None
    payout_asset: str = "USDC"
    principal_asset: str = "PROS"
    status: ProductStatus = "active"
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


class NavSnapshot(BaseModel):
    snapshot_id: str
    fund_id: str
    as_of: datetime
    nav_per_token: float
    total_supply: float
    is_demo: bool = False


# ---------- Positions ----------
class Position(BaseModel):
    position_id: str
    org_id: str
    user_reference_id: Optional[str] = None
    product_id: str
    fund_id: str
    principal: float
    accrued_interest: float = 0.0
    claimed_interest: float = 0.0
    start_date: Optional[datetime] = None
    maturity_date: Optional[datetime] = None
    status: PositionStatus = "active"
    stellar_address: Optional[str] = None
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


# ---------- Treasury / Wallets ----------
class TreasuryAccount(BaseModel):
    account_id: str
    label: str
    kind: Literal["issuer", "treasury", "reward_pool", "fee"] = "treasury"
    fund_id: Optional[str] = None
    stellar_address: Optional[str] = None
    balance_native: float = 0.0  # XLM
    balance_asset: float = 0.0
    asset_code: Optional[str] = None
    environment: Environment = "sandbox"
    custody: Literal["hot", "warm", "cold"] = "warm"
    is_demo: bool = False


# ---------- Transactions ----------
class Transaction(BaseModel):
    tx_id: str
    prosper_tx_id: str  # idempotency anchor
    org_id: Optional[str] = None
    user_reference_id: Optional[str] = None
    position_id: Optional[str] = None
    fund_id: Optional[str] = None
    product_id: Optional[str] = None
    type: TxType
    amount: float
    asset_code: str = "PROS"
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    memo: Optional[str] = None
    tx_hash: Optional[str] = None
    ledger: Optional[int] = None
    status: TxStatus = "pending"
    fail_reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    environment: Environment = "sandbox"
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


class ReconciliationRecord(BaseModel):
    recon_id: str
    prosper_tx_id: str
    onchain_match: bool = False
    offchain_match: bool = True
    tx_hash: Optional[str] = None
    discrepancy: Optional[str] = None
    status: Literal["matched", "unmatched", "investigating", "resolved"] = "matched"
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


# ---------- API / Webhooks ----------
class ApiApp(BaseModel):
    app_id: str
    org_id: str
    name: str
    description: Optional[str] = None
    environment: Environment = "sandbox"
    status: Literal["active", "revoked"] = "active"
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


class ApiKey(BaseModel):
    key_id: str
    app_id: str
    org_id: str
    label: str
    key_prefix: str  # for display, e.g. "pk_live_abc..."
    key_hash: str  # never show actual key after creation
    scopes: List[str] = Field(default_factory=list)
    environment: Environment = "sandbox"
    last_used_at: Optional[datetime] = None
    status: Literal["active", "revoked"] = "active"
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


class WebhookEndpoint(BaseModel):
    endpoint_id: str
    app_id: str
    org_id: str
    url: str
    events: List[str] = Field(default_factory=list)
    secret_prefix: str
    status: Literal["active", "paused", "disabled"] = "active"
    environment: Environment = "sandbox"
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


class WebhookDelivery(BaseModel):
    delivery_id: str
    endpoint_id: str
    event_type: str
    payload: Dict[str, Any]
    response_status: Optional[int] = None
    attempt: int = 1
    delivered: bool = False
    next_retry_at: Optional[datetime] = None
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


# ---------- Alerts / Reports / Audit ----------
class Alert(BaseModel):
    alert_id: str
    org_id: Optional[str] = None
    severity: AlertSeverity = "info"
    kind: str
    title: str
    message: str
    resolved: bool = False
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


class Report(BaseModel):
    report_id: str
    org_id: Optional[str] = None
    kind: str  # "daily_nav", "audit", "tax", "performance"
    period: str  # e.g. "2026-02"
    status: Literal["generating", "ready", "failed"] = "ready"
    download_url: Optional[str] = None
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)


class AuditLog(BaseModel):
    audit_id: str
    actor_id: Optional[str] = None
    actor_email: Optional[str] = None
    action: str
    resource: str
    resource_id: Optional[str] = None
    environment: Environment = "sandbox"
    ip: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)


class EndCustomer(BaseModel):
    end_customer_id: str
    org_id: str
    external_ref: str
    name: str
    email: Optional[str] = None
    country: Optional[str] = None
    kyc_status: ComplianceStatus = "pending"
    total_invested: float = 0.0
    is_demo: bool = False
    created_at: datetime = Field(default_factory=now_utc)
