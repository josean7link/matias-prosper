import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/common";
import { fmtDate } from "@/lib/format";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";

const ROLES = ["super_admin", "ops", "compliance", "finance", "client_admin", "client_user", "developer", "viewer"];

export default function UsersAdmin() {
  const [users, setUsers] = useState([]);
  const load = () => api.get("/users").then(({ data }) => setUsers(data.items || []));
  useEffect(() => { load(); }, []);

  const updateRole = async (id, role) => {
    await api.patch(`/users/${id}`, { platform_role: role });
    toast.success("Role updated");
    load();
  };

  return (
    <div data-testid="users-admin-page">
      <PageHeader title="Users & Roles" subtitle={`${users.length} platform users`} />
      {users.length === 0 ? <EmptyState title="No users yet" /> : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">User</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Internal</th>
              <th className="text-left px-4 py-3">Role</th>
              <th className="text-left px-4 py-3">Created</th>
            </tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.user_id} data-testid={`user-row-${u.user_id}`}>
                  <td className="px-4 py-3 flex items-center gap-2">
                    {u.picture && <img src={u.picture} alt="" className="w-6 h-6 rounded-full border border-[var(--border-strong)]" />}
                    <span>{u.name}</span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[var(--fg)]">{u.email}</td>
                  <td className="px-4 py-3 text-xs">
                    <span className={u.is_internal ? "text-[var(--success)]" : "text-[var(--fg-muted)]"}>
                      {u.is_internal ? "internal" : "external"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <Select value={u.platform_role} onValueChange={(v) => updateRole(u.user_id, v)}>
                      <SelectTrigger className="w-[160px] h-7 bg-[var(--surface)] border-[var(--border)] rounded-md text-xs" data-testid={`role-${u.user_id}`}>
                        <SelectValue /></SelectTrigger>
                      <SelectContent>
                        {ROLES.map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="px-4 py-3 text-xs font-mono text-[var(--fg-muted)]">{fmtDate(u.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
