"use client";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Camera, Save, Trash2, User as UserIcon } from "lucide-react";
import { Badge } from "@prosper/ui";
import { api } from "@/lib/api";
import {
  LANGUAGE_OPTIONS, TIMEZONE_OPTIONS,
  type Profile,
} from "@/lib/profile";

const KYB_TONE: Record<string, "success" | "warning" | "info" | "danger"> = {
  approved:   "success",
  pending:    "warning",
  needs_info: "warning",
  in_review:  "info",
  rejected:   "danger",
};

interface Props {
  profile: Profile;
  orgInfo: {
    org_id: string;
    legal_name?: string;
    commercial_name?: string;
    country?: string;
    kyb_status: string;
    env: string;
    tier: string;
    kyb_reject_reason?: string | null;
  } | null;
  onUpdated: () => void;
}

export function AccountTab({ profile, orgInfo, onUpdated }: Props) {
  const [fullName, setFullName] = useState(profile.full_name);
  const [phone, setPhone]       = useState(profile.phone);
  const [language, setLanguage] = useState<Profile["language"]>(profile.language);
  const [timezone, setTimezone] = useState(profile.timezone);
  const [saving, setSaving]     = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setFullName(profile.full_name);
    setPhone(profile.phone);
    setLanguage(profile.language);
    setTimezone(profile.timezone);
  }, [profile]);

  const dirty =
    fullName !== profile.full_name ||
    phone    !== profile.phone    ||
    language !== profile.language ||
    timezone !== profile.timezone;

  const onSave = async () => {
    setSaving(true);
    try {
      await api("/v1/client/profile", {
        method: "PATCH",
        body: JSON.stringify({ full_name: fullName, phone, language, timezone }),
      });
      toast.success("Datos guardados");
      onUpdated();
    } catch (err) {
      toast.error((err as Error).message || "Error al guardar");
    } finally {
      setSaving(false);
    }
  };

  const onAvatar = async (f: File) => {
    if (f.size > 256 * 1024) {
      toast.error("La imagen supera 256 KB. Probá una más liviana.");
      return;
    }
    setUploadingAvatar(true);
    try {
      const dataUrl: string = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload  = () => res(r.result as string);
        r.onerror = () => rej(new Error("Error leyendo archivo"));
        r.readAsDataURL(f);
      });
      await api("/v1/client/avatar", {
        method: "POST",
        body: JSON.stringify({ data_url: dataUrl }),
      });
      toast.success("Avatar actualizado");
      onUpdated();
    } catch (err) {
      toast.error((err as Error).message || "Error subiendo avatar");
    } finally {
      setUploadingAvatar(false);
    }
  };

  const onRemoveAvatar = async () => {
    try {
      await api("/v1/client/avatar", { method: "DELETE" });
      toast.success("Avatar eliminado");
      onUpdated();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  return (
    <div className="space-y-6" data-testid="account-tab">
      {/* Avatar */}
      <section className="prosper-card p-6">
        <h3 className="font-display font-bold text-lg text-fg mb-1">Foto de perfil</h3>
        <p className="text-xs text-fg-muted mb-4">PNG o JPG hasta 256 KB.</p>
        <div className="flex items-center gap-5">
          <div className="h-20 w-20 rounded-full bg-surface border border-border overflow-hidden grid place-items-center"
               data-testid="avatar-preview">
            {profile.avatar_url ? (
              <img src={profile.avatar_url} alt="" className="h-full w-full object-cover" />
            ) : (
              <UserIcon size={28} className="text-fg-subtle" />
            )}
          </div>
          <div className="flex flex-col gap-2">
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && onAvatar(e.target.files[0])}
              data-testid="avatar-file" />
            <button onClick={() => fileRef.current?.click()}
              disabled={uploadingAvatar}
              className="prosper-btn-primary h-9 px-3 text-xs gap-1.5 disabled:opacity-50"
              data-testid="avatar-upload-btn">
              <Camera size={13}/> {uploadingAvatar ? "Subiendo…" : "Cambiar foto"}
            </button>
            {profile.avatar_url && (
              <button onClick={onRemoveAvatar}
                className="text-[11px] text-danger hover:underline self-start"
                data-testid="avatar-remove-btn">
                Eliminar foto
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Personal data */}
      <section className="prosper-card p-6">
        <h3 className="font-display font-bold text-lg text-fg mb-4">Datos personales</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Nombre completo">
            <input
              value={fullName} onChange={(e) => setFullName(e.target.value)}
              maxLength={80}
              className="prosper-input w-full h-10 text-sm"
              placeholder="Nombre y apellido"
              data-testid="profile-fullname" />
          </Field>
          <Field label="Teléfono">
            <input
              value={phone} onChange={(e) => setPhone(e.target.value)}
              maxLength={24}
              className="prosper-input w-full h-10 text-sm"
              placeholder="+54 11 5555-1234"
              data-testid="profile-phone" />
          </Field>
          <Field label="Email">
            <input value={profile.email} disabled
              className="prosper-input w-full h-10 text-sm opacity-60 cursor-not-allowed"
              data-testid="profile-email" />
            <p className="text-[10px] text-fg-subtle mt-1">El email no se puede modificar — contactá soporte.</p>
          </Field>
          <Field label="Rol">
            <input value={profile.role} disabled
              className="prosper-input w-full h-10 text-sm font-mono opacity-60 cursor-not-allowed"
              data-testid="profile-role" />
          </Field>

          <Field label="Idioma">
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value as Profile["language"])}
              className="prosper-input w-full h-10 text-sm"
              data-testid="profile-language">
              {LANGUAGE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Zona horaria">
            <select
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className="prosper-input w-full h-10 text-sm"
              data-testid="profile-timezone">
              {TIMEZONE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </Field>
        </div>

        <div className="mt-5 flex justify-end">
          <button onClick={onSave} disabled={!dirty || saving}
            className="prosper-btn-primary h-10 px-4 text-sm gap-1.5 disabled:opacity-40"
            data-testid="profile-save">
            <Save size={13}/> {saving ? "Guardando…" : "Guardar cambios"}
          </button>
        </div>
      </section>

      {/* Organization (read-only) */}
      {orgInfo && (
        <section className="prosper-card p-6" data-testid="org-card">
          <div className="flex items-start justify-between gap-3 mb-4">
            <div>
              <h3 className="font-display font-bold text-lg text-fg">
                {orgInfo.commercial_name || orgInfo.legal_name || orgInfo.org_id}
              </h3>
              {orgInfo.legal_name && orgInfo.commercial_name && (
                <p className="text-xs text-fg-muted mt-1">Razón social · {orgInfo.legal_name}</p>
              )}
            </div>
            <Badge tone={KYB_TONE[orgInfo.kyb_status] || "default"}>
              KYB · {orgInfo.kyb_status}
            </Badge>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-x-6 gap-y-3 text-sm">
            <DataRow label="Org ID"  value={orgInfo.org_id} mono />
            <DataRow label="País"    value={orgInfo.country || "—"} />
            <DataRow label="Tier"    value={orgInfo.tier} />
            <DataRow label="Entorno" value={orgInfo.env} mono />
          </div>
          {orgInfo.kyb_status === "rejected" && orgInfo.kyb_reject_reason && (
            <div className="border border-danger/30 bg-danger/5 rounded p-3 mt-4"
                 data-testid="kyb-reject-reason">
              <div className="text-[10px] font-mono uppercase tracking-wider text-danger mb-1">
                Motivo de rechazo
              </div>
              <p className="text-xs text-fg">{orgInfo.kyb_reject_reason}</p>
            </div>
          )}
          <p className="text-[11px] text-fg-subtle mt-4">
            Los datos de la organización los gestiona el equipo de Prosper.
            Escribinos a <a className="text-primary hover:underline"
                            href="mailto:support@prosper.foundation">support@prosper.foundation</a>.
          </p>
        </section>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
        {label}
      </div>
      {children}
    </label>
  );
}

function DataRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
        {label}
      </div>
      <div className={`${mono ? "font-mono" : ""} text-sm text-fg break-all`}>{value}</div>
    </div>
  );
}
