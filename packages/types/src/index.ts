// Shared TypeScript types between API and frontend apps.

export type Env = "sandbox" | "production";

export type PlatformRole = "super_admin" | "ops" | "finance" | "compliance" | "developer" | "viewer";
export type ClientRole   = "client_admin" | "client_user";

export interface User {
  user_id: string;
  email: string;
  name?: string;
  picture?: string;
  platform_role?: PlatformRole;
  client_role?: ClientRole;
  org_id?: string | null;
  is_internal: boolean;
  mfa_enabled?: boolean;
}

export interface AuthLoginResponse { code: string; }
export interface AuthTokenResponse { accessToken: string; }
export interface MeResponse {
  email: string;
  user: { email: string; created_at: string; last_login: string } | null;
}

export type DocType   = "kyc" | "kyb" | "contract" | "other";
export type DocStatus = "pending" | "approved" | "rejected";

export type OnboardingStatus =
  | "submitted" | "under_review" | "needs_info" | "approved" | "rejected";
