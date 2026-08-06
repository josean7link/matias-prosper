"""Phase 1 — Pydantic schemas for every collection.

Every model:
  - `_id`            (Mongo native, generated)
  - `org_id`         (except Organization)
  - `created_at`     (UTC ISO)
  - `updated_at`     (UTC ISO)
  - `is_deleted`     (bool — soft delete)
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, List, Optional, Dict
from pydantic import BaseModel, EmailStr, Field
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# -------------------------------------------------------------------------
# Mixins
# -------------------------------------------------------------------------
class TimestampMixin(BaseModel):
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    is_deleted: bool = False


# -------------------------------------------------------------------------
# Organization
# -------------------------------------------------------------------------
class OrgCaps(BaseModel):
    subscribe_daily_cap_usd:   Optional[float] = None
    subscribe_monthly_cap_usd: Optional[float] = None
    redeem_daily_cap_usd:      Optional[float] = None
    redeem_monthly_cap_usd:    Optional[float] = None


class Organization(TimestampMixin):
    org_id: str = Field(default_factory=lambda: new_id("org"))
    legal_name: str
    commercial_name: str
    country: str
    type: str = "fintech"  # fintech | broker | family_office | retail_aggregator | other
    kyb_status: str = "pending"  # pending | in_review | approved | rejected | paused
    risk_score: int = 0  # 0..100
    risk_profile: str = "low"  # low | medium | high | critical
    allowlist_domains: List[str] = []
    caps: OrgCaps = Field(default_factory=OrgCaps)
    stellar_address: Optional[str] = None
    alfred_customer_id: Optional[str] = None  # Sprint 12.6 — KYB customer
    start_date: Optional[str] = None
    expected_aum_usd: Optional[float] = None
    internal_notes: Optional[str] = None
    # Phase 23 — N1/N2 hierarchy. N1 (parent_org_id=None, level=1) can create
    # exactly one tier of children (N2). N2 (parent_org_id=<n1>, level=2) is
    # a full org with its own KYB / ramp account / caps. Max depth = 2.
    parent_org_id: Optional[str] = None
    level: int = 1


# -------------------------------------------------------------------------
# User
# -------------------------------------------------------------------------
class User(TimestampMixin):
    user_id: str = Field(default_factory=lambda: new_id("usr"))
    org_id: Optional[str] = None  # null for system super_admins not attached to an org
    email: EmailStr
    role: str = "client_user"
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    mfa_enabled: bool = False
    mfa_secret: Optional[str] = None  # encrypted on write — placeholder here
    kyc_status: str = "pending"
    alfred_customer_id: Optional[str] = None  # Sprint 12.6 — KYC customer
    last_login_at: Optional[str] = None
    status: str = "invited"  # active | paused | invited | deleted


# -------------------------------------------------------------------------
# KYC / KYB
# -------------------------------------------------------------------------
class DocumentRef(BaseModel):
    name: str
    storage_path: str
    content_type: Optional[str] = None
    size: Optional[int] = None


class KycCase(TimestampMixin):
    kyc_id: str = Field(default_factory=lambda: new_id("kyc"))
    org_id: str
    user_id: str
    provider: str = "manual"  # sumsub | comply_advantage | manual
    level: Optional[str] = None
    status: str = "pending"
    score: Optional[int] = None
    flags: List[str] = []
    aml_check: str = "pending"
    sanctions_check: str = "pending"
    pep_check: str = "pending"
    travel_rule_check: str = "pending"
    documents: List[DocumentRef] = []
    provider_payload: Dict[str, Any] = {}
    decision_by: Optional[str] = None
    decision_at: Optional[str] = None
    decision_reason: Optional[str] = None


class UboEntry(BaseModel):
    name: str
    percentage: float
    nationality: Optional[str] = None
    pep: bool = False


class KybChecklist(BaseModel):
    certificate: bool = False
    board_resolution: bool = False
    ubo_list: bool = False
    proof_address: bool = False
    financial_statements: bool = False
    sanctions_check: bool = False
    sectoral_risk: bool = False
    ownership_chart: bool = False


class KybCase(TimestampMixin):
    kyb_id: str = Field(default_factory=lambda: new_id("kyb"))
    org_id: str
    provider: str = "manual"
    status: str = "pending"
    score: Optional[int] = None
    documents: List[DocumentRef] = []
    ubo_list: List[UboEntry] = []
    checklist: KybChecklist = Field(default_factory=KybChecklist)
    decision_by: Optional[str] = None
    decision_at: Optional[str] = None
    decision_reason: Optional[str] = None


# -------------------------------------------------------------------------
# Position / Transaction
# -------------------------------------------------------------------------
class Position(TimestampMixin):
    position_id: str = Field(default_factory=lambda: new_id("pos"))
    org_id: str
    user_id: Optional[str] = None
    product_id: str
    principal_usd: float
    accrued_interest: float = 0.0
    apr_bps: int  # basis points (1% = 100)
    currency: str = "USDC"
    start: str = Field(default_factory=utc_now)
    maturity: Optional[str] = None
    status: str = "active"  # active | matured | redeemed | cancelled
    prosper_tx_id: Optional[str] = None


class Transaction(TimestampMixin):
    tx_id: str = Field(default_factory=lambda: new_id("tx"))
    org_id: str
    prosper_tx_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str  # onramp | subscribe | redeem | mint | transfer | offramp | fee | payout
    amount: float
    asset: str = "USDC"
    status: str = "pending"  # pending | confirmed | failed | reversed
    tx_hash: Optional[str] = None
    ledger: Optional[int] = None
    memo: Optional[str] = None
    metadata: Dict[str, Any] = {}
    related_position_id: Optional[str] = None
    related_onramp_id:   Optional[str] = None
    related_offramp_id:  Optional[str] = None
    fee_amount:   Optional[float] = None
    fee_currency: Optional[str] = None


# -------------------------------------------------------------------------
# On/Off-ramp
# -------------------------------------------------------------------------
class OnrampOrder(TimestampMixin):
    onramp_id: str = Field(default_factory=lambda: new_id("on"))
    org_id: str
    user_id: str
    alfred_id: Optional[str] = None
    coelsa_id: Optional[str] = None
    source_currency: str  # ARS | USD | CLP | …
    source_amount: float
    usdc_received: Optional[float] = None
    fee: Optional[float] = None
    rate: Optional[float] = None
    status: str = "pending"
    prosper_tx_id: Optional[str] = None


class OfframpOrder(TimestampMixin):
    offramp_id: str = Field(default_factory=lambda: new_id("off"))
    org_id: str
    user_id: str
    alfred_id: Optional[str] = None
    target_currency: str
    usdc_sent: Optional[float] = None
    fiat_received: Optional[float] = None
    fee: Optional[float] = None
    rate: Optional[float] = None
    bank_account_destination: Optional[str] = None
    status: str = "pending"


# -------------------------------------------------------------------------
# API surface
# -------------------------------------------------------------------------
class ApiKey(TimestampMixin):
    api_key_id: str = Field(default_factory=lambda: new_id("ak"))
    org_id: str
    name: str
    scope: str = "sandbox"  # sandbox | production
    hashed_value: str       # bcrypt hash
    prefix: str             # first 8 chars of plaintext (visible)
    last_used_at: Optional[str] = None
    last_used_ip: Optional[str] = None
    created_by: str
    revoked_at: Optional[str] = None


class WebhookEndpoint(TimestampMixin):
    webhook_id: str = Field(default_factory=lambda: new_id("whk"))
    org_id: str
    url: str
    events: List[str] = []
    hmac_secret: str        # encrypted on write
    status: str = "active"  # active | paused | failing
    fail_count: int = 0
    last_delivery_at: Optional[str] = None


# -------------------------------------------------------------------------
# Alert / Audit / Approval
# -------------------------------------------------------------------------
class Alert(TimestampMixin):
    alert_id: str = Field(default_factory=lambda: new_id("alt"))
    org_id: Optional[str] = None  # null for system-wide alerts
    rule_id: Optional[str] = None
    type: str = "operational"  # kyt | operational | compliance | technical
    severity: str = "info"     # info | warning | critical
    status: str = "open"       # open | acknowledged | resolved
    assigned_to: Optional[str] = None
    payload: Dict[str, Any] = {}
    resolved_at: Optional[str] = None
    resolution_note: Optional[str] = None


class AuditLog(BaseModel):
    """IMMUTABLE — `db.audit.write_log` is the only way to insert.
    Updates/deletes are blocked at the Mongo helper layer + tests cover it."""
    audit_id: str = Field(default_factory=lambda: new_id("aud"))
    org_id: Optional[str] = None
    actor_user_id: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: str = Field(default_factory=utc_now)


class Approval(TimestampMixin):
    approval_id: str = Field(default_factory=lambda: new_id("apv"))
    type: str  # mint | redeem_large | kyb_override | …
    org_id: Optional[str] = None
    requested_by: str
    payload: Dict[str, Any] = {}
    status: str = "pending"   # pending | approved | rejected | expired
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    mfa_verified: bool = False
    expires_at: Optional[str] = None
