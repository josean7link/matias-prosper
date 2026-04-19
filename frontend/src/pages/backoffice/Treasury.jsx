import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { PageHeader, StatusBadge, CopyField } from "@/components/common";
import { fmtMoney, fmtNum } from "@/lib/format";
import { Snowflake, Thermometer, Fire, Vault } from "@phosphor-icons/react";

const custodyIcon = { cold: Snowflake, warm: Thermometer, hot: Fire };

export default function Treasury() {
  const { env } = useApp();
  const [items, setItems] = useState([]);
  useEffect(() => { api.get(`/treasury/accounts?env=${env}`).then(({ data }) => setItems(data.items || [])); }, [env]);

  const issuers = items.filter(a => a.kind === "issuer");
  const treasuries = items.filter(a => a.kind === "treasury");
  const pools = items.filter(a => a.kind === "reward_pool");
  const fees = items.filter(a => a.kind === "fee");

  return (
    <div data-testid="treasury-page">
      <PageHeader title="Treasury Console" subtitle={`Custody & distribution accounts · ${env}`} />
      <Section title="Issuer" accounts={issuers} />
      <Section title="Treasury / Distribution" accounts={treasuries} />
      <Section title="Reward Pools" accounts={pools} />
      <Section title="Fees" accounts={fees} />
    </div>
  );
}

const Section = ({ title, accounts }) => {
  if (accounts.length === 0) return null;
  return (
    <section className="mb-8">
      <div className="text-[10px] uppercase tracking-wider text-[#888] mb-2 font-mono">{title}</div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {accounts.map((a) => {
          const Icon = custodyIcon[a.custody] || Vault;
          return (
            <div key={a.account_id} className="prosper-card p-5" data-testid={`account-${a.account_id}`}>
              <div className="flex justify-between items-start mb-3">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <Icon size={14} className="text-[#888]" />
                    <span className="text-[10px] uppercase tracking-wider text-[#888] font-mono">{a.custody}</span>
                  </div>
                  <div className="font-display font-bold text-lg">{a.label}</div>
                </div>
                <StatusBadge value={a.environment} />
              </div>
              <div className="grid grid-cols-2 tight-grid border border-[#1a1a1a] mb-3">
                <div className="p-3 bg-[#0a0a0a]">
                  <div className="text-[10px] uppercase tracking-wider text-[#888]">{a.asset_code || "Asset"} balance</div>
                  <div className="font-mono text-lg mt-1">{fmtNum(a.balance_asset, 2)}</div>
                </div>
                <div className="p-3 bg-[#0a0a0a]">
                  <div className="text-[10px] uppercase tracking-wider text-[#888]">XLM</div>
                  <div className="font-mono text-lg mt-1">{fmtNum(a.balance_native, 2)}</div>
                </div>
              </div>
              <CopyField value={a.stellar_address} testId={`addr-${a.account_id}`} />
            </div>
          );
        })}
      </div>
    </section>
  );
};
