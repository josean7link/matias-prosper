import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { PageHeader, StatusBadge, CopyField, EnvPill, EmptyState } from "@/components/common";
import { fmtMoney, fmtCompact, fmtNum } from "@/lib/format";

export default function Funds() {
  const { env } = useApp();
  const [items, setItems] = useState([]);

  useEffect(() => {
    api.get(`/funds?env=${env}`).then(({ data }) => setItems(data.items || []));
  }, [env]);

  return (
    <div data-testid="funds-page">
      <PageHeader title="Funds" subtitle="Tokenized fund assets" />
      {items.length === 0 ? <EmptyState title="No funds" /> : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {items.map((f) => (
            <div key={f.fund_id} className="prosper-card p-6" data-testid={`fund-card-${f.fund_id}`}>
              <div className="flex justify-between items-start mb-4">
                <div>
                  <div className="font-mono text-xs text-[var(--fg-muted)] mb-1">{f.code} · {f.underlying}</div>
                  <div className="font-display font-bold text-2xl">{f.name}</div>
                </div>
                <div className="flex flex-col gap-1 items-end">
                  <EnvPill env={f.environment} />
                  <StatusBadge value={f.status} />
                </div>
              </div>
              <div className="grid grid-cols-3 tight-grid border border-[var(--border)] mb-4">
                <Stat label="NAV / Token" value={fmtNum(f.nav_per_token, 6)} />
                <Stat label="Circulating" value={fmtCompact(f.circulating_supply)} />
                <Stat label="Total Supply" value={fmtCompact(f.total_supply)} />
              </div>
              <div className="space-y-2 text-sm">
                <Row label="Issuer" value={<CopyField value={f.issuer_address} />} />
                <Row label="Treasury" value={<CopyField value={f.treasury_address} />} />
                <Row label="Home Domain" value={<span className="font-mono text-[var(--fg)]">{f.home_domain}</span>} />
                <Row label="Regulator" value={<span className="text-[var(--fg)]">{f.regulator}</span>} />
                <Row label="Rating" value={<span className="text-[var(--fg)]">{f.rating}</span>} />
              </div>
              <div className="mt-4 pt-4 border-t border-[var(--border)]">
                <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] mb-2">Products</div>
                <div className="flex flex-wrap gap-2">
                  {(f.products || []).map((p) => (
                    <span key={p.product_id} className="text-xs px-2 py-1 rounded-sm border border-[var(--border-strong)] font-mono">
                      {p.name} · {(p.apr_bps / 100).toFixed(2)}%
                    </span>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const Stat = ({ label, value }) => (
  <div className="p-4 bg-[var(--surface)]">
    <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] mb-1">{label}</div>
    <div className="font-mono text-base">{value}</div>
  </div>
);
const Row = ({ label, value }) => (
  <div className="flex justify-between items-center">
    <span className="text-[var(--fg-muted)] text-xs uppercase tracking-wider">{label}</span>
    <div>{value}</div>
  </div>
);
