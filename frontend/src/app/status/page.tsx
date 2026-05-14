"use client";
import useSWR from "swr";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  CheckCircle2, AlertTriangle, XCircle, Clock, RefreshCw,
} from "lucide-react";
import { api } from "@/lib/api";
import { PublicFooter } from "@/components/PublicFooter";

type ServiceStatus = "operational" | "degraded" | "outage";

interface Service {
  id: string;
  name: string;
  status: ServiceStatus;
  detail?: string;
}

interface StatusResponse {
  overall: ServiceStatus;
  services: Service[];
  checked_at: string;
  version: string;
}

const STATUS_META: Record<ServiceStatus, { label: string; tone: string; ring: string; Icon: typeof CheckCircle2 }> = {
  operational: { label: "Operativo",  tone: "text-success",  ring: "bg-success/10 border-success/30", Icon: CheckCircle2 },
  degraded:    { label: "Degradado",  tone: "text-warning",  ring: "bg-warning/10 border-warning/30", Icon: AlertTriangle },
  outage:      { label: "Caído",      tone: "text-danger",   ring: "bg-danger/10 border-danger/30",   Icon: XCircle },
};

export default function StatusPage() {
  const { data, isLoading, mutate } = useSWR<StatusResponse>(
    "/v1/status", (p: string) => api(p),
    { refreshInterval: 30_000 });
  const [lastSync, setLastSync] = useState<string>("");

  useEffect(() => {
    if (data) setLastSync(new Date(data.checked_at).toLocaleString());
  }, [data]);

  const overall = data?.overall ?? "operational";
  const m = STATUS_META[overall];

  return (
    <div className="min-h-screen bg-bg flex flex-col" data-testid="status-page">
      {/* Header */}
      <header className="border-b border-border">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-5 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-full bg-primary/10 grid place-items-center text-primary">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
                <path d="M12 2c-1.5 3.5-5 4-5 7s3.5 3.5 5 7c1.5-3.5 5-4 5-7s-3.5-3.5-5-7z"/>
              </svg>
            </div>
            <span className="font-display font-bold text-fg lowercase tracking-tight">prosper</span>
          </Link>
          <button onClick={() => mutate()}
            className="prosper-btn-ghost h-9 px-3 text-xs gap-1.5"
            data-testid="status-refresh">
            <RefreshCw size={12}/> Refrescar
          </button>
        </div>
      </header>

      {/* Overall banner */}
      <section className={`border-b border-border ${m.ring.replace("border", "bg")}/30`}>
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10 flex flex-col items-center text-center">
          <div className={`h-14 w-14 rounded-full grid place-items-center mb-3 ${m.ring}`}>
            <m.Icon size={28} className={m.tone}/>
          </div>
          <h1 className="font-display font-bold text-2xl sm:text-3xl text-fg mb-1"
              data-testid="status-overall">
            {overall === "operational" && "Todos los sistemas operativos"}
            {overall === "degraded"    && "Algunos servicios degradados"}
            {overall === "outage"      && "Estamos investigando un incidente"}
          </h1>
          <p className="text-sm text-fg-muted">
            Última verificación · <span className="font-mono">{lastSync || "—"}</span>
            {data?.version && <> · v{data.version}</>}
          </p>
        </div>
      </section>

      {/* Services grid */}
      <section className="flex-1">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10">
          <h2 className="font-display font-bold text-lg text-fg mb-4">
            Estado por componente
          </h2>
          {isLoading ? (
            <div className="prosper-card p-6 animate-pulse h-40" />
          ) : (
            <ul className="prosper-card divide-y divide-border overflow-hidden"
                data-testid="status-list">
              {data?.services.map((s) => {
                const sm = STATUS_META[s.status];
                return (
                  <li key={s.id}
                      className="px-5 py-4 flex items-center justify-between gap-4"
                      data-testid={`status-${s.id}`}>
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                      <sm.Icon size={18} className={sm.tone + " shrink-0"} />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-display font-semibold text-fg">{s.name}</div>
                        {s.detail && (
                          <div className="text-[11px] text-fg-subtle font-mono mt-0.5 truncate">
                            {s.detail}
                          </div>
                        )}
                      </div>
                    </div>
                    <span className={`text-xs font-mono uppercase tracking-wider ${sm.tone}`}>
                      {sm.label}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}

          <div className="mt-8 prosper-card p-5 flex items-start gap-3"
               data-testid="status-incidents">
            <Clock size={16} className="text-fg-subtle shrink-0 mt-0.5"/>
            <div className="text-xs text-fg-muted">
              <p className="font-medium text-fg mb-1">Historial de incidentes</p>
              <p>Sin incidentes reportados en los últimos 90 días. Los reportes históricos
              se publican acá apenas se resuelve cada incidente.</p>
            </div>
          </div>

          <div className="mt-4 text-center text-[11px] text-fg-subtle">
            ¿Querés que te avisemos cuando haya cambios? Escribinos a{" "}
            <a className="text-primary hover:underline"
               href="mailto:status@prosper.foundation">status@prosper.foundation</a>.
          </div>
        </div>
      </section>

      <PublicFooter />
    </div>
  );
}
