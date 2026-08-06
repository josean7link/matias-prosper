"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

// ===========================================================================
// Profile
// ===========================================================================
export interface ProfileNotifications {
  email_security_alerts:  boolean;
  email_account_activity: boolean;
  email_yield_summary:    boolean;
  email_marketing:        boolean;
  inapp_alerts:           boolean;
  inapp_transactions:     boolean;
}

export interface Profile {
  user_id:               string;
  email:                 string;
  full_name:             string;
  phone:                 string;
  language:              "es" | "en" | "pt";
  timezone:              string;
  avatar_url:            string | null;
  mfa_enabled:           boolean;
  notifications:         ProfileNotifications;
  deletion_requested:    boolean;
  deletion_effective_at: string | null;
  role:                  string;
  org_id:                string | null;
}

const fetcher = (p: string) => api(p);

export function useProfile() {
  return useSWR<Profile>("/v1/client/profile", fetcher);
}

export const TIMEZONE_OPTIONS = [
  { value: "America/Argentina/Buenos_Aires", label: "Argentina (Buenos Aires)" },
  { value: "America/Sao_Paulo",              label: "Brasil (São Paulo)" },
  { value: "America/Santiago",               label: "Chile (Santiago)" },
  { value: "America/Bogota",                 label: "Colombia (Bogotá)" },
  { value: "America/Mexico_City",            label: "México (Ciudad de México)" },
  { value: "America/Lima",                   label: "Perú (Lima)" },
  { value: "America/Montevideo",             label: "Uruguay (Montevideo)" },
  { value: "America/New_York",               label: "EE.UU. Este (Nueva York)" },
  { value: "America/Los_Angeles",            label: "EE.UU. Oeste (Los Ángeles)" },
  { value: "Europe/Madrid",                  label: "España (Madrid)" },
  { value: "Europe/London",                  label: "Reino Unido (Londres)" },
  { value: "UTC",                            label: "UTC" },
] as const;

export const LANGUAGE_OPTIONS = [
  { value: "es", label: "Español" },
  { value: "en", label: "English" },
  { value: "pt", label: "Português" },
] as const;

// ===========================================================================
// MFA
// ===========================================================================
export interface MfaSetupResponse {
  provisioning_uri: string;
  secret:           string;
  qr_data_url:      string;
  issuer:           string;
  account:          string;
  algorithm:        string;
  digits:           number;
  period:           number;
}

export interface MfaVerifyResponse {
  ok:           true;
  backup_codes: string[];
  warning:      string;
}

// ===========================================================================
// Sessions
// ===========================================================================
export interface Session {
  session_id:   string;
  label:        string;
  ip:           string;
  user_agent:   string;
  created_at:   string;
  last_seen_at: string;
  expires_at:   string;
  is_current:   boolean;
}

export function useSessions() {
  return useSWR<{ items: Session[]; total: number }>("/v1/client/sessions", fetcher);
}
