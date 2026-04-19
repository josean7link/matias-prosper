import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EnvPill, MetricBar, MetricCell, CopyField } from "@/components/common";
import { fmtMoney, fmtNum, fmtDate } from "@/lib/format";
import { ArrowLeft } from "@phosphor-icons/react";

export default function ClientDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [org, setOrg] = useState(null);
  const [positions, setPositions] = useState([]);
  const [txs, setTxs] = useState([]);
  const [keys, setKeys] = useState([]);

  useEffect(() => {
    api.get(`/organizations/${id}`).then(({ data }) => setOrg(data));
    api.get(`/positions?org_id=${id}`).then(({ data }) => setPositions(data.items || []));
    api.get(`/transactions?org_id=${id}&limit=20`).then(({ data }) => setTxs(data.items || []));
    api.get(`/integrations/keys?org_id=${id}`).then(({ data }) => setKeys(data.items || []));
  }, [id]);

  if (!org) return <div className="text-[#888] font-mono text-sm">Loading client…</div>;

  return (
    <div data-testid="client-detail-page">
      <button onClick={() => nav(-1)} className="flex items-center gap-2 text-xs text-[#888] hover:text-white mb-4 font-mono uppercase tracking-wider" data-testid="back-button">
        <ArrowLeft size={12} /> Back
      </button>
      <PageHeader
        title={org.name}
        subtitle={`${org.legal_name || ""} · ${org.country || ""} · ${org.type}`}
        actions={<StatusBadge value={org.status} />}
      />
      <MetricBar>
        <MetricCell label="AUM" value={fmtMoney(org.aum_usd)} />
        <MetricCell label="Investors" value={fmtNum(org.active_investors, 0)} />
        <MetricCell label="API Apps" value={org.counts?.apps ?? 0} />
        <MetricCell label="Active Keys" value={org.counts?.keys ?? 0} />
        <MetricCell label="Webhooks" value={org.counts?.hooks ?? 0} />
        <MetricCell label="Transactions" value={fmtNum(org.counts?.tx ?? 0, 0)} />
      </MetricBar>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-6">
        <section className="prosper-card p-5">
          <div className="text-[10px] uppercase tracking-wider text-[#888] mb-3">Contact</div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-[#888]">Email</span><span>{org.contact_email || "—"}</span></div>
            <div className="flex justify-between"><span className="text-[#888]">Country</span><span>{org.country || "—"}</span></div>
            <div className="flex justify-between"><span className="text-[#888]">Environment</span><EnvPill env={org.environment} /></div>
            <div className="flex justify-between"><span className="text-[#888]">Created</span><span className="font-mono text-xs">{fmtDate(org.created_at)}</span></div>
          </div>
        </section>

        <section className="prosper-card p-5">
          <div className="text-[10px] uppercase tracking-wider text-[#888] mb-3">API Keys</div>
          {keys.length === 0 ? <div className="text-sm text-[#555]">No keys issued</div> :
            <div className="space-y-2">
              {keys.slice(0, 5).map((k) => (
                <div key={k.key_id} className="flex items-center justify-between py-2 border-b border-[#1a1a1a] last:border-0">
                  <div>
                    <div className="text-sm text-white">{k.label}</div>
                    <CopyField value={k.key_prefix} testId={`key-${k.key_id}`} />
                  </div>
                  <StatusBadge value={k.status} />
                </div>
              ))}
            </div>
          }
        </section>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-3">
        <section className="prosper-card p-5">
          <div className="text-[10px] uppercase tracking-wider text-[#888] mb-3">Recent Positions</div>
          <table className="data-table w-full">
            <thead><tr><th className="text-left">Product</th><th className="text-right">Principal</th><th className="text-right">Accrued</th><th className="text-left">Status</th></tr></thead>
            <tbody>
              {positions.slice(0, 6).map((p) => (
                <tr key={p.position_id}>
                  <td className="py-2 font-mono text-xs">{p.product_id.slice(0, 14)}…</td>
                  <td className="py-2 text-right font-mono">{fmtMoney(p.principal)}</td>
                  <td className="py-2 text-right font-mono text-[#00C853]">{fmtMoney(p.accrued_interest)}</td>
                  <td className="py-2"><StatusBadge value={p.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="prosper-card p-5">
          <div className="text-[10px] uppercase tracking-wider text-[#888] mb-3">Recent Transactions</div>
          <table className="data-table w-full">
            <thead><tr><th className="text-left">Type</th><th className="text-right">Amount</th><th className="text-left">Status</th><th className="text-left">Created</th></tr></thead>
            <tbody>
              {txs.slice(0, 6).map((t) => (
                <tr key={t.tx_id}>
                  <td className="py-2 capitalize text-sm">{t.type}</td>
                  <td className="py-2 text-right font-mono">{fmtMoney(t.amount)}</td>
                  <td className="py-2"><StatusBadge value={t.status} /></td>
                  <td className="py-2 text-xs font-mono text-[#888]">{fmtDate(t.created_at, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
