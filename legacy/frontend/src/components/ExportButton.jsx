import { Button } from "@/components/ui/button";
import { DownloadSimple } from "@phosphor-icons/react";
import { downloadCsv } from "@/lib/csv";

export default function ExportButton({ filename, rows, columns, disabled, testId = "export-csv" }) {
  const handle = () => {
    if (!rows || rows.length === 0) return;
    downloadCsv(filename, rows, columns);
  };
  return (
    <Button onClick={handle} disabled={disabled || !rows || rows.length === 0}
            variant="outline"
            className="rounded-full border-[var(--border)] gap-1.5 h-9"
            data-testid={testId}>
      <DownloadSimple size={14} weight="bold" /> Export CSV
    </Button>
  );
}
