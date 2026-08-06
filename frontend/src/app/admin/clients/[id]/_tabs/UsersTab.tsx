"use client";
import { useState } from "react";
import { toast } from "sonner";
import { UserPlus, X, ShieldCheck } from "lucide-react";
import { Badge } from "@prosper/ui";
import {
  useClientUsers, inviteUser, patchUser, revokeUser, makeLink,
} from "@/lib/admin-clients";
import { cn, fmtDate } from "@/lib/utils";

export default function UsersTab({ orgId }: { orgId: string }) {
  const swr = useClientUsers(orgId);
  const [showInvite, setShowInvite] = useState(false);
  const [draft, setDraft] = useState({ email: "", full_name: "", role: "client_user" });
  const items = swr.data?.items ?? [];

  const send = async () => {
    if (!draft.email) return toast.error("Email requerido");
    try {
      const res: any = await inviteUser(orgId, { ...draft, send_email: true });
      toast.success(`Usuario invitado · link ${res.invite_link.slice(0, 60)}…`);
      setShowInvite(false); setDraft({ email: "", full_name: "", role: "client_user" });
      await swr.mutate();
    } catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  const changeRole = async (uid: string, role: string) => {
    try { await patchUser(orgId, uid, { role }); await swr.mutate(); toast.success("Rol actualizado"); }
    catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  const revoke = async (uid: string) => {
    if (!confirm("¿Revocar acceso de este usuario?")) return;
    try { await revokeUser(orgId, uid); await swr.mutate(); toast.success("Acceso revocado"); }
    catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  const sendReset = async (email: string) => {
    try { await makeLink(orgId, "reset_password", { email, send_email: true });
          toast.success("Link de reset enviado"); }
    catch (e: any) { toast.error(e?.message || "Failed"); }
  };

  return (
    <div data-testid="tab-content-users" className="space-y-3">
      <div className="flex justify-end">
        <button onClick={() => setShowInvite((v) => !v)}
          data-testid="users-invite-btn"
          className="prosper-btn-primary h-9 text-xs gap-1.5">
          <UserPlus size={12}/> Invitar usuario
        </button>
      </div>
      {showInvite && (
        <div className="prosper-card p-4" data-testid="users-invite-form">
          <div className="grid grid-cols-3 gap-3">
            <input placeholder="email" value={draft.email}
              onChange={(e) => setDraft({...draft, email: e.target.value})}
              data-testid="invite-email"
              className="h-9 px-3 rounded border border-border bg-surface font-mono text-xs"/>
            <input placeholder="nombre" value={draft.full_name}
              onChange={(e) => setDraft({...draft, full_name: e.target.value})}
              data-testid="invite-name"
              className="h-9 px-3 rounded border border-border bg-surface text-xs"/>
            <select value={draft.role}
              onChange={(e) => setDraft({...draft, role: e.target.value})}
              data-testid="invite-role"
              className="h-9 px-3 rounded border border-border bg-surface text-xs">
              <option value="client_admin">client_admin</option>
              <option value="client_user">client_user</option>
            </select>
          </div>
          <div className="flex justify-end gap-2 mt-2">
            <button onClick={() => setShowInvite(false)} className="prosper-btn-ghost h-8 text-xs">Cancel</button>
            <button onClick={send} data-testid="invite-send"
              className="prosper-btn-primary h-8 text-xs">Enviar invitación</button>
          </div>
        </div>
      )}

      <table className="w-full text-xs">
        <thead className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
          <tr className="border-b border-border">
            <th className="text-left py-2">Usuario</th>
            <th className="text-left py-2">Rol</th>
            <th className="text-left py-2">Status</th>
            <th className="text-left py-2">MFA</th>
            <th className="text-left py-2">Último login</th>
            <th className="text-left py-2 w-32">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {items.map((u) => (
            <tr key={u.user_id} className="border-b border-border" data-testid={`user-row-${u.user_id}`}>
              <td className="py-2">
                <div>{u.full_name || u.email}</div>
                <div className="text-[10px] text-fg-subtle font-mono">{u.email}</div>
              </td>
              <td className="py-2">
                <select value={u.role}
                  onChange={(e) => changeRole(u.user_id, e.target.value)}
                  data-testid={`user-role-${u.user_id}`}
                  className="bg-surface border border-border rounded px-2 py-1 font-mono text-[10px]">
                  <option value="client_admin">client_admin</option>
                  <option value="client_user">client_user</option>
                </select>
              </td>
              <td className="py-2">
                <Badge size="sm"
                  tone={u.status === "active" ? "success" :
                         u.status === "revoked" ? "danger" : "warning"}>
                  {u.status}</Badge>
              </td>
              <td className="py-2">{u.mfa_enabled
                ? <ShieldCheck size={12} className="text-success"/>
                : <span className="text-fg-subtle text-[10px]">off</span>}</td>
              <td className="py-2 font-mono text-[10px]">{u.last_login_at ? fmtDate(u.last_login_at) : "—"}</td>
              <td className="py-2 flex gap-1.5">
                <button onClick={() => sendReset(u.email)}
                  data-testid={`user-reset-${u.user_id}`}
                  className="text-[10px] text-primary hover:underline">reset</button>
                <button onClick={() => revoke(u.user_id)}
                  data-testid={`user-revoke-${u.user_id}`}
                  className="text-[10px] text-danger hover:underline">revoke</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
