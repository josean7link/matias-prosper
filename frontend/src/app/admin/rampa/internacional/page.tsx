"use client";
import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Badge, PageHeader } from "@prosper/ui";
import {
  Globe, RefreshCw, Plus, AlertTriangle, CheckCircle2,
  ArrowRight, Save, X, Building2,
} from "lucide-react";
import { toast } from "sonner";
import {
  useIntlCotization, useIntlBanks, useIntlAccounts, useIntlOfframps,
  createIntlAccount, quoteIntl, executeIntlOfframp,
  fmtArsaAdmin, useAdminAccounts,
} from "@/lib/admin-ramp";

type Country = "bob" | "pen" | "pyg";
const COUNTRY_LABEL: Record<Country, string> = {
  bob: "Bolivia (BOB)", pen: "Perú (PEN)", pyg: "Paraguay (PYG)",
};

/** Phase 15.2 · A — Off-ramp internacional (operación manual del backoffice). */
export default function RampInternationalPage() {
  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");
  const cot = useIntlCotization();
  // Use the admin accounts endpoint (super_admin sees ALL orgs' ramp accounts);
  // pass an empty query string for "everything".
  const accs = useAdminAccounts("");
  const [step, setStep] = useState<"setup" | "quote" | "execute">("setup");
  const [country, setCountry] = useState<Country>("pyg");
  const [ecid, setEcid] = useState<string>("");
  const [pickedOrgId, setPickedOrgId] = useState<string>("");
  const [destFid, setDestFid] = useState<string>("");
  const [quote, setQuote] = useState<any>(null);
  const [arsAmount, setArsAmount] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const intlAccs = useIntlAccounts(ecid || undefined, pickedOrgId || undefined);
  const offramps = useIntlOfframps(ecid || undefined, pickedOrgId || undefined);

  const doQuote = async () => {
    setBusy(true);
    try {
      const q = await quoteIntl(country, arsAmount || undefined);
      setQuote(q);
      setStep("execute");
    } catch (e: any) { toast.error(e?.message || "Quote failed"); }
    finally { setBusy(false); }
  };

  const doExecute = async () => {
    if (!ecid || !destFid) {
      toast.error("Elegí cliente y cuenta destino"); return;
    }
    setBusy(true);
    try {
      const body: any = { end_customer_id: ecid, country,
                            fiat_account_id: destFid };
      if (country === "pyg") {
        body.ars_amount = arsAmount;
      } else {
        body.ars_usdt_quote_id  = quote?.quotes?.arsUsdt?.quoteId;
        body.usdt_dest_quote_id = country === "bob"
          ? quote?.quotes?.usdtBob?.quoteId
          : quote?.quotes?.usdtPen?.quoteId;
        body.quote_expiration   = quote?.quotes?.arsUsdt?.expiration;
        body.expected_to_amount = country === "bob"
          ? quote?.quotes?.usdtBob?.toAmount
          : quote?.quotes?.usdtPen?.toAmount;
      }
      const idem = "ik_intl_" + Date.now();
      await executeIntlOfframp(body, pickedOrgId || undefined, idem);
      toast.success("Off-ramp enviada · esperando webhook");
      offramps.mutate();
      setStep("setup");
      setQuote(null);
      setArsAmount("");
    } catch (e: any) { toast.error(e?.message || "Execution failed"); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-6" data-testid="ramp-intl-page">
      <PageHeader
        crumbs={[{ label: tA("breadcrumb_admin") }, { label: tH("rampa_label") },
                  { label: tH("rampa_intl_bc") }]}
        title={tH("rampa_intl_title")}
        subtitle={tH("rampa_intl_subtitle")}
      />

      {/* Cotization strip */}
      <section className="prosper-card p-4" data-testid="intl-cotization-card">
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Cotización referencial
          </div>
          <button onClick={() => cot.mutate()}
                  className="prosper-btn-ghost h-7 text-[10px] gap-1.5">
            <RefreshCw size={10}/> Refrescar
          </button>
        </div>
        {cot.data ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <Stat label="1 USDT" value={`${cot.data.ars_usdt} ARS`}/>
            <Stat label="1 USDT" value={`${cot.data.usdt_bob} BOB`}/>
            <Stat label="1 USDT" value={`${cot.data.usdt_pen} PEN`}/>
            <Stat label="1 USDT" value={`${cot.data.usdt_pyg} PYG`}/>
          </div>
        ) : (
          <div className="text-xs text-fg-subtle italic">Cargando…</div>
        )}
      </section>

      {/* Step 1 — Setup */}
      <section className="prosper-card p-5" data-testid="intl-setup-card">
        <h3 className="font-display font-bold text-lg text-fg flex items-center gap-1.5">
          <Globe size={14} className="text-primary"/> 1 · Cliente y país destino
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
          <Field label="Cliente">
            <select value={ecid}
                    onChange={e => {
                      const picked = (accs.data?.items || []).find(
                        (a: any) => a.end_customer_id === e.target.value);
                      setEcid(e.target.value);
                      setPickedOrgId(picked?.org_id || "");
                      setDestFid("");
                    }}
                    data-testid="intl-client-select"
                    className="prosper-input h-9 text-xs w-full">
              <option value="">Elegí un cliente…</option>
              {((accs.data?.items) || []).map((a: any) => (
                <option key={a.end_customer_id} value={a.end_customer_id}>
                  {a.account_name || a.holder_name || a.end_customer_id} · {a.org_id}
                </option>
              ))}
            </select>
          </Field>
          <Field label="País destino">
            <div className="flex gap-2">
              {(["pyg", "bob", "pen"] as Country[]).map(c => (
                <button key={c} onClick={() => setCountry(c)}
                  data-testid={`intl-country-${c}`}
                  className={`flex-1 h-9 text-xs rounded border ${
                    country === c
                      ? "border-primary bg-primary/5 text-fg"
                      : "border-border bg-surface hover:border-primary/40"}`}>
                  {COUNTRY_LABEL[c]}
                </button>
              ))}
            </div>
          </Field>
        </div>
      </section>

      {/* Step 2 — Destination accounts */}
      {ecid && (
        <DestinationAccountSection
          ecid={ecid} country={country} orgId={pickedOrgId}
          accounts={intlAccs.data || []}
          onChanged={() => intlAccs.mutate()}
          destFid={destFid} setDestFid={setDestFid}/>
      )}

      {/* Step 3 — Quote + Execute */}
      {ecid && destFid && (
        <section className="prosper-card p-5" data-testid="intl-execute-card">
          <h3 className="font-display font-bold text-lg text-fg flex items-center gap-1.5">
            <ArrowRight size={14} className="text-primary"/> 3 · Cotizar y ejecutar
          </h3>

          <div className="mt-3 flex items-end gap-3 flex-wrap">
            <Field label={country === "pyg" ? "Monto ARS (amount-driven)" : "Monto ARS"}>
              <input value={arsAmount} onChange={e => setArsAmount(e.target.value)}
                     data-testid="intl-ars-amount"
                     placeholder="50000"
                     className="prosper-input h-9 text-xs w-40"/>
            </Field>
            {country !== "pyg" && (
              <button onClick={doQuote}
                      data-testid="intl-quote-btn"
                      disabled={busy || !arsAmount}
                      className="prosper-btn-ghost h-9 text-xs gap-1.5">
                <RefreshCw size={11} className={busy ? "animate-spin" : ""}/>
                Cotizar
              </button>
            )}
            <button onClick={doExecute}
                    data-testid="intl-execute-btn"
                    disabled={busy || !arsAmount
                                  || (country !== "pyg" && !quote)}
                    className="prosper-btn-primary h-9 text-xs gap-1.5">
              <CheckCircle2 size={11}/> Ejecutar off-ramp
            </button>
          </div>

          {quote && (
            <div className="mt-3 rounded border border-info/30 bg-info/5 p-3 text-xs space-y-1"
                 data-testid="intl-quote-preview">
              {country === "pyg" ? (
                <>
                  <div>Rate ARS→USDT: <strong>{quote.ars_usdt_rate}</strong></div>
                  <div>Rate USDT→PYG: <strong>{quote.usdt_pyg_rate}</strong></div>
                  <div className="text-[10px] text-fg-subtle">
                    PYG es amount-driven · el rate es referencial
                  </div>
                </>
              ) : (
                <>
                  <div>arsUsdt quote: <code className="text-[10px]">{quote.quotes?.arsUsdt?.quoteId}</code></div>
                  <div>USDT estimados: {quote.quotes?.arsUsdt?.toAmount}</div>
                  <div>Destino estimado: {Object.values(quote.quotes || {}).find((q:any)=>q.toCurrency!=="USDT")?.toAmount}</div>
                  <div className="text-[10px] text-fg-subtle">
                    Expiración: {new Date(quote.quotes?.arsUsdt?.expiration).toLocaleString()}
                  </div>
                </>
              )}
            </div>
          )}
        </section>
      )}

      {/* History */}
      {ecid && (
        <section className="prosper-card p-5"
                 data-testid="intl-history-card">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
            Off-ramps recientes
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border">
                <th className="text-left py-1.5">Fecha</th>
                <th className="text-left py-1.5">País</th>
                <th className="text-right py-1.5">ARS</th>
                <th className="text-right py-1.5">Destino</th>
                <th className="text-left py-1.5 pl-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {(offramps.data || []).map(o => (
                <tr key={o.id} className="border-b border-border/40"
                    data-testid={`intl-offramp-row-${o.id}`}>
                  <td className="py-1.5 text-fg-subtle font-mono text-[10px]">
                    {new Date(o.created_at).toLocaleString()}
                  </td>
                  <td className="py-1.5"><Badge tone="info" size="sm">{(o.country||'').toUpperCase()}</Badge></td>
                  <td className="py-1.5 text-right font-mono tabular">
                    {fmtArsaAdmin(o.from_amount)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular">
                    {o.to_amount} {o.to_currency}
                  </td>
                  <td className="py-1.5 pl-3">
                    <Badge tone={o.status === "Success" ? "success" :
                                 o.status === "Failed" ? "danger" : "warning"}
                           size="sm">
                      {o.status}
                    </Badge>
                  </td>
                </tr>
              ))}
              {(offramps.data || []).length === 0 && (
                <tr><td colSpan={5} className="py-3 text-center text-fg-subtle italic">
                  Sin off-ramps todavía.
                </td></tr>
              )}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border bg-surface px-3 py-2">
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">{label}</div>
      <div className="font-display font-bold text-fg text-base mt-0.5">{value}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
        {label}
      </label>
      <div className="mt-1">{children}</div>
    </div>
  );
}

// ────────────────────────────────────── Step 2 · Destination accounts
function DestinationAccountSection({
  ecid, country, orgId, accounts, destFid, setDestFid, onChanged,
}: {
  ecid: string; country: Country; orgId: string; accounts: any[];
  destFid: string; setDestFid: (v: string) => void;
  onChanged: () => void;
}) {
  const banks = useIntlBanks(country);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<any>({
    account_number: "", account_holder: "", account_holder_last_name: "",
    document_number: "", document_type: "DNI", account_type: "checking",
    bank_code: "", bank_name: "",
  });

  const filtered = (accounts || []).filter(a => a.country === country);

  const submit = async () => {
    try {
      const res = await createIntlAccount({
        end_customer_id: ecid, country, ...form,
      }, orgId || undefined);
      toast.success("Cuenta destino creada");
      setDestFid(res.fiat_account_id || res.id);
      setCreating(false);
      onChanged();
    } catch (e: any) { toast.error(e?.message || "No se pudo crear"); }
  };

  return (
    <section className="prosper-card p-5" data-testid="intl-dest-account-card">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-display font-bold text-lg text-fg flex items-center gap-1.5">
          <Building2 size={14} className="text-primary"/> 2 · Cuenta destino ({country.toUpperCase()})
        </h3>
        <button onClick={() => setCreating(v => !v)}
                data-testid="intl-add-dest-btn"
                className="prosper-btn-ghost h-8 text-[11px] gap-1.5">
          {creating ? <X size={11}/> : <Plus size={11}/>}
          {creating ? "Cancelar" : "Nueva"}
        </button>
      </div>

      <div className="mt-3 space-y-1">
        {filtered.length === 0 && !creating && (
          <div className="text-[11px] text-fg-subtle italic">
            No hay cuentas destino para este cliente en {country.toUpperCase()}. Creá una nueva.
          </div>
        )}
        {filtered.map(a => (
          <button key={a.id} onClick={() => setDestFid(a.fiat_account_id)}
            data-testid={`intl-dest-pick-${a.fiat_account_id}`}
            className={`w-full text-left rounded border px-3 py-2 ${
              destFid === a.fiat_account_id
                ? "border-primary bg-primary/5"
                : "border-border bg-surface hover:border-primary/40"}`}>
            <div className="flex items-center gap-2 text-xs">
              {destFid === a.fiat_account_id
                ? <CheckCircle2 size={12} className="text-primary"/>
                : <div className="h-3 w-3 rounded-full border border-border"/>}
              <span className="font-display font-bold">{a.account_holder} {a.account_holder_last_name}</span>
              <span className="font-mono text-fg-subtle">·</span>
              <span className="font-mono">{a.account_number}</span>
              {a.bank_name && (
                <Badge tone="info" size="sm">{a.bank_name}</Badge>
              )}
            </div>
          </button>
        ))}
      </div>

      {creating && (
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 border-t border-border pt-4">
          <Field label="Titular (nombre)">
            <input className="prosper-input h-9 text-xs w-full"
              data-testid="intl-form-holder"
              value={form.account_holder}
              onChange={e => setForm({ ...form, account_holder: e.target.value })}/>
          </Field>
          <Field label="Apellido">
            <input className="prosper-input h-9 text-xs w-full"
              value={form.account_holder_last_name}
              onChange={e => setForm({ ...form, account_holder_last_name: e.target.value })}/>
          </Field>
          <Field label="Número de cuenta">
            <input className="prosper-input h-9 text-xs w-full"
              data-testid="intl-form-account-number"
              value={form.account_number}
              onChange={e => setForm({ ...form, account_number: e.target.value })}/>
          </Field>
          <Field label="Documento">
            <input className="prosper-input h-9 text-xs w-full"
              value={form.document_number}
              onChange={e => setForm({ ...form, document_number: e.target.value })}/>
          </Field>
          <Field label="Banco">
            {country === "pen" ? (
              <input className="prosper-input h-9 text-xs w-full"
                placeholder="ej: Banco de Crédito"
                value={form.bank_name}
                onChange={e => setForm({ ...form, bank_name: e.target.value })}/>
            ) : (
              <select className="prosper-input h-9 text-xs w-full"
                value={form.bank_code}
                onChange={e => setForm({ ...form, bank_code: e.target.value })}>
                <option value="">Elegí banco…</option>
                {country === "bob" && (banks.data || []).map((b: any) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
                {country === "pyg" && banks.data && Object.entries(banks.data).map(([id, name]) => (
                  <option key={id} value={id}>{name as string}</option>
                ))}
              </select>
            )}
          </Field>
          <div className="md:col-span-2 flex justify-end">
            <button onClick={submit}
                    data-testid="intl-form-submit"
                    className="prosper-btn-primary h-9 text-xs gap-1.5">
              <Save size={11}/> Crear destino
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
