"use client";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { Download } from "lucide-react";
import { toast } from "sonner";
import {
  Document, Page, Text, View, StyleSheet,
} from "@react-pdf/renderer";
import type {
  DashboardKpis, NavPoint, RevenuePoint, TopClient,
} from "@/lib/dashboard";

// `pdf` from @react-pdf/renderer is the imperative API. We lazy-load it on
// click so the heavy bundle isn't shipped on the initial /admin payload.
// We deliberately use built-in Helvetica (no Font.register) — custom CDN fonts
// regularly fail with 'Offset is outside the bounds of the DataView' in
// browser environments.

const styles = StyleSheet.create({
  page: { padding: 28, fontSize: 9, fontFamily: "Helvetica", color: "#0B0F19" },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start",
            borderBottomWidth: 1, borderBottomColor: "#0B0F19", paddingBottom: 10, marginBottom: 16 },
  brandWrap: { flexDirection: "row", alignItems: "center", gap: 8 },
  logoBox: { width: 24, height: 24, backgroundColor: "#2563FF",
             alignItems: "center", justifyContent: "center", borderRadius: 5 },
  logoText: { color: "#FFFFFF", fontSize: 13, fontFamily: "Helvetica-Bold" },
  brand: { fontSize: 17, fontFamily: "Helvetica-Bold", marginLeft: 6, color: "#0B0F19" },
  kicker: { fontSize: 7, color: "#6B7280", letterSpacing: 1.2 },
  title: { fontSize: 18, fontFamily: "Helvetica-Bold", marginTop: 2 },
  metaCol: { textAlign: "right" },
  metaLine: { fontSize: 8, color: "#6B7280", fontFamily: "Courier" },

  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 16 },
  kpiCard: { width: "32%", padding: 8, backgroundColor: "#F2F6FF",
             borderRadius: 4, borderWidth: 1, borderColor: "#E0EAFF" },
  kpiLabel: { fontSize: 7, color: "#6B7280", letterSpacing: 1 },
  kpiValue: { fontSize: 13, fontFamily: "Helvetica-Bold", marginTop: 3 },
  kpiHint: { fontSize: 7, color: "#6B7280", marginTop: 2, fontFamily: "Courier" },

  section: { marginTop: 6, marginBottom: 14 },
  sectionTitle: { fontSize: 10, fontFamily: "Helvetica-Bold", marginBottom: 6, color: "#0B0F19" },

  tableRow: { flexDirection: "row", borderBottomWidth: 0.5, borderBottomColor: "#E0EAFF", paddingVertical: 5 },
  tableHead: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: "#0B0F19", paddingVertical: 4 },
  tCell: { fontSize: 9 },
  tCellMono: { fontSize: 9, fontFamily: "Courier" },
  tCellHead: { fontSize: 7, color: "#6B7280", letterSpacing: 1 },

  footer: { position: "absolute", bottom: 18, left: 28, right: 28, flexDirection: "row",
            justifyContent: "space-between", fontSize: 7, color: "#6B7280",
            borderTopWidth: 0.5, borderTopColor: "#E0EAFF", paddingTop: 6, fontFamily: "Courier" },
});

const fmt = (n: number | null | undefined, currency = true) => {
  if (n == null || isNaN(n as number)) return "—";
  return currency
    ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n)
    : new Intl.NumberFormat("en-US").format(n);
};

interface ReportProps {
  generatedAt: string;
  generatedBy: string;
  kpis?: DashboardKpis;
  navLast?: NavPoint;
  revenue: RevenuePoint[];
  topClients: TopClient[];
}

function DashboardReport({ generatedAt, generatedBy, kpis, navLast, revenue, topClients }: ReportProps) {
  const reportDate = new Date(generatedAt).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
  return (
    <Document title={`Prosper · Admin Dashboard · ${reportDate}`} author="Prosper Foundation">
      <Page size="A4" style={styles.page}>
        <View style={styles.header}>
          <View>
            <View style={styles.brandWrap}>
              <View style={styles.logoBox}><Text style={styles.logoText}>✦</Text></View>
              <Text style={styles.brand}>prosper</Text>
            </View>
            <Text style={[styles.kicker, { marginTop: 6 }]}>BORDERLESS ON-CHAIN FINANCIAL SERVICES</Text>
            <Text style={styles.title}>Daily Operations Snapshot</Text>
          </View>
          <View style={styles.metaCol}>
            <Text style={styles.metaLine}>Generated: {reportDate}</Text>
            <Text style={styles.metaLine}>By: {generatedBy}</Text>
            <Text style={styles.metaLine}>Environment: PRODUCTION</Text>
          </View>
        </View>

        <View style={styles.kpiGrid}>
          <Kpi label="AUM (USD)" value={fmt(kpis?.aum_usd)}
               hint={kpis?.aum_delta_24h != null ? `${(kpis.aum_delta_24h * 100).toFixed(2)}% 24h` : "24h"} />
          <Kpi label="NAV" value={(navLast?.nav ?? kpis?.nav ?? 1).toFixed(6)}
               hint={kpis?.nav_delta_24h != null ? `${(kpis.nav_delta_24h * 100).toFixed(2)}% 24h` : "24h"} />
          <Kpi label="Revenue · MTD" value={fmt(kpis?.revenue_mtd)} hint={`YTD ${fmt(kpis?.revenue_ytd)}`} />
          <Kpi label="Volume · 30d" value={fmt(kpis?.volume_30d)} hint="subscribe + redeem" />
          <Kpi label="Active Clients" value={String(kpis?.active_clients ?? "—")} hint="with open positions" />
          <Kpi label="Ops Queue" value={String(kpis?.operations_queue ?? "—")} hint="pending approvals" />
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Top Clients by AUM</Text>
          <View style={styles.tableHead}>
            <Text style={[styles.tCellHead, { width: "50%" }]}>Client</Text>
            <Text style={[styles.tCellHead, { width: "30%", textAlign: "right" }]}>AUM</Text>
            <Text style={[styles.tCellHead, { width: "20%", textAlign: "right" }]}>Positions</Text>
          </View>
          {topClients.length === 0 ? (
            <Text style={[styles.tCell, { color: "#5B6478", paddingVertical: 8 }]}>No active clients</Text>
          ) : topClients.slice(0, 10).map((c) => (
            <View style={styles.tableRow} key={c.org_id}>
              <Text style={[styles.tCell, { width: "50%" }]}>{c.name}</Text>
              <Text style={[styles.tCellMono, { width: "30%", textAlign: "right" }]}>{fmt(c.aum)}</Text>
              <Text style={[styles.tCellMono, { width: "20%", textAlign: "right" }]}>{c.positions_count}</Text>
            </View>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Revenue · last 12 months</Text>
          <View style={styles.tableHead}>
            <Text style={[styles.tCellHead, { width: "50%" }]}>Month</Text>
            <Text style={[styles.tCellHead, { width: "50%", textAlign: "right" }]}>Fee revenue</Text>
          </View>
          {revenue.length === 0 ? (
            <Text style={[styles.tCell, { color: "#5B6478", paddingVertical: 8 }]}>No revenue this period</Text>
          ) : revenue.map((r) => (
            <View style={styles.tableRow} key={r.month}>
              <Text style={[styles.tCellMono, { width: "50%" }]}>{r.month}</Text>
              <Text style={[styles.tCellMono, { width: "50%", textAlign: "right" }]}>{fmt(r.revenue)}</Text>
            </View>
          ))}
        </View>

        <View style={styles.footer} fixed>
          <Text>prosper · borderless on-chain financial services</Text>
          <Text render={({ pageNumber, totalPages }) => `Page ${pageNumber} / ${totalPages}`} />
        </View>
      </Page>
    </Document>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <View style={styles.kpiCard}>
      <Text style={styles.kpiLabel}>{label}</Text>
      <Text style={styles.kpiValue}>{value}</Text>
      {hint && <Text style={styles.kpiHint}>{hint}</Text>}
    </View>
  );
}

interface BtnProps extends ReportProps {}

export function ExportPdfButton(props: BtnProps) {
  const [busy, setBusy] = useState(false);
  const doc = useMemo(() => <DashboardReport {...props} />, [props]);

  const onClick = async () => {
    setBusy(true);
    try {
      const { pdf } = await import("@react-pdf/renderer");
      const blob = await pdf(doc).toBlob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `prosper-admin-${new Date().toISOString().slice(0, 10)}.pdf`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success("Dashboard PDF downloaded");
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("PDF export failed", err);
      toast.error("PDF export failed — check console for details");
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="prosper-btn-ghost h-9 text-xs gap-1.5"
      data-testid="dashboard-export-pdf"
    >
      <Download size={13} className={busy ? "animate-pulse" : undefined} />
      {busy ? "Generating…" : "Export PDF"}
    </button>
  );
}

// Avoid SSR for this component (uses browser APIs)
export default dynamic(() => Promise.resolve(ExportPdfButton), { ssr: false });
