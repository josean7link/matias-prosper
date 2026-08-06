"use client";
import { useState } from "react";
import { toast } from "sonner";
import {
  Monitor, Smartphone, Tablet, LogOut, Trash2, ShieldAlert, Clock,
} from "lucide-react";
import { Badge } from "@prosper/ui";
import { api } from "@/lib/api";
import { useSessions, type Session } from "@/lib/profile";

interface Props {
  onSelfRevoked?: () => void;
}

export function SessionsTab({ onSelfRevoked }: Props) {
  const { data, isLoading, mutate } = useSessions();
  const sessions = data?.items ?? [];
  const [revokingId, setRevoking] = useState<string | null>(null);
  const [revokeAllBusy, setRevokeAllBusy] = useState(false);

  const revoke = async (sid: string, isCurrent: boolean) => {
    if (!window.confirm(isCurrent
        ? "¿Cerrar esta sesión? Vas a tener que volver a entrar."
        : "¿Cerrar esta sesión?")) return;
    setRevoking(sid);
    try {
      await api(`/v1/client/sessions/${sid}`, { method: "DELETE" });
      toast.success("Sesión cerrada");
      if (isCurrent) {
        onSelfRevoked?.();
        window.location.href = "/access";
        return;
      }
      mutate();
    } catch (err) {
      toast.error((err as Error).message || "Error al cerrar sesión");
    } finally { setRevoking(null); }
  };

  const revokeAll = async () => {
    if (!window.confirm("Vamos a cerrar TODAS las demás sesiones. ¿Continuar?")) return;
    setRevokeAllBusy(true);
    try {
      const res = await api<{ ok: true; revoked: number }>(
        "/v1/client/sessions/revoke-others", { method: "POST" });
      toast.success(res.revoked > 0
        ? `${res.revoked} sesión${res.revoked === 1 ? "" : "es"} cerrada${res.revoked === 1 ? "" : "s"}`
        : "No había otras sesiones activas");
      mutate();
    } catch (err) {
      toast.error((err as Error).message || "Error al cerrar sesiones");
    } finally { setRevokeAllBusy(false); }
  };

  const otherCount = sessions.filter((s) => !s.is_current).length;

  return (
    <div className="space-y-5" data-testid="sessions-tab">
      <section className="prosper-card p-6">
        <div className="flex items-start justify-between gap-4 mb-5">
          <div>
            <h3 className="font-display font-bold text-lg text-fg flex items-center gap-2">
              <ShieldAlert size={18} className="text-primary"/> Sesiones activas
            </h3>
            <p className="text-xs text-fg-muted mt-1 max-w-md">
              Dispositivos donde tu cuenta está conectada. Cerrá las que no reconozcas.
            </p>
          </div>
          {otherCount > 0 && (
            <button onClick={revokeAll} disabled={revokeAllBusy}
              className="prosper-btn-ghost h-9 px-3 text-xs gap-1.5 text-danger hover:bg-danger/5 disabled:opacity-40"
              data-testid="sessions-revoke-all">
              <LogOut size={12}/> {revokeAllBusy ? "Cerrando…" : "Cerrar las demás"}
            </button>
          )}
        </div>

        {isLoading ? (
          <div className="h-24 animate-pulse bg-bg-muted rounded" />
        ) : sessions.length === 0 ? (
          <p className="text-sm text-fg-muted text-center py-8">Sin sesiones activas.</p>
        ) : (
          <ul className="space-y-3" data-testid="sessions-list">
            {sessions.map((s) => (
              <SessionRow key={s.session_id} s={s}
                          onRevoke={() => revoke(s.session_id, s.is_current)}
                          busy={revokingId === s.session_id} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function SessionRow({ s, onRevoke, busy }:
  { s: Session; onRevoke: () => void; busy: boolean }) {
  const Icon = deviceIcon(s.user_agent);
  return (
    <li className="flex items-center gap-4 p-3 rounded-lg border border-border hover:bg-surface-hover transition"
        data-testid={`session-${s.session_id}`}>
      <div className="shrink-0 h-10 w-10 rounded-lg bg-surface flex items-center justify-center">
        <Icon size={18} className="text-fg-muted" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-display font-semibold text-fg">{s.label}</span>
          {s.is_current && (
            <Badge tone="success" size="sm" data-testid={`session-current-${s.session_id}`}>
              Esta sesión
            </Badge>
          )}
        </div>
        <div className="text-[11px] text-fg-subtle font-mono mt-0.5 truncate">
          IP {s.ip} · creada {formatRel(s.created_at)} · vista {formatRel(s.last_seen_at)}
        </div>
        <div className="text-[10px] text-fg-subtle truncate mt-0.5" title={s.user_agent}>
          {s.user_agent || "User-agent desconocido"}
        </div>
      </div>
      <button onClick={onRevoke} disabled={busy}
        className="prosper-btn-ghost h-9 px-3 text-xs text-danger hover:bg-danger/5 disabled:opacity-40 gap-1.5 shrink-0"
        data-testid={`session-revoke-${s.session_id}`}>
        <Trash2 size={12}/> {busy ? "…" : (s.is_current ? "Cerrar y salir" : "Cerrar")}
      </button>
    </li>
  );
}

function deviceIcon(ua: string) {
  const s = ua.toLowerCase();
  if (s.includes("iphone") || s.includes("android") || s.includes("mobile")) return Smartphone;
  if (s.includes("ipad") || s.includes("tablet")) return Tablet;
  return Monitor;
}

function formatRel(iso: string): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60)      return `hace ${Math.floor(diff)}s`;
  if (diff < 3600)    return `hace ${Math.floor(diff / 60)}m`;
  if (diff < 86400)   return `hace ${Math.floor(diff / 3600)}h`;
  if (diff < 30 * 86400) return `hace ${Math.floor(diff / 86400)}d`;
  return new Date(iso).toLocaleDateString();
}
