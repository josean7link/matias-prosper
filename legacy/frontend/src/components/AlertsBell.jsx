import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Bell, WarningCircle, WarningOctagon, Info } from "@phosphor-icons/react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { relativeTime } from "@/lib/format";

const sevColor = { critical: "var(--danger)", warning: "var(--warning)", info: "var(--primary)" };
const sevIcon = { critical: WarningOctagon, warning: WarningCircle, info: Info };

export default function AlertsBell() {
  const [items, setItems] = useState([]);
  const navigate = useNavigate();

  const load = () => api.get("/alerts?resolved=false")
    .then(({ data }) => setItems(data.items || []))
    .catch(() => {});

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const unread = items.length;
  const hasCritical = items.some((a) => a.severity === "critical");

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          className="relative w-9 h-9 rounded-full border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface-hover)] flex items-center justify-center transition-colors"
          data-testid="alerts-bell"
          aria-label="Alerts"
        >
          <Bell size={15} weight={unread > 0 ? "fill" : "regular"}
                className={unread > 0 ? "text-[var(--fg)]" : "text-[var(--fg-muted)]"} />
          {unread > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full text-[9px] font-mono font-bold flex items-center justify-center"
                  style={{ background: hasCritical ? "var(--danger)" : "var(--warning)", color: "#fff" }}
                  data-testid="alerts-bell-badge">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-0 bg-[var(--surface)] border-[var(--border)] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
          <div className="font-display font-bold">Alerts</div>
          <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--fg-muted)]">{unread} open</span>
        </div>
        <div className="max-h-96 overflow-y-auto">
          {items.length === 0 ? (
            <div className="px-4 py-8 text-center text-xs text-[var(--fg-muted)]">All clear · no open alerts</div>
          ) : (
            items.slice(0, 8).map((a) => {
              const Icon = sevIcon[a.severity] || Info;
              return (
                <div key={a.alert_id}
                     className="px-4 py-3 border-b border-[var(--border)] last:border-0 hover:bg-[var(--surface-hover)] cursor-pointer"
                     onClick={() => navigate("/app/alerts")}
                     data-testid={`alert-bell-item-${a.alert_id}`}>
                  <div className="flex items-start gap-2">
                    <Icon size={14} weight="fill" style={{ color: sevColor[a.severity], marginTop: 2 }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-[var(--fg)]">{a.title}</div>
                      <div className="text-xs text-[var(--fg-muted)] mt-0.5 line-clamp-2">{a.message}</div>
                      <div className="text-[10px] font-mono uppercase tracking-wider text-[var(--fg-subtle)] mt-1">
                        {a.kind} · {relativeTime(a.created_at)}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
        <button onClick={() => navigate("/app/alerts")}
                className="w-full py-2.5 text-center text-xs font-medium text-[var(--primary)] hover:bg-[var(--surface-hover)] border-t border-[var(--border)] transition-colors"
                data-testid="alerts-bell-see-all">
          See all alerts →
        </button>
      </PopoverContent>
    </Popover>
  );
}
