"use client";
import { useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import type { Profile } from "@/lib/profile";

interface Props {
  profile: Profile;
  onUpdated: () => void;
}

export function DangerTab({ profile, onUpdated }: Props) {
  const [showModal, setShowModal] = useState(false);
  const [busy, setBusy] = useState(false);

  const cancelDeletion = async () => {
    if (!window.confirm("¿Cancelar la solicitud de eliminación?")) return;
    setBusy(true);
    try {
      await api("/v1/client/account/cancel-deletion", { method: "POST" });
      toast.success("Solicitud de eliminación cancelada");
      onUpdated();
    } catch (err) {
      toast.error((err as Error).message || "Error al cancelar");
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-6" data-testid="danger-tab">
      {profile.deletion_requested ? (
        <section className="prosper-card p-6 border-warning/40 bg-warning/5"
                 data-testid="deletion-pending-card">
          <div className="flex items-start gap-3 mb-4">
            <AlertTriangle size={20} className="text-warning shrink-0 mt-0.5"/>
            <div>
              <h3 className="font-display font-bold text-lg text-fg">
                Solicitud de eliminación pendiente
              </h3>
              <p className="text-sm text-fg-muted mt-1">
                Tu cuenta será eliminada el{" "}
                <span className="font-mono text-fg">
                  {profile.deletion_effective_at
                    ? new Date(profile.deletion_effective_at).toLocaleString()
                    : "—"}
                </span>.
              </p>
              <p className="text-xs text-fg-muted mt-2">
                Mientras tanto seguís pudiendo operar normalmente.
                Si cambiás de opinión, podés cancelar la solicitud.
              </p>
            </div>
          </div>
          <div className="flex justify-end">
            <button onClick={cancelDeletion} disabled={busy}
              className="prosper-btn-primary h-10 px-4 text-sm gap-1.5 disabled:opacity-40"
              data-testid="cancel-deletion-btn">
              <X size={13}/> {busy ? "Cancelando…" : "Cancelar eliminación"}
            </button>
          </div>
        </section>
      ) : (
        <section className="prosper-card p-6 border-danger/40">
          <h3 className="font-display font-bold text-lg text-fg flex items-center gap-2 mb-2">
            <Trash2 size={18} className="text-danger"/> Eliminar cuenta
          </h3>
          <p className="text-sm text-fg-muted mb-4 max-w-xl">
            La eliminación entra en un período de gracia de 7 días. Durante ese tiempo
            podés cancelarla. Al cabo del plazo, tu cuenta personal se desactiva y tus
            datos quedan bajo retención legal según las normas regulatorias aplicables.
          </p>
          <div className="rounded-lg bg-bg-muted border border-border p-3 text-xs text-fg-muted mb-4">
            <p className="font-medium text-fg mb-1">Importante</p>
            <ul className="list-disc list-inside space-y-1">
              <li>Si tenés posiciones activas, escribinos primero a soporte para redimir.</li>
              <li>Tu organización ({profile.org_id}) NO se elimina — sólo tu usuario.</li>
              <li>Los logs de auditoría se preservan por compliance.</li>
            </ul>
          </div>
          <div className="flex justify-end">
            <button onClick={() => setShowModal(true)}
              className="prosper-btn-ghost h-10 px-4 text-sm gap-1.5 text-danger hover:bg-danger/5 border border-danger/40"
              data-testid="request-deletion-btn">
              <Trash2 size={13}/> Solicitar eliminación
            </button>
          </div>
        </section>
      )}

      {showModal && <DeletionModal email={profile.email}
                                     onClose={() => setShowModal(false)}
                                     onRequested={() => { setShowModal(false); onUpdated(); }} />}
    </div>
  );
}

function DeletionModal({ email, onClose, onRequested }:
  { email: string; onClose: () => void; onRequested: () => void }) {
  const [confirm, setConfirm] = useState("");
  const [reason, setReason]   = useState("");
  const [busy, setBusy]       = useState(false);

  const valid = confirm.trim().toLowerCase() === email.toLowerCase();

  const submit = async () => {
    setBusy(true);
    try {
      const res = await api<{ ok: true; effective_at: string; message: string }>(
        "/v1/client/account/request-deletion",
        { method: "POST",
          body: JSON.stringify({ confirm_email: confirm, reason }) });
      toast.success(res.message || "Solicitud registrada");
      onRequested();
    } catch (err) {
      toast.error((err as Error).message || "Error al solicitar eliminación");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-bg/70 backdrop-blur-sm z-50 grid place-items-center p-4"
         onClick={onClose} data-testid="deletion-modal">
      <div className="prosper-card p-6 w-full max-w-md"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle size={18} className="text-danger"/>
          <h2 className="font-display font-bold text-lg text-fg">¿Eliminar tu cuenta?</h2>
        </div>
        <p className="text-xs text-fg-muted mb-4">
          Se aplicará un período de gracia de 7 días antes de la eliminación efectiva.
          Para confirmar, escribí tu email tal cual lo tenés registrado.
        </p>

        <label className="block mb-3">
          <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
            Tu email
          </div>
          <input value={confirm} onChange={(e) => setConfirm(e.target.value)}
            className="prosper-input w-full h-10 text-sm" placeholder={email}
            data-testid="deletion-confirm-email" />
        </label>

        <label className="block mb-5">
          <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
            Motivo (opcional)
          </div>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)}
            maxLength={400} rows={3}
            className="prosper-input w-full text-sm py-2"
            placeholder="Nos ayuda a mejorar. No es obligatorio."
            data-testid="deletion-reason" />
        </label>

        <div className="flex gap-2">
          <button onClick={onClose}
            className="prosper-btn-ghost flex-1 h-10 text-sm" data-testid="deletion-cancel">
            Cancelar
          </button>
          <button onClick={submit} disabled={!valid || busy}
            className="prosper-btn-primary flex-1 h-10 text-sm disabled:opacity-40 bg-danger hover:bg-danger/90"
            data-testid="deletion-confirm">
            {busy ? "Procesando…" : "Solicitar eliminación"}
          </button>
        </div>
      </div>
    </div>
  );
}
