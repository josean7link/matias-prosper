"use client";
import dynamic from "next/dynamic";
import { useState } from "react";
import { FileText } from "lucide-react";
import { toast } from "sonner";
import {
  Document, Page, Text, View, StyleSheet,
} from "@react-pdf/renderer";
import { api } from "@/lib/api";

const styles = StyleSheet.create({
  page: { padding: 36, fontSize: 9, fontFamily: "Helvetica", color: "#0B0F19" },
  cover: { paddingTop: 80, paddingBottom: 80 },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 60 },
  brandBox: { width: 36, height: 36, backgroundColor: "#2563FF", borderRadius: 6,
              alignItems: "center", justifyContent: "center" },
  brandBoxT: { color: "white", fontSize: 22, fontFamily: "Helvetica-Bold" },
  brandText: { fontSize: 22, fontFamily: "Helvetica-Bold" },
  coverKicker: { fontSize: 8, color: "#6B7280", letterSpacing: 2 },
  coverTitle: { fontSize: 34, fontFamily: "Helvetica-Bold", marginTop: 6, lineHeight: 1.1 },
  coverSub: { fontSize: 11, color: "#6B7280", marginTop: 12, fontFamily: "Courier" },
  divider: { borderTopWidth: 1, borderTopColor: "#0B0F19", marginVertical: 24 },
  sectionKicker: { fontSize: 8, color: "#6B7280", letterSpacing: 2, textTransform: "uppercase" },
  sectionTitle: { fontSize: 16, fontFamily: "Helvetica-Bold", marginTop: 4, marginBottom: 14 },
  kpiGrid: { flexDirection: "row", gap: 8, marginBottom: 18 },
  kpiCard: { flex: 1, padding: 12, backgroundColor: "#F2F6FF",
             borderRadius: 6, borderWidth: 1, borderColor: "#E0EAFF" },
  kpiLabel: { fontSize: 7, color: "#6B7280", letterSpacing: 1, textTransform: "uppercase" },
  kpiValue: { fontSize: 15, fontFamily: "Helvetica-Bold", marginTop: 4 },
  kpiHint:  { fontSize: 8, color: "#6B7280", marginTop: 2, fontFamily: "Courier" },
  th: { fontSize: 7, color: "#6B7280", letterSpacing: 1, textTransform: "uppercase",
        borderBottomWidth: 1, borderBottomColor: "#0B0F19", paddingBottom: 4 },
  td: { fontSize: 9, paddingVertical: 5, borderBottomWidth: 0.5, borderBottomColor: "#E0EAFF" },
  tdMono: { fontSize: 9, paddingVertical: 5, fontFamily: "Courier",
            borderBottomWidth: 0.5, borderBottomColor: "#E0EAFF" },
  footer: { position: "absolute", bottom: 20, left: 36, right: 36,
            flexDirection: "row", justifyContent: "space-between",
            fontSize: 7, color: "#6B7280", fontFamily: "Courier",
            borderTopWidth: 0.5, borderTopColor: "#E0EAFF", paddingTop: 6 },
});

const fmt = (n?: number) => n == null
  ? "—"
  : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD",
                                     maximumFractionDigits: 0 }).format(n);

interface ReportData {
  summary: any; breakdown: any; byMonth: any; topClients: any; topYieldClients: any;
  generatedBy: string; generatedAt: string;
}

function Cover({ d }: { d: ReportData }) {
  return (
    <Page size="A4" style={styles.page}>
      <View style={styles.cover}>
        <View style={styles.brandRow}>
          <View style={styles.brandBox}><Text style={styles.brandBoxT}>✦</Text></View>
          <Text style={styles.brandText}>prosper</Text>
        </View>
        <Text style={styles.coverKicker}>EXECUTIVE BUSINESS REPORT</Text>
        <Text style={styles.coverTitle}>Revenue & client{"\n"}performance</Text>
        <Text style={styles.coverSub}>{new Date(d.generatedAt).toLocaleDateString("en-US",
          { year: "numeric", month: "long", day: "numeric" })}</Text>
        <View style={styles.divider} />
        <Text style={{ fontSize: 10, color: "#0B0F19" }}>
          Prepared by · {d.generatedBy}
        </Text>
        <Text style={{ fontSize: 9, color: "#6B7280", marginTop: 6 }}>
          Borderless on-chain financial services
        </Text>
      </View>
      <View style={styles.footer} fixed>
        <Text>prosper · executive report · confidential</Text>
        <Text render={({ pageNumber, totalPages }) => `${pageNumber} / ${totalPages}`} />
      </View>
    </Page>
  );
}

function KpisPage({ d }: { d: ReportData }) {
  const s = d.summary || {};
  return (
    <Page size="A4" style={styles.page}>
      <Text style={styles.sectionKicker}>SECTION 1</Text>
      <Text style={styles.sectionTitle}>Revenue summary</Text>
      <View style={styles.kpiGrid}>
        <Kpi label="Revenue total" value={fmt(s.revenue_total)} hint="Since inception" />
        <Kpi label="Revenue MTD" value={fmt(s.revenue_mtd)}
             hint={s.mom_delta_pct != null ? `${s.mom_delta_pct >= 0 ? '+' : ''}${s.mom_delta_pct}% MoM` : "—"} />
        <Kpi label="Revenue YTD" value={fmt(s.revenue_ytd)}
             hint={s.yoy_delta_pct != null ? `${s.yoy_delta_pct >= 0 ? '+' : ''}${s.yoy_delta_pct}% YoY` : "—"} />
      </View>
      <Text style={styles.sectionKicker}>SECTION 2</Text>
      <Text style={styles.sectionTitle}>Revenue breakdown by concept</Text>
      <View>
        <View style={{ flexDirection: "row" }}>
          <Text style={[styles.th, { flex: 2 }]}>Concept</Text>
          <Text style={[styles.th, { flex: 1, textAlign: "right" }]}>Amount</Text>
          <Text style={[styles.th, { flex: 1, textAlign: "right" }]}>Share</Text>
        </View>
        {(d.breakdown?.items || []).map((it: any) => (
          <View key={it.concept} style={{ flexDirection: "row" }}>
            <Text style={[styles.td, { flex: 2 }]}>{it.concept.replace("_", " ")}</Text>
            <Text style={[styles.tdMono, { flex: 1, textAlign: "right" }]}>{fmt(it.amount)}</Text>
            <Text style={[styles.tdMono, { flex: 1, textAlign: "right" }]}>{it.share_pct}%</Text>
          </View>
        ))}
      </View>
      <View style={styles.footer} fixed>
        <Text>prosper · executive report · confidential</Text>
        <Text render={({ pageNumber, totalPages }) => `${pageNumber} / ${totalPages}`} />
      </View>
    </Page>
  );
}

function ClientsPage({ d }: { d: ReportData }) {
  const top = (d.topClients?.items || []).slice(0, 10);
  return (
    <Page size="A4" style={styles.page}>
      <Text style={styles.sectionKicker}>SECTION 3</Text>
      <Text style={styles.sectionTitle}>Top revenue contributors</Text>
      <View>
        <View style={{ flexDirection: "row" }}>
          <Text style={[styles.th, { flex: 3 }]}>Client</Text>
          <Text style={[styles.th, { flex: 1, textAlign: "right" }]}>Revenue</Text>
        </View>
        {top.map((it: any) => (
          <View key={it.org_id} style={{ flexDirection: "row" }}>
            <Text style={[styles.td, { flex: 3 }]}>{it.name}</Text>
            <Text style={[styles.tdMono, { flex: 1, textAlign: "right" }]}>{fmt(it.revenue)}</Text>
          </View>
        ))}
      </View>
      <View style={{ marginTop: 18 }}>
        <Text style={styles.sectionKicker}>SECTION 4</Text>
        <Text style={styles.sectionTitle}>Top yielding clients</Text>
        <View style={{ flexDirection: "row" }}>
          <Text style={[styles.th, { flex: 3 }]}>Client</Text>
          <Text style={[styles.th, { flex: 1, textAlign: "right" }]}>Principal</Text>
          <Text style={[styles.th, { flex: 1, textAlign: "right" }]}>APR</Text>
          <Text style={[styles.th, { flex: 1, textAlign: "right" }]}>Accrued 30d</Text>
        </View>
        {(d.topYieldClients?.items || []).slice(0, 10).map((it: any) => (
          <View key={it.org_id} style={{ flexDirection: "row" }}>
            <Text style={[styles.td, { flex: 3 }]}>{it.name}</Text>
            <Text style={[styles.tdMono, { flex: 1, textAlign: "right" }]}>{fmt(it.principal_usd)}</Text>
            <Text style={[styles.tdMono, { flex: 1, textAlign: "right" }]}>{it.apr_pct}%</Text>
            <Text style={[styles.tdMono, { flex: 1, textAlign: "right" }]}>{fmt(it.accrued_30d)}</Text>
          </View>
        ))}
      </View>
      <View style={styles.footer} fixed>
        <Text>prosper · executive report · confidential</Text>
        <Text render={({ pageNumber, totalPages }) => `${pageNumber} / ${totalPages}`} />
      </View>
    </Page>
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

function ExecutiveReport({ data }: { data: ReportData }) {
  return (
    <Document title={`prosper · executive report · ${new Date(data.generatedAt).toLocaleDateString()}`}>
      <Cover d={data} />
      <KpisPage d={data} />
      <ClientsPage d={data} />
    </Document>
  );
}

function Btn() {
  const [busy, setBusy] = useState(false);
  const onClick = async () => {
    setBusy(true);
    try {
      const [summary, breakdown, byMonth, topClients, yieldData, me] = await Promise.all([
        api("/v1/admin/business/revenue/summary"),
        api("/v1/admin/business/revenue/breakdown?period=all"),
        api("/v1/admin/business/revenue/by-month?months=12"),
        api("/v1/admin/business/revenue/by-client?limit=10"),
        api("/v1/admin/business/yield/by-client"),
        api<{ user: { email: string } }>("/v1/me"),
      ]);
      const data: ReportData = {
        summary, breakdown, byMonth, topClients,
        topYieldClients: yieldData,
        generatedAt: new Date().toISOString(),
        generatedBy: me.user?.email || "admin",
      };
      const { pdf } = await import("@react-pdf/renderer");
      const blob = await pdf(<ExecutiveReport data={data} />).toBlob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `prosper-executive-${new Date().toISOString().slice(0, 10)}.pdf`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success("Executive report downloaded");
    } catch (err: any) {
      // eslint-disable-next-line no-console
      console.error("PDF report failed", err);
      toast.error(err?.message || "Report generation failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <button onClick={onClick} disabled={busy}
            data-testid="biz-executive-pdf"
            className="prosper-btn-primary h-9 text-xs gap-1.5">
      <FileText size={13} />
      {busy ? "Generating…" : "Executive PDF"}
    </button>
  );
}

export default dynamic(() => Promise.resolve(Btn), { ssr: false });
