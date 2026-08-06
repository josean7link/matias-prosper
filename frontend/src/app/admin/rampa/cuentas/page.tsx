"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Badge, KpiCard, PageHeader } from "@prosper/ui";
import {
  Wallet, Search, Filter, ChevronRight, X,
  CheckCircle2, AlertTriangle, XCircle, Clock,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  useAdminAccounts, useAdminAccountsKpis,
  fmtArsaAdmin, type RampAccountRow,
} from "@/lib/admin-ramp";

/** Phase 16 · B — /admin/rampa/cuentas
 *  KPIs + tabla + drill-down. Saldo ARSa de primera clase. */
export default function RampAccountsPage() {
  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");
  const [status, setStatus] = useState("");
  const [hasCvu, setHasCvu] = useState<"" | "true" | "false">("");
  const [q, setQ] = useState("");
  const qs = "?" + new URLSearchParams({
    ...(status ? { status } : {}),
    ...(hasCvu ? { has_cvu: hasCvu } : {}),
    ...(q ? { q } : {}),
    limit: "200",
  }).toString();

  const kpis = useAdminAccountsKpis();
  const list = useAdminAccounts(qs);
  const [drill, setDrill] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: tA("breadcrumb_admin") }, { label: tH("rampa_label") }, { label: tH("rampa_accounts_bc") }]}
        title={tH("rampa_accounts_title")}
        subtitle={tH("rampa_accounts_subtitle")}
      />

      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3"
           data-testid="ramp-accounts-kpis">
        <KpiCard
          testId="kpi-arsa-aum"
          label="Saldo ARSa bajo gestión"
          value={fmtArsaAdmin(kpis.data?.total_arsa_under_management || "0")}
          hint="peso digital 1:1"
          loading={kpis.isLoading}/>
        <KpiCard
          testId="kpi-accounts-active"
          label="Cuentas activas"
          value={String(kpis.data?.accounts_active ?? "—")}
          hint="onboarding=approved"
          loading={kpis.isLoading}/>
        <KpiCard
          testId="kpi-accounts-pending"
          label="Pendientes de KYC"
          value={String(kpis.data?.accounts_pending_kyc ?? "—")}
          hint="pending_approval + kyc_pending_andes"
          loading={kpis.isLoading}/>
        <KpiCard
          testId="kpi-accounts-error"
          label="Con error / rechazadas"
          value={String(kpis.data?.accounts_error ?? "—")}
          hint="needs reconciliation"
          loading={kpis.isLoading}/>
      </div>

      {/* Filters */}
      <section className="prosper-card p-4 flex flex-wrap items-end gap-3"
               data-testid="ramp-accounts-filters">
        <div className="flex-1 min-w-[220px]">
          <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Búsqueda
          </span>
          <div className="relative mt-1">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle"/>
            <input
              value={q} onChange={e => setQ(e.target.value)}
              placeholder="end-customer · CVU · andes user_id"
              data-testid="ramp-accounts-search"
              className="w-full pl-7 pr-3 h-9 rounded border border-border bg-bg text-fg text-sm font-mono focus:outline-none focus:border-primary"/>
          </div>
        </div>
        <FilterSelect label="Estado" value={status} onChange={setStatus}
                       testid="ramp-accounts-filter-status"
                       options={[
                         ["", "todos"],
                         ["approved", "approved"],
                         ["pending_approval", "pending_approval"],
                         ["kyc_pending_andes", "kyc_pending_andes"],
                         ["error", "error"],
                         ["rejected", "rejected"],
                       ]}/>
        <FilterSelect label="CVU" value={hasCvu}
                       onChange={(v) => setHasCvu(v as any)}
                       testid="ramp-accounts-filter-cvu"
                       options={[["", "todos"], ["true", "con CVU"], ["false", "sin CVU"]]}/>
      </section>

      {/* Table */}
      <section className="prosper-card overflow-x-auto"
               data-testid="ramp-accounts-table">
        <table className="w-full text-xs">
          <thead className="bg-surface border-b border-border">
            <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              <th className="text-left  py-2 px-3">End-customer</th>
              <th className="text-left  py-2 px-3">Provider · userId</th>
              <th className="text-left  py-2 px-3">CVU · Alias</th>
              <th className="text-left  py-2 px-3">Estado</th>
              <th className="text-right py-2 px-3">Saldo ARSa</th>
              <th className="text-left  py-2 px-3">Última actualización</th>
              <th className="text-right py-2 px-3"></th>
            </tr>
          </thead>
          <tbody>
            {list.isLoading && (
              <tr><td colSpan={7} className="py-4 text-center text-fg-subtle italic">
                Cargando…</td></tr>
            )}
            {!list.isLoading && (list.data?.items.length ?? 0) === 0 && (
              <tr><td colSpan={7} className="py-6 text-center text-fg-subtle">
                Sin resultados</td></tr>
            )}
            {(list.data?.items || []).map(a => (
              <AccountRow key={a.id} a={a} onOpen={() => setDrill(a.end_customer_id)}/>
            ))}
          </tbody>
        </table>
      </section>

      {drill && (
        <DrillDownDrawer
          endCustomerId={drill}
          onClose={() => setDrill(null)}/>
      )}
    </div>
  );
}

function AccountRow({ a, onOpen }: { a: RampAccountRow; onOpen: () => void }) {
  const StatusIcon = a.onboarding_status === "approved"
    ? <CheckCircle2 size={11} className="text-success"/>
    : a.onboarding_status === "kyc_pending_andes"
      ? <Clock size={11} className="text-warning"/>
      : a.onboarding_status === "error"
        ? <XCircle size={11} className="text-danger"/>
        : <AlertTriangle size={11} className="text-warning"/>;
  return (
    <tr className="border-b border-border/40 hover:bg-surface/50"
        data-testid={`ramp-account-row-${a.end_customer_id}`}>
      <td className="py-2 px-3 font-mono text-fg">{a.end_customer_id}</td>
      <td className="py-2 px-3 font-mono text-fg-muted text-[10px]">
        <span className="text-fg">{a.provider}</span>
        {a.provider_user_id && (
          <div>{a.provider_user_id.slice(0, 14)}…</div>
        )}
      </td>
      <td className="py-2 px-3 font-mono text-[10px]">
        {a.cvu
          ? <><div className="text-fg">{a.cvu.replace(/(.{4})/g, "$1 ").trim()}</div>
              <div className="text-fg-subtle">{a.alias || "—"}</div></>
          : <span className="text-fg-subtle italic">sin CVU</span>}
      </td>
      <td className="py-2 px-3">
        <span className="inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-wider">
          {StatusIcon} {a.onboarding_status}
        </span>
      </td>
      <td className="py-2 px-3 text-right font-mono tabular text-fg">
        {fmtArsaAdmin(a.arsa_balance)}
      </td>
      <td className="py-2 px-3 font-mono text-[10px] text-fg-subtle">
        {new Date(a.updated_at).toLocaleString()}
      </td>
      <td className="py-2 px-3 text-right">
        <button onClick={onOpen}
                data-testid={`ramp-account-open-${a.end_customer_id}`}
                className="prosper-btn-ghost h-7 text-[11px] gap-1">
          Detalle <ChevronRight size={11}/>
        </button>
      </td>
    </tr>
  );
}

function FilterSelect({ label, value, onChange, options, testid }: {
  label: string; value: string; onChange: (v: string) => void;
  options: [string, string][]; testid?: string;
}) {
  return (
    <label className="block">
      <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
        {label}
      </span>
      <select value={value} onChange={e => onChange(e.target.value)}
              data-testid={testid}
              className="mt-1 px-2.5 h-9 rounded border border-border bg-bg text-fg text-sm font-mono focus:outline-none focus:border-primary">
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function DrillDownDrawer({ endCustomerId, onClose }: {
  endCustomerId: string; onClose: () => void;
}) {
  // SWR-less direct fetch — drill data is one-shot
  const [data, setData] = useState<any | null>(null);
  const [err, setErr]   = useState<string | null>(null);

  if (!data && !err) {
    api(`/v1/admin/ramp/accounts/${endCustomerId}/detail`)
      .then((d: any) => setData(d))
      .catch((e: any) => setErr(e?.message || "Error cargando"));
  }
  return (
    <div className="fixed inset-0 z-50 bg-bg/70 backdrop-blur-sm flex justify-end"
         onClick={onClose} data-testid="ramp-account-drilldown">
      <div className="bg-bg border-l border-border w-full max-w-2xl h-full overflow-y-auto p-6"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              Detalle de cuenta
            </div>
            <h2 className="font-display font-bold text-lg text-fg">
              {endCustomerId}
            </h2>
          </div>
          <button onClick={onClose} className="text-fg-subtle hover:text-fg">
            <X size={16}/>
          </button>
        </div>
        {err && <div className="text-danger text-sm">{err}</div>}
        {!data && !err && (
          <div className="text-fg-subtle italic text-xs">Cargando…</div>
        )}
        {data && (
          <div className="space-y-5 text-xs">
            <Section title="Cuenta">
              <pre className="font-mono text-[11px] bg-surface p-3 rounded border border-border overflow-x-auto">
                {JSON.stringify(data.account, null, 2)}
              </pre>
            </Section>
            <Section title="Wallets" testid="drill-wallets">
              {data.wallets.length === 0
                ? <Empty text="Sin wallets"/>
                : <ul className="space-y-1">{data.wallets.map((w: any) => (
                    <li key={w.id || w.address} className="font-mono text-[11px] border-b border-border/40 py-1">
                      <span className="text-fg">{w.asset} · {w.chain}</span>
                      <span className="text-fg-muted ml-2">{w.address}</span>
                    </li>))}</ul>}
            </Section>
            <Section title="Saldos" testid="drill-balances">
              {data.balances.length === 0
                ? <Empty text="Sin saldos"/>
                : <ul className="space-y-1">{data.balances.map((b: any, i: number) => (
                    <li key={`${b.asset}-${b.chain}-${i}`} className="font-mono flex justify-between border-b border-border/40 py-1">
                      <span>{b.asset === "arsa" ? "ARSa" : b.asset.toUpperCase()} · {b.chain}</span>
                      <span className="tabular">
                        {b.asset === "arsa" ? fmtArsaAdmin(b.balance) : b.balance}
                      </span>
                    </li>))}</ul>}
            </Section>
            <Section title="Fiat (CVU)">
              {!data.fiat_account
                ? <Empty text="No emitido"/>
                : <pre className="font-mono text-[11px] bg-surface p-3 rounded border border-border overflow-x-auto">
                    {JSON.stringify(data.fiat_account, null, 2)}
                  </pre>}
            </Section>
            <Section title={`Movimientos recientes (${data.recent_movements.length})`}
                      testid="drill-movements">
              {data.recent_movements.length === 0
                ? <Empty text="Sin movimientos"/>
                : <ul className="space-y-1">{data.recent_movements.map((m: any) => (
                    <li key={m.id} className="font-mono text-[10px] flex justify-between border-b border-border/40 py-1">
                      <span>{new Date(m.created_at).toLocaleString()}</span>
                      <span>{m.kind} · <Badge tone={
                        m.status === "Success" ? "success"
                          : m.status === "Failed" ? "danger" : "warning"}>{m.status}</Badge></span>
                      <span className="tabular text-fg">
                        {m.kind === "deposit" ? "+" : "−"} {fmtArsaAdmin(m.amount)}
                      </span>
                    </li>))}</ul>}
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}
function Section({ title, children, testid }: { title: string; children: React.ReactNode; testid?: string }) {
  return (
    <section data-testid={testid}>
      <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-1">
        {title}
      </div>
      {children}
    </section>
  );
}
function Empty({ text }: { text: string }) {
  return <div className="text-fg-subtle italic text-[11px]">{text}</div>;
}
