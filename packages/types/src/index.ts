// Shared TS types — Phase 1. Mirrors the Pydantic models in apps/api.

export type Env = "sandbox" | "production";

// ─── Roles (mirror of apps/api/roles.py) ─────────────────────────────────
export type Role =
  | "super_admin"
  | "admin"
  | "compliance_officer"
  | "finance"
  | "client_admin"
  | "client_user";

export const INTERNAL_ROLES: Role[] = [
  "super_admin", "admin", "compliance_officer", "finance",
];

export const isInternal = (r: Role) => INTERNAL_ROLES.includes(r);

// ─── Common mixins ───────────────────────────────────────────────────────
export interface Timestamped {
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
}

// ─── Organization ────────────────────────────────────────────────────────
export type OrgType =
  | "fintech" | "broker" | "family_office" | "retail_aggregator" | "other";

export type KybStatus =
  | "pending" | "in_review" | "approved" | "rejected" | "paused";

export type RiskProfile = "low" | "medium" | "high" | "critical";

export interface OrgCaps {
  subscribe_daily_cap_usd?:   number | null;
  subscribe_monthly_cap_usd?: number | null;
  redeem_daily_cap_usd?:      number | null;
  redeem_monthly_cap_usd?:    number | null;
}

export interface Organization extends Timestamped {
  org_id: string;
  legal_name: string;
  commercial_name: string;
  country: string;
  type: OrgType;
  kyb_status: KybStatus;
  risk_score: number;          // 0..100
  risk_profile: RiskProfile;
  allowlist_domains: string[];
  caps: OrgCaps;
  stellar_address?: string | null;
  start_date?: string | null;
  expected_aum_usd?: number | null;
  internal_notes?: string | null;
}

// ─── User ────────────────────────────────────────────────────────────────
export type UserStatus = "active" | "paused" | "invited" | "deleted";

export interface User extends Timestamped {
  user_id: string;
  org_id: string | null;
  email: string;
  role: Role;
  first_name?: string | null;
  last_name?: string | null;
  mfa_enabled: boolean;
  mfa_secret?: string | null;
  kyc_status: string;
  last_login_at?: string | null;
  status: UserStatus;
}

// ─── KYC / KYB ───────────────────────────────────────────────────────────
export interface DocumentRef {
  name: string;
  storage_path: string;
  content_type?: string | null;
  size?: number | null;
}

export interface KycCase extends Timestamped {
  kyc_id: string;
  org_id: string;
  user_id: string;
  provider: "sumsub" | "comply_advantage" | "manual";
  level?: string | null;
  status: string;
  score?: number | null;
  flags: string[];
  aml_check: string;
  sanctions_check: string;
  pep_check: string;
  travel_rule_check: string;
  documents: DocumentRef[];
  provider_payload: Record<string, unknown>;
  decision_by?: string | null;
  decision_at?: string | null;
  decision_reason?: string | null;
}

export interface UboEntry {
  name: string;
  percentage: number;
  nationality?: string | null;
  pep: boolean;
}

export interface KybChecklist {
  certificate: boolean;
  board_resolution: boolean;
  ubo_list: boolean;
  proof_address: boolean;
  financial_statements: boolean;
  sanctions_check: boolean;
  sectoral_risk: boolean;
  ownership_chart: boolean;
}

export interface KybCase extends Timestamped {
  kyb_id: string;
  org_id: string;
  provider: string;
  status: string;
  score?: number | null;
  documents: DocumentRef[];
  ubo_list: UboEntry[];
  checklist: KybChecklist;
  decision_by?: string | null;
  decision_at?: string | null;
  decision_reason?: string | null;
}

// ─── Position / Transaction ──────────────────────────────────────────────
export type PositionStatus = "active" | "matured" | "redeemed" | "cancelled";

export interface Position extends Timestamped {
  position_id: string;
  org_id: string;
  user_id?: string | null;
  product_id: string;
  principal_usd: number;
  accrued_interest: number;
  apr_bps: number;
  currency: string;
  start: string;
  maturity?: string | null;
  status: PositionStatus;
  prosper_tx_id?: string | null;
}

export type TxType =
  | "onramp" | "subscribe" | "redeem" | "mint"
  | "transfer" | "offramp" | "fee" | "payout";
export type TxStatus = "pending" | "confirmed" | "failed" | "reversed";

export interface Transaction extends Timestamped {
  tx_id: string;
  org_id: string;
  prosper_tx_id: string;
  type: TxType;
  amount: number;
  asset: string;
  status: TxStatus;
  tx_hash?: string | null;
  ledger?: number | null;
  memo?: string | null;
  metadata: Record<string, unknown>;
  related_position_id?: string | null;
  related_onramp_id?:   string | null;
  related_offramp_id?:  string | null;
  fee_amount?:   number | null;
  fee_currency?: string | null;
}

// ─── On / Off ramp ───────────────────────────────────────────────────────
export interface OnrampOrder extends Timestamped {
  onramp_id: string;
  org_id: string;
  user_id: string;
  alfred_id?: string | null;
  coelsa_id?: string | null;
  source_currency: string;
  source_amount: number;
  usdc_received?: number | null;
  fee?: number | null;
  rate?: number | null;
  status: string;
  prosper_tx_id?: string | null;
}

export interface OfframpOrder extends Timestamped {
  offramp_id: string;
  org_id: string;
  user_id: string;
  alfred_id?: string | null;
  target_currency: string;
  usdc_sent?: number | null;
  fiat_received?: number | null;
  fee?: number | null;
  rate?: number | null;
  bank_account_destination?: string | null;
  status: string;
}

// ─── API surface ─────────────────────────────────────────────────────────
export interface ApiKey extends Timestamped {
  api_key_id: string;
  org_id: string;
  name: string;
  scope: "sandbox" | "production";
  hashed_value: string;
  prefix: string;
  last_used_at?: string | null;
  last_used_ip?: string | null;
  created_by: string;
  revoked_at?: string | null;
}

export type WebhookStatus = "active" | "paused" | "failing";

export interface WebhookEndpoint extends Timestamped {
  webhook_id: string;
  org_id: string;
  url: string;
  events: string[];
  hmac_secret: string;
  status: WebhookStatus;
  fail_count: number;
  last_delivery_at?: string | null;
}

// ─── Alert / Audit / Approval ────────────────────────────────────────────
export type AlertSeverity = "info" | "warning" | "critical";
export type AlertStatus = "open" | "acknowledged" | "resolved";

export interface Alert extends Timestamped {
  alert_id: string;
  org_id?: string | null;
  rule_id?: string | null;
  type: "kyt" | "operational" | "compliance" | "technical";
  severity: AlertSeverity;
  status: AlertStatus;
  assigned_to?: string | null;
  payload: Record<string, unknown>;
  resolved_at?: string | null;
  resolution_note?: string | null;
}

export interface AuditLog {
  audit_id: string;
  org_id: string | null;
  actor_user_id: string | null;
  action: string;
  resource_type: string;
  resource_id?: string | null;
  metadata: Record<string, unknown>;
  ip?: string | null;
  user_agent?: string | null;
  timestamp: string;
}

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";

export interface Approval extends Timestamped {
  approval_id: string;
  type: string;
  org_id?: string | null;
  requested_by: string;
  payload: Record<string, unknown>;
  status: ApprovalStatus;
  approved_by?: string | null;
  approved_at?: string | null;
  mfa_verified: boolean;
  expires_at?: string | null;
}

// ─── /me payload ─────────────────────────────────────────────────────────
export interface MeResponse {
  user: User;
  org: Organization | null;
  role: Role;
  is_internal: boolean;
  acting_as_org: string | null;
  permissions: string[];
  features: {
    mfa_required: boolean;
    mfa_enabled: boolean;
    kyb_locked: boolean;
    kyc_pending: boolean;
    is_internal: boolean;
  };
}
