"use client";
/**
 * /client/kyc-docs — Phase 22+ widget for individuals trapped in
 * `kyc_docs_required` / `kyc_pending_andes` (deprecated alias) /
 * `kyc_docs_submitted` (polling).
 *
 * Gated by `useClientMe`: only individuals with the right onboarding
 * state see it; everyone else is bounced back to /client.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import {
  Camera, CheckCircle2, Loader2, RefreshCw, User as UserIcon, IdCard, XCircle,
} from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { useClientMe } from "@/lib/client-portal";
import { api } from "@/lib/api";

type DocKey = "face" | "id_front" | "id_back";

interface Shot {
  blob: Blob;
  preview: string;
  size: number;
  filename: string;
}

const SLOTS: { key: DocKey; titleKey: string; helpKey: string; icon: React.ReactNode }[] = [
  { key: "face",     titleKey: "slot_face_title",     helpKey: "slot_face_help",     icon: <UserIcon size={18} /> },
  { key: "id_front", titleKey: "slot_id_front_title", helpKey: "slot_id_front_help", icon: <IdCard size={18} /> },
  { key: "id_back",  titleKey: "slot_id_back_title",  helpKey: "slot_id_back_help",  icon: <IdCard size={18} /> },
];

const MAX_BYTES = 10 * 1024 * 1024;
const POLL_INTERVAL_MS = 10_000;
const POLL_MAX_TRIES = 30;

type WidgetState =
  | { kind: "capture" }
  | { kind: "submitting" }
  | { kind: "approved" }
  | { kind: "submitted"; tries: number }
  | { kind: "rejected"; message: string };

export default function ClientKycDocsPage() {
  const t  = useTranslations("kyc_widget");
  const tc = useTranslations("common");
  const router = useRouter();
  const { data: me, mutate: refreshMe } = useClientMe();
  const [shots, setShots] = useState<Partial<Record<DocKey, Shot>>>({});
  const [state, setState] = useState<WidgetState>({ kind: "capture" });

  // Gate by status. Allowed: kyc_docs_required, kyc_pending_andes, kyc_docs_submitted.
  // Allowed applicant_type: individual. Otherwise bounce.
  useEffect(() => {
    if (!me) return;
    const orgType = me.org?.type;
    const onb = (me as { ramp_onboarding_status?: string }).ramp_onboarding_status;
    const canOperate = me.features?.can_operate ?? false;
    if (canOperate) {
      router.replace("/client");
      return;
    }
    if (orgType !== "personal") {
      router.replace("/client");
      return;
    }
    if (onb === "kyc_docs_submitted") {
      setState({ kind: "submitted", tries: 0 });
    }
  }, [me, router]);

  // Polling for kyc_docs_submitted → can_operate=true.
  useEffect(() => {
    if (state.kind !== "submitted") return;
    if (state.tries >= POLL_MAX_TRIES) return;
    const tm = setTimeout(async () => {
      const fresh = await refreshMe();
      if (fresh?.features?.can_operate) {
        setState({ kind: "approved" });
        setTimeout(() => router.replace("/client"), 3000);
        return;
      }
      setState({ kind: "submitted", tries: state.tries + 1 });
    }, POLL_INTERVAL_MS);
    return () => clearTimeout(tm);
  }, [state, refreshMe, router]);

  const onPickFile = (key: DocKey) => (ev: React.ChangeEvent<HTMLInputElement>) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_BYTES) { toast.error(`> 10MB`); return; }
    const url = URL.createObjectURL(file);
    setShots((prev) => ({
      ...prev,
      [key]: { blob: file, preview: url, size: file.size, filename: file.name },
    }));
  };

  const removeShot = (key: DocKey) => {
    const s = shots[key];
    if (s) URL.revokeObjectURL(s.preview);
    const next = { ...shots };
    delete next[key];
    setShots(next);
  };

  const canSubmit = SLOTS.every((s) => shots[s.key]);

  const submit = async () => {
    if (!canSubmit) return;
    setState({ kind: "submitting" });
    const fd = new FormData();
    for (const k of ["face", "id_front", "id_back"] as DocKey[]) {
      const s = shots[k]!;
      fd.append(k, s.blob, s.filename);
    }
    try {
      const resp: { ok: boolean; ramp_account_status: string; activated: boolean;
                    can_operate: boolean } =
        await api("/v1/client/me/andes-kyc-docs", { method: "POST", body: fd });
      await refreshMe();
      if (resp.activated || resp.can_operate) {
        setState({ kind: "approved" });
        setTimeout(() => router.replace("/client"), 3000);
      } else {
        setState({ kind: "submitted", tries: 0 });
      }
    } catch (e) {
      const err = e as { status?: number; message?: string };
      let msg = err.message || "Error";
      try {
        const parsed = JSON.parse(msg);
        if (parsed && typeof parsed === "object" && parsed.message) {
          msg = parsed.message;
        }
      } catch {}
      setState({ kind: "rejected", message: msg });
    }
  };

  return (
    <div data-testid="client-kyc-docs">
      <PageHeader
        breadcrumbs={[{ label: tc("home"), href: "/client" }, { label: t("breadcrumb") }]}
        title={t("title")}
        subtitle={t("subtitle")}
      />

      {state.kind === "approved" && (
        <ResultPanel
          tone="success"
          icon={<CheckCircle2 size={28} />}
          title={t("success_approved_title")}
          body={t("success_approved_body")}
        />
      )}

      {state.kind === "submitted" && (
        <ResultPanel
          tone="info"
          icon={<Loader2 size={28} className="animate-spin" />}
          title={t("success_submitted_title")}
          body={
            state.tries >= POLL_MAX_TRIES
              ? t("polling_timeout")
              : state.tries > 0
                ? t("polling_still_waiting")
                : t("success_submitted_body")
          }
        />
      )}

      {state.kind === "rejected" && (
        <ResultPanel
          tone="danger"
          icon={<XCircle size={28} />}
          title={t("rejected_title")}
          body={state.message}
          action={
            <button
              onClick={() => setState({ kind: "capture" })}
              className="prosper-btn-primary h-10 px-5 text-sm"
              data-testid="kyc-retry-btn"
            >
              {t("rejected_retry")}
            </button>
          }
        />
      )}

      {(state.kind === "capture" || state.kind === "submitting") && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6"
               data-testid="kyc-slots">
            {SLOTS.map((slot) => {
              const shot = shots[slot.key];
              return (
                <div
                  key={slot.key}
                  className="prosper-card p-4"
                  data-testid={`kyc-slot-${slot.key}`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-primary">{slot.icon}</span>
                    <div className="font-display font-bold text-sm">
                      {t(slot.titleKey as keyof Messages)}
                    </div>
                    {shot && <Badge tone="success" size="sm">✓</Badge>}
                  </div>
                  <p className="text-[11px] text-fg-muted mb-3 min-h-[2.5em]">
                    {t(slot.helpKey as keyof Messages)}
                  </p>
                  {shot ? (
                    <div className="space-y-2">
                      <img
                        src={shot.preview}
                        alt={slot.key}
                        className="w-full h-32 object-cover rounded border border-border"
                      />
                      <button
                        onClick={() => removeShot(slot.key)}
                        className="prosper-btn-ghost h-8 text-xs gap-1.5 w-full"
                        data-testid={`kyc-slot-${slot.key}-replace`}
                      >
                        <RefreshCw size={11} /> {t("replace")} ·{" "}
                        {t("size_ok", { kb: Math.round(shot.size / 1024) })}
                      </button>
                    </div>
                  ) : (
                    <label
                      className="prosper-btn-primary h-10 px-3 text-xs gap-2 w-full cursor-pointer
                                 flex items-center justify-center"
                      data-testid={`kyc-slot-${slot.key}-capture`}
                    >
                      <Camera size={13} /> {t("capture")}
                      <input
                        type="file"
                        accept="image/jpeg,image/png,image/webp,image/heic,application/pdf"
                        capture={slot.key === "face" ? "user" : "environment"}
                        className="hidden"
                        onChange={onPickFile(slot.key)}
                      />
                    </label>
                  )}
                </div>
              );
            })}
          </div>

          <button
            onClick={submit}
            disabled={!canSubmit || state.kind === "submitting"}
            className="prosper-btn-primary h-12 px-6 text-sm gap-2 w-full md:w-auto"
            data-testid="kyc-submit-btn"
          >
            {state.kind === "submitting" ? (
              <><Loader2 size={14} className="animate-spin" /> {t("submitting")}</>
            ) : (
              <><CheckCircle2 size={14} /> {t("submit")}</>
            )}
          </button>
        </>
      )}
    </div>
  );
}

type Messages = string;

function ResultPanel({ tone, icon, title, body, action }: {
  tone: "success" | "info" | "danger";
  icon: React.ReactNode;
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  const accent = tone === "success" ? "bg-success/10 text-success border-success/30"
              : tone === "danger"  ? "bg-danger/10 text-danger border-danger/30"
              :                      "bg-primary/10 text-primary border-primary/30";
  return (
    <div className={`prosper-card p-8 text-center border-2 ${accent}`}
         data-testid={`kyc-result-${tone}`}>
      <div className="mx-auto mb-3">{icon}</div>
      <h2 className="font-display font-bold text-xl text-fg">{title}</h2>
      <p className="text-sm text-fg-muted mt-2 max-w-md mx-auto whitespace-pre-line">
        {body}
      </p>
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}
