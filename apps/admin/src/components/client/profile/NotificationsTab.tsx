"use client";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Bell, Mail, Save } from "lucide-react";
import { api } from "@/lib/api";
import type { Profile, ProfileNotifications } from "@/lib/profile";

interface Props {
  profile: Profile;
  onUpdated: () => void;
}

const ROWS: Array<{
  key: keyof ProfileNotifications;
  group: "email" | "inapp";
  title: string;
  desc: string;
}> = [
  { key: "email_security_alerts",  group: "email", title: "Alertas de seguridad",
    desc: "Avisos sobre logins sospechosos, cambios en MFA y revocaciones de sesión." },
  { key: "email_account_activity", group: "email", title: "Actividad de cuenta",
    desc: "Confirmaciones de cargas, retiros, inversiones y rescates." },
  { key: "email_yield_summary",    group: "email", title: "Resumen de yield",
    desc: "Newsletter semanal con el rendimiento de tus posiciones." },
  { key: "email_marketing",        group: "email", title: "Novedades y productos",
    desc: "Lanzamientos, mejoras y oportunidades de inversión. Sin spam." },
  { key: "inapp_alerts",           group: "inapp", title: "Alertas en la app",
    desc: "Notificaciones críticas (compliance, KYB, alertas operativas)." },
  { key: "inapp_transactions",     group: "inapp", title: "Movimientos en la app",
    desc: "Banners con cada carga / inversión / rescate confirmado." },
];

export function NotificationsTab({ profile, onUpdated }: Props) {
  const [prefs, setPrefs] = useState<ProfileNotifications>(profile.notifications);
  const [busy, setBusy]   = useState(false);

  useEffect(() => { setPrefs(profile.notifications); }, [profile.notifications]);

  const dirty = JSON.stringify(prefs) !== JSON.stringify(profile.notifications);

  const save = async () => {
    setBusy(true);
    try {
      await api("/v1/client/notifications", {
        method: "PATCH",
        body: JSON.stringify(prefs),
      });
      toast.success("Preferencias guardadas");
      onUpdated();
    } catch (err) {
      toast.error((err as Error).message || "Error al guardar");
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-6" data-testid="notifications-tab">
      <Group title="Notificaciones por email" icon={<Mail size={16}/>}
             rows={ROWS.filter((r) => r.group === "email")}
             prefs={prefs} setPrefs={setPrefs} />
      <Group title="Notificaciones en la app" icon={<Bell size={16}/>}
             rows={ROWS.filter((r) => r.group === "inapp")}
             prefs={prefs} setPrefs={setPrefs} />

      <div className="flex justify-end">
        <button onClick={save} disabled={!dirty || busy}
          className="prosper-btn-primary h-10 px-4 text-sm gap-1.5 disabled:opacity-40"
          data-testid="notifications-save">
          <Save size={13}/> {busy ? "Guardando…" : "Guardar preferencias"}
        </button>
      </div>
    </div>
  );
}

function Group({ title, icon, rows, prefs, setPrefs }:
  { title: string; icon: React.ReactNode;
    rows: typeof ROWS;
    prefs: ProfileNotifications;
    setPrefs: (p: ProfileNotifications) => void }) {
  return (
    <section className="prosper-card p-6">
      <h3 className="font-display font-bold text-lg text-fg mb-4 flex items-center gap-2">
        {icon} {title}
      </h3>
      <ul className="space-y-3">
        {rows.map((row) => (
          <li key={row.key} className="flex items-start gap-3 py-2 border-b border-border/40 last:border-0">
            <div className="flex-1">
              <div className="text-sm text-fg font-medium">{row.title}</div>
              <p className="text-xs text-fg-muted mt-0.5">{row.desc}</p>
            </div>
            <Toggle
              checked={prefs[row.key]}
              onChange={(v) => setPrefs({ ...prefs, [row.key]: v })}
              testid={`notif-${row.key}`}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}

function Toggle({ checked, onChange, testid }:
  { checked: boolean; onChange: (v: boolean) => void; testid: string }) {
  return (
    <button onClick={() => onChange(!checked)}
      role="switch" aria-checked={checked}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors shrink-0
                  ${checked ? "bg-primary" : "bg-border"}`}
      data-testid={testid}>
      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform
                        ${checked ? "translate-x-5" : "translate-x-0.5"}`} />
    </button>
  );
}
