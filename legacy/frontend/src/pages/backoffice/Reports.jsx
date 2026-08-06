import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EmptyState } from "@/components/common";
import { fmtDate } from "@/lib/format";
import { DownloadSimple } from "@phosphor-icons/react";

export default function Reports() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get("/reports").then(({ data }) => setItems(data.items || [])); }, []);

  const grouped = items.reduce((acc, r) => { (acc[r.kind] ||= []).push(r); return acc; }, {});

  return (
    <div data-testid="reports-page">
      <PageHeader title="Reports Center" subtitle="NAV, Audit, Performance, Tax" />
      {Object.keys(grouped).length === 0 ? <EmptyState title="No reports" /> : (
        <div className="space-y-6">
          {Object.entries(grouped).map(([kind, list]) => (
            <section key={kind}>
              <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] font-mono mb-2">{kind.replace("_", " ")}</div>
              <div className="prosper-card overflow-hidden">
                <table className="data-table w-full">
                  <thead><tr><th className="text-left px-4 py-3">Period</th><th className="text-left px-4 py-3">Generated</th><th className="text-left px-4 py-3">Status</th><th className="text-right px-4 py-3">Download</th></tr></thead>
                  <tbody>
                    {list.map((r) => (
                      <tr key={r.report_id} data-testid={`report-${r.report_id}`}>
                        <td className="px-4 py-3 font-mono">{r.period}</td>
                        <td className="px-4 py-3 text-xs font-mono text-[var(--fg-muted)]">{fmtDate(r.created_at, true)}</td>
                        <td className="px-4 py-3"><StatusBadge value={r.status} /></td>
                        <td className="px-4 py-3 text-right">
                          <a href={r.download_url || "#"} className="inline-flex items-center gap-1 text-xs text-[var(--primary)] hover:underline">
                            <DownloadSimple size={12} /> Download
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
