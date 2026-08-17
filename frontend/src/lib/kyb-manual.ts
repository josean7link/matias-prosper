"use client";
/* Fase 5a — tipos y fetchers del módulo de verificación manual KYB. */
import { api } from "@/lib/api";

const BASE = "/v1/admin/compliance/kyb";

export type VerificationModes = {
  environment: "sandbox" | "production";
} & Record<string, { mode: string; updated_by?: string; updated_at?: string }>;

export interface TemplateItem {
  item_key: string; label: string; description: string;
  source_url: string | null; evidence_required: boolean;
  possible_outcomes: string[]; order: number;
}
export interface CheckTemplate {
  template_id: string; category: string; country: string | null;
  subject_types: string[]; version: number; active: boolean;
  items: TemplateItem[]; updated_by?: string; updated_at?: string;
}
export interface CheckItem extends TemplateItem {
  outcome: string | null; notes: string | null;
  evidence_document_ids: string[];
  completed_by: string | null; completed_at: string | null;
}
export interface ManualCheck {
  check_id: string; case_id: string; category: string;
  subject_type: string; subject_id: string; subject_name: string | null;
  template_id: string; template_version: number;
  status: "pending" | "in_progress" | "completed"; trigger: string;
  items: CheckItem[]; contributors: string[];
  completed_by: string | null; completed_at: string | null;
}
export interface EvidenceDoc {
  document_id: string; filename: string; check_id: string | null;
  version: number; uploaded_by: string; created_at?: string;
  discarded: { at: string; by: string; reason: string } | null;
}
export interface CaseChecks {
  case: { case_id: string; status: string; company_name: string | null;
          country: string | null;
          verification_modes: Record<string, string> | null;
          verification_states: Record<string, { state: string }> | null;
          submitted_at: string | null };
  checks: ManualCheck[];
  evidence_documents: EvidenceDoc[];
}

export const getModes = () => api<VerificationModes>(`${BASE}/verification-modes`);
export const putMode = (category: string, mode: string) =>
  api(`${BASE}/verification-modes/${category}`,
      { method: "PUT", body: JSON.stringify({ mode }) });
export const getTemplates = () => api<{ items: CheckTemplate[] }>(`${BASE}/templates`);
export const saveTemplate = (t: Partial<CheckTemplate>, id?: string) =>
  api(id ? `${BASE}/templates/${id}` : `${BASE}/templates`,
      { method: id ? "PUT" : "POST", body: JSON.stringify(t) });
export const getCaseChecks = (caseId: string) =>
  api<CaseChecks>(`${BASE}/cases/${caseId}/manual-checks`);
export const generateChecks = (caseId: string) =>
  api(`${BASE}/cases/${caseId}/manual-checks/generate`, { method: "POST" });
export const patchItem = (checkId: string, itemKey: string, body: {
  outcome: string; notes: string; evidence_document_ids: string[] }) =>
  api(`${BASE}/manual-checks/${checkId}/items/${itemKey}`,
      { method: "PATCH", body: JSON.stringify(body) });
export const completeCheck = (checkId: string) =>
  api(`${BASE}/manual-checks/${checkId}/complete`, { method: "POST" });
export const uploadEvidence = (checkId: string, itemKey: string, file: File) => {
  const fd = new FormData();
  fd.append("item_key", itemKey); fd.append("file", file);
  return api<{ document_id: string }>(`${BASE}/manual-checks/${checkId}/evidence`,
      { method: "POST", body: fd });
};
export const discardEvidence = (checkId: string, documentId: string, reason: string) =>
  api<{ reset_items: string[] }>(
      `${BASE}/manual-checks/${checkId}/evidence/${documentId}/discard`,
      { method: "POST", body: JSON.stringify({ reason }) });
export const forceManual = (caseId: string, category: string, reason: string) =>
  api(`${BASE}/cases/${caseId}/force-manual`,
      { method: "POST", body: JSON.stringify({ category, reason }) });

export const CATEGORY_LABELS: Record<string, string> = {
  identity: "Identidad",
  screening: "Screening (sanciones / PEP / medios)",
  company_registry: "Registro societario",
};
export const SUBJECT_LABELS: Record<string, string> = {
  company: "Empresa",
  legal_representative: "Representante legal",
  ubo: "Beneficiario final",
};
