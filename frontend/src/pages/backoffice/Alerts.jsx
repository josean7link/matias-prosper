import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/common";
import { fmtDate, relativeTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { WarningCircle, Info, WarningOctagon } from "@phosphor-icons/react";

const sevIcon = { critical: WarningOctagon, warning: WarningCircle, info: Info };
const sevColor = { critical: "#FF3D00", warning: "#FFAB00", info: "#0066FF" };

export default function Alerts() {
  const [items, setItems] = useState([]);
  const load = () => api.get("/alerts").then(({ data }) => setItems(data.items || []));
  useEffect(() => { load(); }, []);

  const resolve = async (id) => {
    await api.post(`/alerts/${id}/resolve`);
    toast.success("Alert resolved");
    load();
  };

  return (
    <div data-testid="alerts-page">
      <PageHeader title="Alerts Center" subtitle={`${items.filter(i=>!i.resolved).length} open`} />
      {items.length === 0 ? <EmptyState title="All clear" message="No alerts at this time." /> : (
        <div className="space-y-2">
          {items.map((a) => {
            const Icon = sevIcon[a.severity] || Info;
            return (
              <div key={a.alert_id}
                   className="prosper-card p-4 flex items-start gap-4"
                   data-testid={`alert-${a.alert_id}`}>
                <Icon size={20} weight="fill" style={{ color: sevColor[a.severity] }} />
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color: sevColor[a.severity] }}>
                      {a.severity} · {a.kind}
                    </span>
                    <span className="text-xs text-[#555]">{relativeTime(a.created_at)}</span>
                  </div>
                  <div className="font-medium text-white mt-1">{a.title}</div>
                  <div className="text-sm text-[#888] mt-1">{a.message}</div>
                </div>
                {!a.resolved && (
                  <Button size="sm" onClick={() => resolve(a.alert_id)}
                          className="bg-transparent border border-[#222] hover:bg-[#111] text-xs rounded-sm"
                          data-testid={`resolve-alert-${a.alert_id}`}>
                    Resolve
                  </Button>
                )}
                {a.resolved && <span className="text-xs font-mono text-[#00C853] uppercase tracking-wider">Resolved</span>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
