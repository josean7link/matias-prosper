import { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EnvPill, EmptyState } from "@/components/common";
import { fmtDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { CheckCircle, XCircle, WarningCircle, ArrowsClockwise, Lightning } from "@phosphor-icons/react";
import { toast } from "sonner";

export default function Integrations() {
  const [apps, setApps] = useState([]);
  useEffect(() => { api.get("/integrations/apps").then(({ data }) => setApps(data.items || [])); }, []);

  return (
    <div data-testid="integrations-page">
      <PageHeader title="Integrations" subtitle={`${apps.length} API apps across partners`} />

      <ProsperUpstreamCard />

      {apps.length === 0 ? <EmptyState title="No apps" /> : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {apps.map((a) => (
            <div key={a.app_id} className="prosper-card p-5" data-testid={`app-${a.app_id}`}>
              <div className="flex justify-between items-start mb-3">
                <div className="font-display font-bold text-lg">{a.name}</div>
                <EnvPill env={a.environment} />
              </div>
              <div className="text-sm text-[var(--fg-muted)] mb-3">{a.description}</div>
              <div className="flex justify-between items-center pt-3 border-t border-[var(--border)]">
                <span className="font-mono text-xs text-[var(--fg-subtle)]">{fmtDate(a.created_at)}</span>
                <StatusBadge value={a.status} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ProsperUpstreamCard() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [lastCheck, setLastCheck] = useState(null);
  const [forbidden, setForbidden] = useState(false);

  const check = useCallback(async (silent = false) => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/prosper-upstream");
      setStatus(data);
      setLastCheck(new Date());
      if (!silent) toast.success("Upstream status refreshed");
    } catch (e) {
      if (e?.response?.status === 403) {
        setForbidden(true);
      } else if (!silent) {
        toast.error("Could not reach the diagnostic endpoint");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { check(true); }, [check]);

  if (forbidden) return null;

  const { light, title, subtitle } = describe(status);

  return (
    <div className="prosper-card p-5 mb-6" data-testid="prosper-upstream-card">
      <div className="flex items-start gap-4">
        <LightIndicator light={light} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Lightning size={14} weight="duotone" className="text-[var(--primary)]" />
            <div className="text-[10px] uppercase tracking-[0.15em] text-[var(--fg-muted)] font-mono">
              Prosper Stellar Rail · Upstream
            </div>
          </div>
          <div className="font-display font-bold text-lg" data-testid="upstream-title">{title}</div>
          <div className="text-sm text-[var(--fg-muted)] mt-1">{subtitle}</div>

          {status && (
            <dl className="grid grid-cols-2 md:grid-cols-4 gap-0 tight-grid border border-[var(--border)] mt-4">
              <Stat label="Enabled" value={<BoolPill v={status.enabled} trueLabel="ON" falseLabel="OFF" />} />
              <Stat label="Reachable" value={<BoolPill v={status.reachable} />} testId="upstream-reachable" />
              <Stat label="Authenticated" value={<BoolPill v={status.authenticated} />} testId="upstream-authenticated" />
              <Stat label="Last Check" value={lastCheck ? lastCheck.toLocaleTimeString() : "—"} mono />
            </dl>
          )}

          {status?.base_url && (
            <div className="text-xs text-[var(--fg-subtle)] font-mono mt-3 break-all">
              {status.base_url}
            </div>
          )}
          {status?.error && (
            <div className="text-xs text-[var(--danger)] font-mono mt-2 break-all" data-testid="upstream-error">
              {status.error}
            </div>
          )}
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => check(false)}
          disabled={loading}
          className="h-8 rounded-sm gap-1 text-xs"
          data-testid="upstream-refresh-btn"
        >
          <ArrowsClockwise size={12} className={loading ? "animate-spin" : ""} />
          {loading ? "Checking" : "Re-check"}
        </Button>
      </div>
    </div>
  );
}

function describe(s) {
  if (!s) return { light: "neutral", title: "Upstream status unknown", subtitle: "Running first check…" };
  if (!s.enabled) {
    return {
      light: "amber",
      title: "Proxy disabled (demo / simulated mode)",
      subtitle: "PROSPER_API_ENABLED=false in backend/.env — every mint/deposit/withdraw is simulated. Enable it once the network egress is open.",
    };
  }
  if (s.authenticated) {
    return {
      light: "green",
      title: "Connected & authenticated",
      subtitle: "The real Prosper Stellar API is reachable and a JWT was minted. All upstream calls will be proxied.",
    };
  }
  if (s.reachable) {
    return {
      light: "amber",
      title: "Reachable, login failing",
      subtitle: "The upstream responded but the /v1/Auth/Login call did not mint a token. Check PROSPER_API_USER / PROSPER_API_PASS.",
    };
  }
  return {
    light: "red",
    title: "Upstream unreachable",
    subtitle: "DNS or network egress appears blocked. Ask your infra team to open outbound traffic to the Prosper host.",
  };
}

function LightIndicator({ light }) {
  const map = {
    green:   { bg: "var(--success)", Icon: CheckCircle },
    amber:   { bg: "var(--warning)", Icon: WarningCircle },
    red:     { bg: "var(--danger)",  Icon: XCircle },
    neutral: { bg: "var(--fg-muted)", Icon: WarningCircle },
  };
  const { bg, Icon } = map[light] || map.neutral;
  return (
    <div
      className="w-11 h-11 rounded-full flex items-center justify-center shrink-0"
      style={{ background: `${bg}25`, color: bg }}
      data-testid={`upstream-light-${light}`}
    >
      <Icon size={22} weight="duotone" />
    </div>
  );
}

function BoolPill({ v, trueLabel = "YES", falseLabel = "NO" }) {
  return (
    <span
      className="inline-flex font-mono text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full"
      style={{
        background: v ? "color-mix(in srgb, var(--success) 18%, transparent)" : "color-mix(in srgb, var(--danger) 18%, transparent)",
        color: v ? "var(--success)" : "var(--danger)",
      }}
    >
      {v ? trueLabel : falseLabel}
    </span>
  );
}

function Stat({ label, value, mono = false, testId }) {
  return (
    <div className="p-3 bg-[var(--surface)]" data-testid={testId}>
      <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] mb-1 font-mono">{label}</div>
      <div className={mono ? "font-mono text-xs" : "text-sm"}>{value}</div>
    </div>
  );
}
