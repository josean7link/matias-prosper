"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

export interface MeUser {
  user_id: string;
  email: string;
  role: "super_admin" | "admin" | "compliance_officer" | "finance" | "client_admin" | "client_user";
  org_id: string | null;
}

export function useMe() {
  return useSWR<{ user: MeUser }>("/v1/me", (p: string) => api(p));
}
