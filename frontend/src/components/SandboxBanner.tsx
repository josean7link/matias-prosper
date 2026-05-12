"use client";
import { AlertTriangle, X } from "lucide-react";
import { useState } from "react";
import { useEnvOptional } from "@/contexts/EnvContext";

/**
 * Persistent yellow banner shown on every Admin page while env === "sandbox".
 * Non-dismissable across reloads — only collapsible per-session so the user
 * keeps awareness that real money is NOT flowing.
 *
 * Renders nothing in surfaces that do not wrap children in <EnvProvider>
 * (eg the client portal).
 */
export function SandboxBanner() {
  const envCtx = useEnvOptional();
  const [collapsed, setCollapsed] = useState(false);
  if (!envCtx || envCtx.env !== "sandbox") return null;
  const { setEnv } = envCtx;

  return (
    <div
      role="alert"
      className="w-full border-b border-warning/40 bg-warning/10"
      data-testid="sandbox-banner"
    >
      <div className="mx-auto max-w-[1440px] px-6 py-2 flex items-center gap-3">
        <span className="inline-flex w-2 h-2 rounded-full bg-warning animate-pulse" />
        <AlertTriangle size={14} className="text-warning shrink-0" />
        <div className="flex-1 text-xs sm:text-sm text-warning">
          <span className="font-mono uppercase tracking-[0.18em] font-semibold">
            Sandbox
          </span>
          <span className="text-fg-muted ml-2">
            {collapsed ? null : (
              <>
                · No-real-funds environment. Transactions are simulated and the
                upstream Stellar rail is mocked.
              </>
            )}
          </span>
        </div>
        <button
          onClick={() => setEnv("production")}
          className="text-[11px] font-mono uppercase tracking-wider text-warning hover:underline shrink-0"
          data-testid="sandbox-banner-switch"
        >
          Switch to production
        </button>
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="text-fg-muted hover:text-fg p-1 rounded shrink-0"
          aria-label={collapsed ? "Expand banner" : "Collapse banner"}
          data-testid="sandbox-banner-toggle"
        >
          <X size={13} className={collapsed ? "rotate-45 transition-transform" : "transition-transform"} />
        </button>
      </div>
    </div>
  );
}
