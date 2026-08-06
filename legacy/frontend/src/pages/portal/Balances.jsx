import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, MetricBar, MetricCell, StatusBadge, EmptyState, CopyField } from "@/components/common";
import FormDialog from "@/components/FormDialog";
import { fmtMoney, fmtDate, fmtBps } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Plus, ArrowLineRight } from "@phosphor-icons/react";

export default function PortalBalances() {
  const [positions, setPositions] = useState([]);
  const [products, setProducts] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [subOpen, setSubOpen] = useState(false);

  const load = () => api.get("/positions").then(({ data }) => setPositions(data.items || []));
  useEffect(() => {
    load();
    api.get("/products").then(({ data }) => setProducts(data.items || []));
    api.get("/organizations").then(({ data }) => setOrgs(data.items || []));
  }, []);

  const principal = positions.reduce((s, p) => s + (p.principal || 0), 0);
  const accrued = positions.reduce((s, p) => s + (p.accrued_interest || 0), 0);
  const claimed = positions.reduce((s, p) => s + (p.claimed_interest || 0), 0);

  const subscribe = async (values) => {
    const { data } = await api.post("/positions/subscribe", {
      org_id: values.org_id,
      product_id: values.product_id,
      amount: Number(values.amount),
      user_reference_id: values.user_reference_id || undefined,
    });
    toast.success(`Subscribed! prosperTxId: ${data.prosper_tx_id.slice(0, 8)}…`);
    load();
  };

  const redeem = async (positionId) => {
    if (!window.confirm("Redeem this position? This will settle principal + accrued interest.")) return;
    try {
      const { data } = await api.post(`/positions/${positionId}/redeem`);
      toast.success(`Redeemed: ${fmtMoney(data.transaction.amount)}`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Redeem failed");
    }
  };

  return (
    <div data-testid="portal-balances">
      <PageHeader title="Balances & Positions"
        actions={
          <Button onClick={() => setSubOpen(true)} data-testid="subscribe-btn"
                  className="rounded-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white gap-1.5">
            <Plus size={14} weight="bold" /> Subscribe
          </Button>
        }
      />
      <MetricBar>
        <MetricCell label="Total Principal" value={fmtMoney(principal)} />
        <MetricCell label="Accrued Yield" value={fmtMoney(accrued)} />
        <MetricCell label="Claimed Yield" value={fmtMoney(claimed)} />
        <MetricCell label="Positions" value={positions.length} />
      </MetricBar>

      <div className="mt-6">
        {positions.length === 0 ? (
          <EmptyState title="No positions held"
            message="Subscribe to a yield product to start accruing returns."
            action={
              <Button onClick={() => setSubOpen(true)} className="rounded-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white gap-1.5">
                <Plus size={14} weight="bold" /> Subscribe now
              </Button>
            }
          />
        ) : (
          <div className="prosper-card overflow-hidden">
            <table className="data-table w-full">
              <thead><tr>
                <th>Stellar Address</th>
                <th className="text-right">Principal</th>
                <th className="text-right">Accrued</th>
                <th>Maturity</th>
                <th>Status</th>
                <th className="text-right">Actions</th>
              </tr></thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.position_id} data-testid={`pos-${p.position_id}`}>
                    <td><CopyField value={p.stellar_address} /></td>
                    <td className="text-right font-mono">{fmtMoney(p.principal)}</td>
                    <td className="text-right font-mono" style={{ color: "var(--success)" }}>{fmtMoney(p.accrued_interest)}</td>
                    <td className="text-xs font-mono text-[var(--fg-muted)]">{fmtDate(p.maturity_date)}</td>
                    <td><StatusBadge value={p.status} /></td>
                    <td className="text-right">
                      {(p.status === "active" || p.status === "matured") && (
                        <Button size="sm" onClick={() => redeem(p.position_id)}
                                data-testid={`redeem-${p.position_id}`}
                                className="h-7 text-xs rounded-full bg-transparent border border-[var(--primary)] text-[var(--primary)] hover:bg-[var(--primary-soft)] gap-1">
                          <ArrowLineRight size={12} weight="bold" /> Redeem
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <FormDialog
        open={subOpen}
        onOpenChange={setSubOpen}
        title="Subscribe to a Product"
        description="Convert USDC into PROS and start accruing yield. The transaction is anchored by a prosperTxId."
        submitLabel="Subscribe"
        onSubmit={subscribe}
        testId="subscribe-dialog"
        fields={[
          { key: "org_id", label: "Organization", type: "select", required: true,
            options: orgs.map(o => ({ value: o.org_id, label: o.name })) },
          { key: "product_id", label: "Product", type: "select", required: true,
            options: products.filter(p => p.status === "active").map(p => ({
              value: p.product_id,
              label: `${p.name} · ${fmtBps(p.apr_bps)} · min ${fmtMoney(p.min_amount, "USD", 0)}`
            })) },
          { key: "amount", label: "Amount (USDC)", type: "number", required: true, placeholder: "1000" },
          { key: "user_reference_id", label: "End-customer Reference (optional)",
            placeholder: "cust_12345",
            help: "If this subscription is on behalf of an end customer, provide your internal reference ID." },
        ]}
      />
    </div>
  );
}
