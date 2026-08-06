"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import {
  ResponsiveContainer, PieChart, Pie, Cell, Tooltip, Legend,
} from "recharts";
import { FileText, ScrollText } from "lucide-react";
import { toast } from "sonner";
import {
  useRiskOverview, useRiskClients, useRiskClient,
  generateSar, generateStr, type RiskClient,
} from "@/lib/admin-compliance";
import { cn, fmtMoney, fmtDate } from "@/lib/utils";

const PROFILE_COLOR: Record<string, string> = {
  low:      "#22C55E",
  medium:   "#8DB4FF",
  high:     "#E07B00",
  critical: "#DC2626",
};
const PROFILE_TONE: Record<string, "success" | "info" | "warning" | "danger"> = {
  low: "success", medium: "info", high: "warning", critical: "danger",
};

export default function RiskPage() {
  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");
  const overview = useRiskOverview();
  const all = useRiskClients();
  const [activeId, setActiveId] = useState<string | null>(null);

  const cols: Column<RiskClient>[] = [
    { key: "name", header: "Cliente", sortable: true,
      render: (r) => <span className="text-fg">{r.name}</span> },
    { key: "score", header: "Score", numeric: true, sortable: true, width: "100px", align: "right",
      render: (r) => (
        <div className="inline-flex items-center gap-2 justify-end">
          <span className="font-mono tabular text-fg w-7 text-right">{r.score}</span>
          <div className="w-16 h-1 rounded bg-surface-hover overflow-hidden">
            <div className="h-full" style={{
              width: `${r.score}%`,
              background: PROFILE_COLOR[r.profile] }}/>
          </div>
        </div>
      ) },
    { key: "profile", header: "Profile", width: "100px",
      render: (r) => <Badge tone={PROFILE_TONE[r.profile]} size="sm">{r.profile}</Badge> },
    { key: "drivers", header: "Drivers principales",
      render: (r) => (
        <div className="flex flex-wrap gap-1">
          {r.drivers.slice(0, 3).map((d, i) => (
            <Badge key={i} tone="auto" size="sm">{d.label}</Badge>
          ))}
        </div>) },
    { key: "refreshed_at", header: "Refresh", width: "130px",
      render: (r) => <span className="font-mono text-[11px]">{fmtDate(r.refreshed_at)}</span> },
  ];

  const donutData = Object.entries(overview.data?.distribution ?? {})
    .map(([k, v]) => ({ name: k, value: v }));

  return (
    <div data-testid="compl-risk-page" className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: tA("breadcrumb_admin"), href: "/admin" },
                      { label: tH("comp_label"), href: "/admin/compliance" },
                      { label: tH("comp_risk_bc") }]}
        kicker={tH("comp_risk_kicker")}
        title={tH("comp_risk_title")}
        subtitle={tH("comp_risk_subtitle")} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="prosper-card p-5" data-testid="risk-donut">
          <h3 className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
            Distribución por perfil</h3>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={donutData} dataKey="value" nameKey="name"
                  cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3}>
                  {donutData.map((d) => (
                    <Cell key={d.name} fill={PROFILE_COLOR[d.name] || "#6B7280"} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ background: "rgb(var(--surface))",
                  border: "1px solid rgb(var(--border))", borderRadius: 8,
                  fontSize: 12, fontFamily: "var(--font-plex-mono)" }} />
                <Legend wrapperStyle={{ fontSize: 10, fontFamily: "var(--font-plex-mono)" }}
                        iconType="circle" iconSize={8}/>
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="prosper-card p-5 lg:col-span-2" data-testid="risk-top10">
          <h3 className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-2">
            Top 10 · risk score</h3>
          <table className="w-full text-xs">
            <thead className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              <tr className="border-b border-border">
                <th className="text-left py-2">#</th>
                <th className="text-left py-2">Cliente</th>
                <th className="text-right py-2">Score</th>
                <th className="text-left py-2">Profile</th>
              </tr>
            </thead>
            <tbody>
              {(overview.data?.top10 ?? []).map((r, i) => (
                <tr key={r.org_id} className="border-b border-border last:border-0 cursor-pointer hover:bg-surface-hover"
                    onClick={() => setActiveId(r.org_id)}
                    data-testid={`risk-top-${r.org_id}`}>
                  <td className="py-2 font-mono text-fg-subtle">{i + 1}</td>
                  <td className="py-2">{r.name}</td>
                  <td className="py-2 text-right font-mono tabular">{r.score}</td>
                  <td className="py-2"><Badge tone={PROFILE_TONE[r.profile]} size="sm">{r.profile}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <DataTable<RiskClient>
        data={all.data?.items ?? []} columns={cols}
        rowKey={(r) => r.org_id}
        onRowClick={(r) => setActiveId(r.org_id)}
        empty={all.isLoading ? "Loading…" : "No risk data"} />

      {activeId && <RiskDrawer orgId={activeId} onClose={() => setActiveId(null)} />}
    </div>
  );
}

function RiskDrawer({ orgId, onClose }: { orgId: string; onClose: () => void }) {
  const swr = useRiskClient(orgId);
  const r = swr.data;
  const [sarSummary, setSarSummary] = useState("");
  const [strTxId, setStrTxId] = useState("");
  const [strSummary, setStrSummary] = useState("");

  const onSar = async () => {
    if (!sarSummary.trim()) { toast.error("Resumen requerido"); return; }
    try { const rep = await generateSar({ org_id: orgId, summary: sarSummary });
          downloadJson(rep, `${(rep as any).report_id}.json`);
          toast.success("SAR generated (draft)"); }
    catch (e: any) { toast.error(e?.message || "SAR failed"); }
  };
  const onStr = async () => {
    if (!strTxId.trim() || !strSummary.trim()) { toast.error("TX + resumen required"); return; }
    try { const rep = await generateStr({ tx_id: strTxId.trim(), summary: strSummary });
          downloadJson(rep, `${(rep as any).report_id}.json`);
          toast.success("STR generated (draft)"); }
    catch (e: any) { toast.error(e?.message || "STR failed"); }
  };

  return (
    <div className="fixed inset-0 z-40 flex" data-testid="risk-drawer">
      <div className="flex-1 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="w-full max-w-[720px] bg-bg border-l border-border h-full overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">Risk profile</div>
            <h2 className="font-display font-bold text-xl">{r?.name || "…"}</h2>
            {r && <div className="text-[11px] font-mono text-fg-subtle">
              Score {r.score} · <Badge tone={PROFILE_TONE[r.profile]} size="sm">{r.profile}</Badge>
            </div>}
          </div>
          <button onClick={onClose} className="prosper-btn-ghost h-8 px-3 text-xs"
                  data-testid="risk-drawer-close">Close</button>
        </div>
        {!r ? <div className="text-fg-subtle">Loading…</div> : (
          <div className="space-y-6">
            <section>
              <h3 className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
                Drivers (composición del score)</h3>
              <div className="space-y-2">
                {r.drivers.map((d) => (
                  <div key={d.key} className="prosper-card p-3"
                       data-testid={`risk-driver-${d.key}`}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs">{d.label}</span>
                      <span className="font-mono text-[11px]">
                        <span className="text-fg-subtle">peso {d.weight}%</span>
                        <span className="ml-2 text-fg">+{d.score}pts</span>
                      </span>
                    </div>
                    <div className="h-1 rounded bg-surface-hover overflow-hidden">
                      <div className="h-full bg-primary"
                           style={{ width: `${(d.score / d.weight) * 100}%` }}/>
                    </div>
                  </div>
                ))}
              </div>
            </section>
            <section>
              <h3 className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
                Reportes regulatorios (draft)</h3>
              <div className="prosper-card p-4 space-y-3">
                <div>
                  <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
                    SAR · Suspicious Activity Report (org)
                  </div>
                  <textarea value={sarSummary} onChange={(e) => setSarSummary(e.target.value)}
                    placeholder="Resumen del comportamiento sospechoso"
                    rows={2}
                    data-testid="sar-summary"
                    className="w-full px-3 py-2 rounded border border-border bg-surface text-xs"/>
                  <button onClick={onSar} data-testid="sar-generate"
                    className="prosper-btn-ghost mt-2 h-9 text-xs gap-1.5">
                    <ScrollText size={13}/> Generar SAR draft
                  </button>
                </div>
                <div className="border-t border-border pt-3">
                  <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
                    STR · Suspicious Transaction Report (tx)
                  </div>
                  <input value={strTxId} onChange={(e) => setStrTxId(e.target.value)}
                    placeholder="tx_id"
                    data-testid="str-txid"
                    className="w-full px-3 py-2 rounded border border-border bg-surface font-mono text-xs mb-2"/>
                  <textarea value={strSummary} onChange={(e) => setStrSummary(e.target.value)}
                    placeholder="Resumen de la transacción sospechosa"
                    rows={2}
                    data-testid="str-summary"
                    className="w-full px-3 py-2 rounded border border-border bg-surface text-xs"/>
                  <button onClick={onStr} data-testid="str-generate"
                    className="prosper-btn-ghost mt-2 h-9 text-xs gap-1.5">
                    <FileText size={13}/> Generar STR draft
                  </button>
                </div>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
