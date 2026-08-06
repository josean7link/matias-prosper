"use client";
/**
 * /client/offramp — Withdraw hub (P0·#3, Feb 2026).
 */
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import {
  AlertTriangle, ArrowRight, ArrowUpFromLine, Banknote,
  CheckCircle2, Coins, Loader2,
} from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { api } from "@/lib/api";
import { useClientMe } from "@/lib/client-portal";
import { fmtArsa, submitWithdraw, cvuLookup,
          type CvuLookup, type RampMovement } from "@/lib/ramp";

interface ArsaBalanceResp {
  cash: { arsa: number; arsa_cvu: number; arsa_stellar: number };
}

export default function OfframpHubPage() {
  const t  = useTranslations("offramp_hub");
  const tc = useTranslations("common");
  const { data: me } = useClientMe();
  const canOperate = me?.features?.can_operate ?? false;
  const orgId      = me?.org?.org_id;

  const { data: summary } = useSWR<ArsaBalanceResp>(
    canOperate ? "/v1/client/dashboard-summary" : null,
    (p: string) => api(p),
    { refreshInterval: 30_000 });
  const arsaAvailable = summary?.cash?.arsa ?? 0;

  const [expandedRail, setExpandedRail] = useState<"arsa" | null>(null);

  if (!canOperate) {
    return (
      <div data-testid="offramp-hub-page">
        <PageHeader
          breadcrumbs={[{ label: tc("home"), href: "/client" }, { label: t("breadcrumb") }]}
          title={t("title")}
        />
        <div className="prosper-card p-10 text-center" data-testid="offramp-blocked">
          <div className="mx-auto h-12 w-12 rounded-full bg-warning/10 text-warning
                            flex items-center justify-center mb-3">
            <AlertTriangle size={20} />
          </div>
          <h2 className="font-display font-bold text-lg text-fg">{t("blocked_title")}</h2>
          <p className="text-sm text-fg-muted mt-2">{t("blocked_msg")}</p>
          <Link href="/apply"
                  className="prosper-btn-primary inline-flex h-10 px-5 mt-5 text-sm">
            {tc("continue")} <ArrowRight size={14} />
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="offramp-hub-page">
      <PageHeader
        breadcrumbs={[{ label: tc("home"), href: "/client" }, { label: t("breadcrumb") }]}
        title={t("title")}
        subtitle={t("subtitle")}
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6"
            data-testid="offramp-rails-grid">
        <RailCard
          testid="rail-arsa"
          eyebrow={t("rail_arsa_eyebrow", { amount: fmtArsa(arsaAvailable) })}
          title={t("rail_arsa_title")}
          desc={t("rail_arsa_desc")}
          icon={<Banknote size={20} />}
          tone="primary"
          active
          onClick={() => setExpandedRail((s) => s === "arsa" ? null : "arsa")}
          expanded={expandedRail === "arsa"}
        />
        <RailCardSoon
          testid="rail-usdc-soon"
          eyebrow={t("rail_usdc_eyebrow")}
          title={t("rail_usdc_title")}
          desc={t("rail_usdc_desc")}
          icon={<Coins size={20} />}
        />
      </div>

      {expandedRail === "arsa" && orgId && (
        <ArsaWithdrawForm
          orgId={orgId}
          legalName={me?.org?.legal_name || ""}
          available={arsaAvailable}
          onDone={() => setExpandedRail(null)}
        />
      )}
    </div>
  );
}

function ArsaWithdrawForm({ orgId, legalName, available, onDone }: {
  orgId: string;
  legalName: string;
  available: number;
  onDone: () => void;
}) {
  const t = useTranslations("offramp_hub");
  const [amount, setAmount]         = useState<string>("");
  const [destKind, setDestKind]     = useState<"cvu" | "alias">("alias");
  const [destValue, setDestValue]   = useState<string>("");
  const [holderName, setHolderName] = useState<string>(legalName);
  const [lookup, setLookup]         = useState<CvuLookup | null>(null);
  const [lookupErr, setLookupErr]   = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirmed, setConfirmed]   = useState(false);
  const [movement, setMovement]     = useState<RampMovement | null>(null);

  const numericAmount = Number(amount) || 0;
  const insufficient  = numericAmount > available;
  const validDest     = destValue.trim().length > 0;

  useEffect(() => {
    setLookup(null); setLookupErr(null);
    if (!validDest) return;
    const tm = setTimeout(async () => {
      try {
        const r = await cvuLookup(
          destKind === "cvu"
            ? { cvu: destValue.trim() }
            : { alias: destValue.trim() });
        setLookup(r);
      } catch (e) {
        setLookupErr((e as Error).message || t("lookup_error"));
      }
    }, 600);
    return () => clearTimeout(tm);
  }, [destKind, destValue, validDest, t]);

  const canSubmit = (
    numericAmount > 0 && !insufficient && validDest &&
    holderName.trim().length >= 3 && !submitting && confirmed
  );

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const idempotencyKey = `arsa_wd_${orgId}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      const mv = await submitWithdraw(
        orgId,
        {
          amount: String(numericAmount),
          to_cvu:   destKind === "cvu"   ? destValue.trim() : undefined,
          to_alias: destKind === "alias" ? destValue.trim() : undefined,
          holder_name_confirmed: holderName.trim(),
        },
        idempotencyKey,
        orgId);
      setMovement(mv);
      toast.success(t("success_title"));
    } catch (e) {
      const err = e as Error;
      toast.error(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (movement) {
    const destText = movement.destination_cvu || movement.destination_alias || "—";
    return (
      <div className="prosper-card p-6" data-testid="offramp-arsa-success">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-full bg-success/15 text-success
                            flex items-center justify-center shrink-0">
            <CheckCircle2 size={20} />
          </div>
          <div className="flex-1">
            <h3 className="font-display font-bold text-base text-fg">
              {t("success_title")}
            </h3>
            <p className="text-sm text-fg-muted mt-1">
              {t("success_msg", { amount: fmtArsa(movement.amount), dest: destText })}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Link href="/client/transactions"
                     className="prosper-btn-primary h-9 px-4 text-xs gap-1.5"
                     data-testid="offramp-arsa-see-tx">
                {t("see_in_tx")} <ArrowRight size={13}/>
              </Link>
              <button onClick={onDone}
                       className="prosper-btn-ghost h-9 px-4 text-xs"
                       data-testid="offramp-arsa-done">
                {t("do_another")}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const holderMismatch = lookup?.holder_name &&
    holderName.trim() &&
    lookup.holder_name.trim().toLowerCase() !== holderName.trim().toLowerCase();

  return (
    <div className="prosper-card p-6" data-testid="offramp-arsa-form">
      <div className="flex items-center gap-2 mb-4">
        <Banknote size={18} className="text-primary" />
        <h3 className="font-display font-bold text-base text-fg">
          {t("form_title")}
        </h3>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label={t("field_amount")}>
          <div className="relative">
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
              className="prosper-input w-full h-12 text-2xl font-display font-bold pr-16"
              data-testid="offramp-arsa-amount"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-mono
                              uppercase tracking-wider text-fg-subtle">ARSa</span>
          </div>
          <div className="flex items-center justify-between mt-1">
            <button type="button" onClick={() => setAmount(String(available))}
                     className="text-[10px] font-mono uppercase tracking-wider
                                 text-primary hover:underline"
                     data-testid="offramp-arsa-max">
              {t("use_max", { amount: fmtArsa(available) })}
            </button>
            {insufficient && (
              <span className="text-[10px] text-danger" data-testid="offramp-arsa-insufficient">
                {t("exceeds_balance")}
              </span>
            )}
          </div>
        </Field>

        <Field label={t("field_destination")}>
          <div className="flex gap-2 mb-2">
            {(["alias", "cvu"] as const).map((k) => (
              <button key={k} type="button" onClick={() => setDestKind(k)}
                       className={`h-9 px-3 rounded-full text-[11px] font-mono
                                    uppercase tracking-wider transition
                                    ${destKind === k
                                      ? "bg-primary text-white"
                                      : "bg-surface-hover text-fg-muted"}`}
                       data-testid={`offramp-arsa-dest-${k}`}>
                {k === "alias" ? t("tab_alias") : t("tab_cvu")}
              </button>
            ))}
          </div>
          <input
            type="text"
            value={destValue}
            onChange={(e) => setDestValue(e.target.value)}
            placeholder={destKind === "alias" ? "your.bank.alias" : "0000000000000000000000"}
            className="prosper-input w-full h-10 text-sm font-mono"
            data-testid="offramp-arsa-dest-value"
          />
          {lookupErr && (
            <p className="text-[10px] text-warning mt-1" data-testid="offramp-arsa-lookup-error">
              {lookupErr}
            </p>
          )}
          {lookup && (
            <div className="mt-2 text-[11px] rounded border border-border bg-bg-elevated p-2"
                  data-testid="offramp-arsa-lookup-ok">
              <div className="text-fg-subtle font-mono uppercase tracking-wider text-[9px]">
                {t("lookup_holder")}
              </div>
              <div className="text-fg font-medium">
                {lookup.holder_name || "—"}
              </div>
              {lookup.bank && (
                <div className="text-fg-muted">{lookup.bank}</div>
              )}
            </div>
          )}
        </Field>

        <Field label={t("field_holder")}>
          <input
            type="text"
            value={holderName}
            onChange={(e) => setHolderName(e.target.value)}
            placeholder={t("holder_placeholder")}
            className="prosper-input w-full h-10 text-sm"
            data-testid="offramp-arsa-holder"
          />
          {holderMismatch && (
            <p className="text-[11px] text-warning mt-1 flex items-start gap-1"
                data-testid="offramp-arsa-holder-mismatch">
              <AlertTriangle size={11} className="mt-0.5 shrink-0" />
              {t("holder_mismatch")}
            </p>
          )}
        </Field>
      </div>

      <label className="flex items-start gap-2 mt-5 cursor-pointer
                          p-3 rounded-lg border border-border bg-bg-elevated
                          hover:bg-surface-hover transition"
              data-testid="offramp-arsa-confirm-label">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
          className="mt-0.5"
          data-testid="offramp-arsa-confirm"
        />
        <span className="text-[12px] text-fg-muted leading-snug">
          {t("confirm_prefix")}{" "}
          <strong className="text-fg">{fmtArsa(numericAmount || 0)}</strong>{" "}
          {t("confirm_to")}{" "}
          <strong className="text-fg">
            {t("confirm_dest", {
              kind: destKind === "alias" ? t("tab_alias") : t("tab_cvu"),
              value: destValue || "—",
            })}
          </strong>
          . {t("confirm_suffix")}
        </span>
      </label>

      <div className="flex gap-2 mt-4">
        <button type="button" onClick={onDone}
                 className="prosper-btn-ghost h-11 px-5 text-sm"
                 data-testid="offramp-arsa-cancel">
          {t("cancel")}
        </button>
        <button type="button" onClick={submit} disabled={!canSubmit}
                 className={"prosper-btn-primary h-11 px-5 text-sm flex-1 gap-2 "
                   + (canSubmit ? "" : "opacity-40 pointer-events-none")}
                 data-testid="offramp-arsa-submit">
          {submitting
            ? <><Loader2 size={14} className="animate-spin" /> {t("submitting")}</>
            : <><ArrowUpFromLine size={14}/> {t("submit")}</>}
        </button>
      </div>
    </div>
  );
}

function RailCard({ eyebrow, title, desc, icon, tone, active, expanded,
                     onClick, testid }: {
  eyebrow: string; title: string; desc: string;
  icon: React.ReactNode; tone: "primary" | "default";
  active: boolean; expanded: boolean;
  onClick: () => void; testid: string;
}) {
  const ring = expanded
    ? "border-primary ring-1 ring-primary"
    : tone === "primary"
      ? "border-primary/30 hover:border-primary"
      : "border-border hover:border-fg/30";
  const accent = tone === "primary"
    ? "bg-primary/10 text-primary"
    : "bg-fg/5 text-fg";
  return (
    <button type="button" onClick={onClick} disabled={!active}
             data-testid={testid}
             className={`prosper-card p-5 border text-left transition-all
                          ${ring} ${active ? "hover:bg-surface-hover"
                                            : "opacity-60 cursor-not-allowed"}`}>
      <div className="flex items-start gap-3">
        <div className={`h-11 w-11 rounded-full ${accent}
                          flex items-center justify-center shrink-0`}>
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {eyebrow}
          </div>
          <h3 className="font-display font-bold text-base text-fg mt-0.5">
            {title}
          </h3>
          <p className="text-sm text-fg-muted mt-1 leading-relaxed">{desc}</p>
        </div>
      </div>
    </button>
  );
}

function RailCardSoon({ eyebrow, title, desc, icon, testid }: {
  eyebrow: string; title: string; desc: string;
  icon: React.ReactNode; testid: string;
}) {
  const t = useTranslations("offramp_hub");
  return (
    <div className="prosper-card p-5 border border-border bg-bg-muted/30 relative"
          data-testid={testid}>
      <div className="absolute top-3 right-3">
        <Badge tone="warning" size="sm" data-testid={`${testid}-badge`}>
          {t("soon_badge")}
        </Badge>
      </div>
      <div className="flex items-start gap-3 opacity-80">
        <div className="h-11 w-11 rounded-full bg-fg/5 text-fg-subtle
                          flex items-center justify-center shrink-0">
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {eyebrow}
          </div>
          <h3 className="font-display font-bold text-base text-fg-muted mt-0.5">
            {title}
          </h3>
          <p className="text-sm text-fg-subtle mt-1 leading-relaxed">{desc}</p>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
        {label}
      </div>
      {children}
    </section>
  );
}
