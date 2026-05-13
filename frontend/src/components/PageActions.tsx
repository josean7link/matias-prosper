"use client";
import { RefreshCw } from "lucide-react";

export function RefreshButton({ onClick }: { onClick?: () => void } = {}) {
  return (
    <button
      onClick={onClick ?? (() => window.location.reload())}
      className="prosper-btn-ghost h-9 text-xs gap-1.5"
      data-testid="page-action-refresh"
    >
      <RefreshCw size={13} />
      Refresh
    </button>
  );
}
