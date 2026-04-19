import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EnvPill, EmptyState } from "@/components/common";
import { fmtMoney, fmtDate, fmtNum } from "@/lib/format";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { MagnifyingGlass } from "@phosphor-icons/react";

export default function Clients() {
  const nav = useNavigate();
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("all");
  const [status, setStatus] = useState("all");

  useEffect(() => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (type !== "all") params.set("type", type);
    if (status !== "all") params.set("status", status);
    api.get(`/organizations?${params}`).then(({ data }) => setItems(data.items || []));
  }, [search, type, status]);

  return (
    <div data-testid="clients-page">
      <PageHeader title="Clients" subtitle={`${items.length} organizations`} />
      <div className="flex gap-3 mb-4">
        <div className="relative flex-1 max-w-xs">
          <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#555]" />
          <Input
            placeholder="Search by name…"
            className="pl-9 bg-[#0a0a0a] border-[#1a1a1a] rounded-sm font-mono text-sm"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            data-testid="clients-search"
          />
        </div>
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="w-[180px] bg-[#0a0a0a] border-[#1a1a1a] rounded-sm" data-testid="filter-type"><SelectValue placeholder="Type" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            <SelectItem value="partner">Partner</SelectItem>
            <SelectItem value="institutional">Institutional</SelectItem>
            <SelectItem value="internal">Internal</SelectItem>
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-[180px] bg-[#0a0a0a] border-[#1a1a1a] rounded-sm" data-testid="filter-status"><SelectValue placeholder="Status" /></SelectTrigger>
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
            <thead className="border-b border-[#1a1a1a]">
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
                  <td className="px-4 py-3 text-white font-medium">{o.name}</td>
                  <td className="px-4 py-3 text-[#ccc] capitalize">{o.type}</td>
                  <td className="px-4 py-3 font-mono text-[#888]">{o.country || "—"}</td>
                  <td className="px-4 py-3"><EnvPill env={o.environment} /></td>
                  <td className="px-4 py-3 text-right font-mono">{fmtMoney(o.aum_usd)}</td>
                  <td className="px-4 py-3 text-right font-mono">{fmtNum(o.active_investors, 0)}</td>
                  <td className="px-4 py-3"><StatusBadge value={o.status} /></td>
                  <td className="px-4 py-3 text-[#888] font-mono text-xs">{fmtDate(o.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
