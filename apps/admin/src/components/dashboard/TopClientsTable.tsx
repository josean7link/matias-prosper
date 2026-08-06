"use client";
import { useTranslations } from "next-intl";
import { DataTable, type Column } from "@prosper/ui";
import { fmtMoney, fmtNum } from "@/lib/utils";
import type { TopClient } from "@/lib/dashboard";

export function TopClientsTable({ data, loading }: { data: TopClient[]; loading?: boolean }) {
  const t = useTranslations("admin.top_clients_table");
  const cols: Column<TopClient>[] = [
    { key: "name", header: t("col_client"), sortable: true },
    {
      key: "aum",
      header: t("col_aum"),
      numeric: true,
      sortable: true,
      render: (r) => fmtMoney(r.aum),
    },
    {
      key: "positions_count",
      header: t("col_positions"),
      numeric: true,
      sortable: true,
      render: (r) => fmtNum(r.positions_count),
    },
  ];
  return (
    <DataTable<TopClient>
      data={loading ? [] : data}
      columns={cols}
      rowKey={(r) => r.org_id}
      empty={loading ? t("loading") : t("empty")}
    />
  );
}
