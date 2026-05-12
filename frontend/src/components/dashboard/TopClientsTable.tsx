"use client";
import { DataTable, type Column } from "@prosper/ui";
import { fmtMoney, fmtNum } from "@/lib/utils";
import type { TopClient } from "@/lib/dashboard";

const cols: Column<TopClient>[] = [
  { key: "name", header: "Client", sortable: true },
  {
    key: "aum",
    header: "AUM",
    numeric: true,
    sortable: true,
    render: (r) => fmtMoney(r.aum),
  },
  {
    key: "positions_count",
    header: "Positions",
    numeric: true,
    sortable: true,
    render: (r) => fmtNum(r.positions_count),
  },
];

export function TopClientsTable({ data, loading }: { data: TopClient[]; loading?: boolean }) {
  return (
    <DataTable<TopClient>
      data={loading ? [] : data}
      columns={cols}
      rowKey={(r) => r.org_id}
      empty={loading ? "Loading…" : "No active clients yet"}
    />
  );
}
