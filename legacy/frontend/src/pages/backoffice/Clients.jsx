import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EnvPill, EmptyState } from "@/components/common";
import FormDialog from "@/components/FormDialog";
import ExportButton from "@/components/ExportButton";
import { fmtMoney, fmtDate, fmtNum } from "@/lib/format";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { MagnifyingGlass, Plus } from "@phosphor-icons/react";
import { toast } from "sonner";

export default function Clients() {
  const nav = useNavigate();
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("all");
  const [status, setStatus] = useState("all");
  const [createOpen, setCreateOpen] = useState(false);

  const load = () => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (type !== "all") params.set("type", type);
    if (status !== "all") params.set("status", status);
    api.get(`/organizations?${params}`).then(({ data }) => setItems(data.items || []));
  };

  useEffect(() => { load(); }, [search, type, status]);

  const createOrg = async (values) => {
    const { data } = await api.post("/organizations", values);
    toast.success(`Organization "${data.name}" created`);
    load();
  };

  return (
    <div data-testid="clients-page">
      <PageHeader title="Clients" subtitle={`${items.length} organizations`}
        actions={
          <div className="flex gap-2">
            <ExportButton filename={`clients_${new Date().toISOString().slice(0,10)}`}
                          rows={items.map(o => ({
                            org_id: o.org_id, name: o.name, legal_name: o.legal_name,
                            type: o.type, country: o.country, status: o.status,
                            environment: o.environment, aum_usd: o.aum_usd,
                            active_investors: o.active_investors, created_at: o.created_at,
                          }))}
                          testId="clients-export" />
            <Button onClick={() => setCreateOpen(true)} data-testid="create-client-btn"
                    className="rounded-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white gap-1.5">
              <Plus size={14} weight="bold" /> New Client
            </Button>
          </div>
        }
      />
      <div className="flex gap-3 mb-4">
        <div className="relative flex-1 max-w-xs">
          <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--fg-subtle)]" />
          <Input
            placeholder="Search by name…"
            className="pl-9 bg-[var(--surface)] border-[var(--border)] rounded-md font-mono text-sm"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            data-testid="clients-search"
          />
        </div>
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="w-[180px] bg-[var(--surface)] border-[var(--border)] rounded-md" data-testid="filter-type"><SelectValue placeholder="Type" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            <SelectItem value="partner">Partner</SelectItem>
            <SelectItem value="institutional">Institutional</SelectItem>
            <SelectItem value="internal">Internal</SelectItem>
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-[180px] bg-[var(--surface)] border-[var(--border)] rounded-md" data-testid="filter-status"><SelectValue placeholder="Status" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="suspended">Suspended</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {items.length === 0 ? (
        <EmptyState title="No clients found" message="Try adjusting filters or seed demo data." />
      ) : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead className="border-b border-[var(--border)]">
              <tr>
                <th className="text-left px-4 py-3">Name</th>
                <th className="text-left px-4 py-3">Type</th>
                <th className="text-left px-4 py-3">Country</th>
                <th className="text-left px-4 py-3">Env</th>
                <th className="text-right px-4 py-3">AUM</th>
                <th className="text-right px-4 py-3">Investors</th>
                <th className="text-left px-4 py-3">Status</th>
                <th className="text-left px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody>
              {items.map((o) => (
                <tr key={o.org_id} className="cursor-pointer" onClick={() => nav(`/app/clients/${o.org_id}`)}
                    data-testid={`client-row-${o.org_id}`}>
                  <td className="px-4 py-3 text-[var(--fg)] font-medium">{o.name}</td>
                  <td className="px-4 py-3 text-[var(--fg)] capitalize">{o.type}</td>
                  <td className="px-4 py-3 font-mono text-[var(--fg-muted)]">{o.country || "—"}</td>
                  <td className="px-4 py-3"><EnvPill env={o.environment} /></td>
                  <td className="px-4 py-3 text-right font-mono">{fmtMoney(o.aum_usd)}</td>
                  <td className="px-4 py-3 text-right font-mono">{fmtNum(o.active_investors, 0)}</td>
                  <td className="px-4 py-3"><StatusBadge value={o.status} /></td>
                  <td className="px-4 py-3 text-[var(--fg-muted)] font-mono text-xs">{fmtDate(o.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <FormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New Client Organization"
        description="Create a new partner or institutional client."
        submitLabel="Create Organization"
        onSubmit={createOrg}
        testId="create-client-dialog"
        fields={[
          { key: "name", label: "Commercial Name", required: true, placeholder: "Alemany Capital" },
          { key: "legal_name", label: "Legal Name", placeholder: "Alemany Capital LLC" },
          { key: "type", label: "Type", type: "select", default: "partner", required: true,
            options: [
              { value: "partner", label: "Partner" },
              { value: "institutional", label: "Institutional" },
              { value: "internal", label: "Internal" },
            ]},
          { key: "country", label: "Country (ISO2)", placeholder: "AR", default: "AR" },
          { key: "contact_email", label: "Contact Email", type: "email", required: true },
          { key: "environment", label: "Environment", type: "select", default: "sandbox",
            options: [
              { value: "sandbox", label: "Sandbox" },
              { value: "production", label: "Production" },
            ]},
        ]}
      />
    </div>
  );
}
