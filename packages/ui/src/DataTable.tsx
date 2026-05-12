"use client";
import { useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

export interface Column<T> {
  key: keyof T & string;
  header: string;
  align?: "left" | "right";
  numeric?: boolean;     // forces right alignment + mono font
  sortable?: boolean;
  render?: (row: T) => React.ReactNode;
  width?: string;
}

export interface DataTableProps<T> {
  data: T[];
  columns: Column<T>[];
  rowKey?: (row: T) => string;
  empty?: string;
  className?: string;
}

export function DataTable<T extends Record<string, unknown>>({
  data, columns, rowKey, empty = "No data yet", className,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const sorted = (() => {
    if (!sortKey) return data;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sortable) return data;
    const copy = [...data];
    copy.sort((a, b) => {
      const av = a[sortKey] as unknown as number | string;
      const bv = b[sortKey] as unknown as number | string;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return av - bv;
      return String(av).localeCompare(String(bv));
    });
    if (sortDir === "desc") copy.reverse();
    return copy;
  })();

  const onHeaderClick = (col: Column<T>) => {
    if (!col.sortable) return;
    if (sortKey === col.key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(col.key); setSortDir("asc"); }
  };

  return (
    <div className={`prosper-card overflow-hidden ${className || ""}`} data-testid="data-table">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface sticky top-0">
            <tr className="border-b border-border">
              {columns.map((c) => {
                const right = c.numeric || c.align === "right";
                const isSorted = sortKey === c.key;
                return (
                  <th
                    key={c.key}
                    onClick={() => onHeaderClick(c)}
                    style={c.width ? { width: c.width } : undefined}
                    className={[
                      "px-4 py-3 text-[10px] font-mono uppercase tracking-wider text-fg-subtle font-semibold",
                      right ? "text-right" : "text-left",
                      c.sortable ? "cursor-pointer hover:text-fg select-none" : "",
                    ].join(" ")}
                  >
                    <span className="inline-flex items-center gap-1">
                      {c.header}
                      {c.sortable && (
                        isSorted
                          ? sortDir === "asc" ? <ArrowUp size={11} /> : <ArrowDown size={11} />
                          : <ArrowUpDown size={11} className="opacity-40" />
                      )}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-12 text-center text-fg-subtle text-sm">
                  {empty}
                </td>
              </tr>
            ) : sorted.map((row, idx) => (
              <tr
                key={rowKey ? rowKey(row) : idx}
                className="border-b border-border last:border-0 hover:bg-surface-hover transition-colors"
              >
                {columns.map((c) => {
                  const right = c.numeric || c.align === "right";
                  return (
                    <td
                      key={c.key}
                      className={[
                        "px-4 py-3 text-fg",
                        right ? "text-right" : "text-left",
                        c.numeric ? "font-mono tabular" : "",
                      ].join(" ")}
                    >
                      {c.render ? c.render(row) : String(row[c.key] ?? "")}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
