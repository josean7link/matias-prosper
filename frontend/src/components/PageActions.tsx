"use client";
import { RefreshCw } from "lucide-react";

export function RefreshButton() {
  return (
    <button
      onClick={() => window.location.reload()}
      className="prosper-btn-ghost h-9 text-xs gap-1.5"
      data-testid="page-action-refresh"
    >
      <RefreshCw size={13} />
      Refresh
    </button>
  );
}
