"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Bell } from "lucide-react";
import { useAlertsSummary } from "@/lib/admin-compliance";
import { cn, fmtDate } from "@/lib/utils";

export default function AlertsBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const swr = useAlertsSummary();
  const count = swr.data?.open_count ?? 0;
  const crit  = swr.data?.open_critical_count ?? 0;

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((v) => !v)}
        className="prosper-btn-ghost h-9 w-9 p-0 relative"
        aria-label="Notifications"
        data-testid="alerts-bell">
        <Bell size={16} />
        {count > 0 && (
          <span
            data-testid="alerts-bell-count"
            className={cn(
              "absolute -top-0.5 -right-0.5 min-w-[16px] h-[16px] rounded-full px-1",
              "text-[9px] font-mono tabular flex items-center justify-center text-white",
              crit > 0 ? "bg-danger" : "bg-primary",
            )}>
            {crit > 0 ? crit : count}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-80 z-30 prosper-card p-2
                        shadow-card-hover animate-fade-in"
             data-testid="alerts-bell-menu">
          <div className="px-2 py-1.5 flex items-center justify-between border-b border-border mb-1">
            <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              Alertas abiertas
            </span>
            <span className="text-[10px] font-mono text-fg-subtle">
              {count} open{crit > 0 ? ` · ${crit} crit` : ""}
            </span>
          </div>
          <div className="max-h-72 overflow-y-auto space-y-1">
            {(swr.data?.latest ?? []).length === 0 && (
              <div className="text-fg-subtle text-xs px-2 py-3 text-center">Sin alertas abiertas</div>
            )}
            {(swr.data?.latest ?? []).map((a) => (
              <Link key={a.alert_id} href="/admin/compliance/alerts"
                onClick={() => setOpen(false)}
                data-testid={`bell-item-${a.alert_id}`}
                className="block px-2 py-1.5 rounded hover:bg-surface-hover">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-fg truncate flex-1">{a.title}</span>
                  <span className={cn(
                    "ml-2 px-1.5 py-0.5 rounded-full text-[9px] font-mono uppercase tracking-wider shrink-0",
                    a.severity === "critical" && "bg-danger/15 text-danger",
                    a.severity === "warning"  && "bg-warning/15 text-warning",
                    a.severity === "info"     && "bg-primary/15 text-primary",
                  )}>{a.severity}</span>
                </div>
                <div className="text-[10px] text-fg-subtle font-mono mt-0.5">
                  {a.type} · {fmtDate(a.created_at)}
                </div>
              </Link>
            ))}
          </div>
          <div className="border-t border-border mt-1 pt-1">
            <Link href="/admin/compliance/alerts"
              onClick={() => setOpen(false)}
              className="block px-2 py-1.5 rounded text-center text-[11px] font-mono
                         uppercase tracking-wider text-primary hover:bg-surface-hover">
              Ver todas
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
