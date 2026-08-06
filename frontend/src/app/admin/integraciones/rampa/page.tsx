"use client";
import { useState } from "react";
import { Badge, PageHeader, StatusDot } from "@prosper/ui";
import {
  Plug, RefreshCw, Shield, CheckCircle2, XCircle,
  Plus, Trash2, Edit3, Save, X, AlertTriangle, Link2,
} from "lucide-react";
import { toast } from "sonner";
import {
  useProviderConfig, useConnectivity, useCapabilities,
  putProviderConfig, deleteOrgOverride,
  useArsaChainConfig, setArsaChainDefault,
  type ProviderConfigRow, type ConnectivityResult,
} from "@/lib/admin-ramp";

/** Phase 16 · A — Switch de proveedor de rampa (global + per-org overrides). */
export default function RampIntegrationsPage() {
  const cfg  = useProviderConfig();
  const conn = useConnectivity();
  const caps = useCapabilities();
  const chainCfg = useArsaChainConfig();

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: "Admin" }, { label: "Integraciones" },
                  { label: "Rampa" }]}
        title="Rampa · proveedor"
        subtitle="Cambiá el proveedor activo (Alfred · AndesLabs), modo (mock · sandbox · real) y override por organización. Cada cambio queda registrado en audit log."
      />

      <ConnectivityStrip data={conn.data} loading={conn.isLoading}
                            onRetry={() => conn.mutate()}/>

      <CapabilitiesPanel data={caps.data}/>

      <ArsaChainPanel data={chainCfg.data} loading={chainCfg.isLoading}
                         onChanged={() => chainCfg.mutate()}/>

      <ArsaAddressReferencePanel/>

      <ProviderConfigPanel
        rows={cfg.data?.rows || []}
        orgNames={cfg.data?.org_names || {}}
        loading={cfg.isLoading}
        onChanged={() => cfg.mutate()}
      />
    </div>
  );
}

// ────────────────────────────────────────────────────────────── A.1 strip
function ConnectivityStrip({ data, loading, onRetry }: {
  data?: ConnectivityResult[]; loading: boolean; onRetry: () => void;
}) {
  return (
    <section className="prosper-card p-5" data-testid="ramp-connectivity-strip">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Conectividad
          </div>
          <h3 className="font-display font-bold text-lg text-fg flex items-center gap-1.5 mt-0.5">
            <Shield size={14} className="text-primary"/> Probe de proveedores
          </h3>
        </div>
        <button onClick={onRetry}
                data-testid="ramp-connectivity-recheck"
                className="prosper-btn-ghost h-8 text-[11px] gap-1.5">
          <RefreshCw size={11} className={loading ? "animate-spin" : ""}/>
          Re-chequear
        </button>
      </div>
      {loading && !data && (
        <div className="text-xs text-fg-subtle italic">Chequeando…</div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {(data || []).map(r => (
          <ConnectivityCard key={r.provider} r={r}/>
        ))}
      </div>
    </section>
  );
}

function ConnectivityCard({ r }: { r: ConnectivityResult }) {
  const overallOk = r.enabled && r.reachable && r.authenticated && !r.error;
  return (
    <div className="rounded border border-border p-3 bg-surface"
         data-testid={`ramp-conn-${r.provider}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="font-display font-bold text-fg capitalize flex items-center gap-2">
          {overallOk
            ? <CheckCircle2 size={14} className="text-success"/>
            : <XCircle size={14} className="text-danger"/>}
          {r.provider}
        </div>
        {r.latency_ms !== undefined && (
          <span className="text-[10px] font-mono text-fg-subtle">
            {r.latency_ms} ms
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-1 text-[10px] font-mono">
        <Sema label="enabled"      ok={r.enabled}/>
        <Sema label="reachable"    ok={r.reachable}/>
        <Sema label="authenticated" ok={r.authenticated}/>
      </div>
      {r.error && (
        <div className="mt-2 text-[11px] text-danger border-t border-danger/20 pt-2"
             data-testid={`ramp-conn-${r.provider}-error`}>
          {r.error}
        </div>
      )}
    </div>
  );
}
function Sema({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className={`flex items-center gap-1 px-2 py-1 rounded ${
        ok ? "bg-success/5 text-success" : "bg-danger/5 text-danger"}`}>
      <StatusDot tone={ok ? "success" : "danger"}/>
      <span className="uppercase tracking-wider">{label}</span>
    </div>
  );
}

// ────────────────────────────────────────────────────────────── A.2 caps
function CapabilitiesPanel({ data }: { data?: Record<string, any> }) {
  if (!data) return null;
  const entries = Object.entries(data).filter(([k]) => !k.startsWith("_"));
  return (
    <section className="prosper-card p-5" data-testid="ramp-capabilities-panel">
      <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
        Capabilities por proveedor
      </div>
      <h3 className="font-display font-bold text-lg text-fg mb-3">
        Qué habilita cada uno
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {entries.map(([id, caps]: [string, any]) => (
          <div key={id} className="rounded border border-border p-3 bg-surface"
               data-testid={`ramp-caps-${id}`}>
            <div className="font-display font-bold capitalize text-fg mb-2">
              {id}
            </div>
            <KvRow k="producedAssets"
                   v={(caps.producedAssets || []).join(", ")}/>
            <KvRow k="chains" v={(caps.chains || []).join(", ")}/>
            <KvRow k="onrampModel" v={caps.onrampModel || "—"}/>
            <KvRow k="supportsDedicatedAccounts"
                   v={String(caps.supportsDedicatedAccounts ?? false)}/>
            <KvRow k="supportsBalances"
                   v={String(caps.supportsBalances ?? false)}/>
            <KvRow k="supportsKYC"
                   v={String(caps.supportsKYC ?? false)}/>
          </div>
        ))}
      </div>
    </section>
  );
}
function KvRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between text-[11px] py-0.5 border-b border-border/40 last:border-0">
      <span className="font-mono text-fg-subtle">{k}</span>
      <span className="font-mono text-fg">{v}</span>
    </div>
  );
}

// ────────────────────────────────────────────────────────────── A.2b · ARSa chain selector
function ArsaChainPanel({ data, loading, onChanged }: {
  data?: { default: "stellar" | "base";
            allowed: Array<"stellar" | "base">;
            source: string };
  loading: boolean;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [picked, setPicked]   = useState<"stellar" | "base">(
    data?.default || "stellar");
  const [busy, setBusy]       = useState(false);

  // Sync when SWR resolves
  if (data && !editing && picked !== data.default) setPicked(data.default);

  const save = async () => {
    setBusy(true);
    try {
      await setArsaChainDefault({ default: picked,
                                     allowed: ["stellar", "base"] });
      toast.success(`Cadena ARSa default → ${picked}`);
      setEditing(false); onChanged();
    } catch (e: any) {
      toast.error(e?.message || "No se pudo guardar");
    } finally { setBusy(false); }
  };

  return (
    <section className="prosper-card p-5" data-testid="arsa-chain-panel">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Cadena ARSa
          </div>
          <h3 className="font-display font-bold text-lg text-fg flex items-center gap-1.5 mt-0.5">
            <Link2 size={14} className="text-primary"/>
            Cadena por defecto para ARSa
          </h3>
          <p className="text-xs text-fg-muted mt-1 max-w-xl">
            Las wallets ARSa de Andes existen por par (asset, red).
            Cambiar la cadena <strong>afecta solo cuentas/wallets nuevas</strong>;
            no convierte ni mueve saldos existentes. Cada cliente puede
            opcionalmente fijar una cadena distinta desde su detalle.
          </p>
        </div>
        {!editing && data && (
          <div className="flex items-center gap-2 flex-wrap">
            <Badge tone={data.default === "stellar" ? "info" : "warning"}
                   data-testid="arsa-chain-current">
              Red default · {data.default === "stellar" ? "Stellar" : "Base"}
            </Badge>
            <span className="text-[10px] font-mono text-fg-subtle">
              fuente: {data.source}
            </span>
            <button onClick={() => setEditing(true)}
                    data-testid="arsa-chain-edit-btn"
                    className="prosper-btn-ghost h-8 text-[11px] gap-1.5">
              <Edit3 size={11}/> Cambiar
            </button>
          </div>
        )}
      </div>

      {loading && !data && (
        <div className="text-xs text-fg-subtle italic mt-2">Cargando…</div>
      )}

      {editing && (
        <div className="mt-4 rounded border border-warning/30 bg-warning/5 p-3">
          <div className="flex items-start gap-2 mb-3">
            <AlertTriangle size={14} className="text-warning shrink-0 mt-0.5"/>
            <p className="text-[11px] text-fg leading-snug">
              Solo afecta a cuentas y wallets <strong>creadas a partir de
              ahora</strong>. Las wallets existentes en otra red conservan su
              saldo y red.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 mb-3">
            <ChainPickButton
              testid="arsa-chain-pick-stellar"
              chain="stellar"
              picked={picked === "stellar"}
              onClick={() => setPicked("stellar")}
              label="Stellar (activo clásico)"
              hint="ARSa code · issuer GCVI…T5NE"/>
            <ChainPickButton
              testid="arsa-chain-pick-base"
              chain="base"
              picked={picked === "base"}
              onClick={() => setPicked("base")}
              label="Base (Coinbase L2 · EVM)"
              hint="Addresses 0x… · gas en ETH"/>
          </div>
          <div className="flex justify-end gap-2">
            <button onClick={() => setEditing(false)}
                    className="prosper-btn-ghost h-9 text-xs">
              <X size={12}/> Cancelar
            </button>
            <button onClick={save} disabled={busy || picked === data?.default}
                    data-testid="arsa-chain-save-btn"
                    className="prosper-btn-primary h-9 text-xs gap-1.5">
              <Save size={12}/> Guardar default
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function ChainPickButton({ chain, picked, onClick, label, hint, testid }: {
  chain: "stellar" | "base"; picked: boolean; onClick: () => void;
  label: string; hint: string; testid: string;
}) {
  return (
    <button onClick={onClick} data-testid={testid}
            className={`text-left rounded border p-3 transition-colors ${
              picked
                ? "border-primary bg-primary/5"
                : "border-border bg-surface hover:border-primary/40"}`}>
      <div className="flex items-center gap-2 mb-1">
        {picked
          ? <CheckCircle2 size={14} className="text-primary"/>
          : <div className="h-3.5 w-3.5 rounded-full border border-border"/>}
        <span className="font-display font-bold text-fg text-sm capitalize">
          {chain}
        </span>
      </div>
      <div className="text-[11px] text-fg-muted">{label}</div>
      <div className="text-[10px] font-mono text-fg-subtle mt-0.5">{hint}</div>
    </button>
  );
}

// ──────────────────────────────────────────────── A.2c · ARSa contract reference
function ArsaAddressReferencePanel() {
  // Source: PRD + Addendum. ARSa-Stellar is a CLASSIC asset (no token contract;
  // it has an issuer account + SAC). ARSa-Base is an ERC-20 proxy.
  return (
    <section className="prosper-card p-5" data-testid="arsa-addresses-panel">
      <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
        Direcciones de referencia · ARSa
      </div>
      <h3 className="font-display font-bold text-lg text-fg mt-0.5 flex items-center gap-1.5">
        <Link2 size={14} className="text-primary"/> ARSa por red
      </h3>
      <p className="text-xs text-fg-muted mt-1 max-w-2xl">
        ARSa-Stellar es un <strong>activo clásico de Stellar</strong> (no es
        Soroban): tiene un <em>issuer account</em> y un Stellar Asset Contract
        para uso con smart-contracts. ARSa-Base es un ERC-20 estándar en la red
        Base (chainId 8453).
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
        <div className="rounded border border-border bg-surface p-3 space-y-2"
             data-testid="arsa-stellar-ref">
          <div className="flex items-center justify-between">
            <span className="font-display font-bold text-fg text-sm">Stellar</span>
            <Badge tone="info" size="sm">classic asset</Badge>
          </div>
          <KvLink label="Issuer"
            value="GCVIA2UOUEM6JATLDQVXERXPSELWBRCDHB53SOAYBGUOHNOSUII4T5NE"
            href="https://stellar.expert/explorer/public/asset/ARSa-GCVIA2UOUEM6JATLDQVXERXPSELWBRCDHB53SOAYBGUOHNOSUII4T5NE"/>
          <KvLink label="SAC (smart contract)"
            value="CDYP52X4FIXSPDK76JGJT6J3NH2EV2GMBJ2KCEKMYMR36OSB3Y4CHFPL"
            href={null}/>
          <Kv label="Code" value="ARSa"/>
        </div>
        <div className="rounded border border-border bg-surface p-3 space-y-2"
             data-testid="arsa-base-ref">
          <div className="flex items-center justify-between">
            <span className="font-display font-bold text-fg text-sm">Base</span>
            <Badge tone="warning" size="sm">ERC-20</Badge>
          </div>
          <KvLink label="Proxy (token)"
            value="0x1817A385Df1f9F4721F8499D747FB3A63b1a1965"
            href="https://basescan.org/address/0x1817A385Df1f9F4721F8499D747FB3A63b1a1965"/>
          <Kv label="Chain ID" value="8453"/>
          <Kv label="Decimals" value="2"/>
        </div>
      </div>
    </section>
  );
}

function Kv({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-2 text-[11px]">
      <span className="font-mono uppercase tracking-wider text-fg-subtle">
        {label}
      </span>
      <span className="font-mono text-fg break-all text-right">{value}</span>
    </div>
  );
}

function KvLink({ label, value, href }: {
  label: string; value: string; href: string | null;
}) {
  return (
    <div className="flex items-start justify-between gap-2 text-[11px]">
      <span className="font-mono uppercase tracking-wider text-fg-subtle">
        {label}
      </span>
      {href ? (
        <a href={href} target="_blank" rel="noopener noreferrer"
           className="font-mono text-primary hover:underline break-all text-right">
          {value}
        </a>
      ) : (
        <span className="font-mono text-fg break-all text-right">{value}</span>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────── A.3 config rows
function ProviderConfigPanel({ rows, orgNames, loading, onChanged }: {
  rows: ProviderConfigRow[];
  orgNames: Record<string, string>;
  loading: boolean;
  onChanged: () => void;
}) {
  const global = rows.find(r => r.scope === "global");
  const overrides = rows.filter(r => r.scope !== "global");
  const [addingOpen, setAddingOpen] = useState(false);

  return (
    <section className="prosper-card p-5" data-testid="ramp-provider-config">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Configuración
          </div>
          <h3 className="font-display font-bold text-lg text-fg flex items-center gap-1.5">
            <Plug size={14} className="text-primary"/> Proveedor activo
          </h3>
        </div>
        <button onClick={() => setAddingOpen(true)}
                data-testid="ramp-add-override-btn"
                className="prosper-btn-ghost h-8 text-[11px] gap-1.5">
          <Plus size={11}/> Override por org
        </button>
      </div>

      {loading && <div className="text-xs text-fg-subtle italic">Cargando…</div>}

      {global && (
        <ProviderConfigRowEditor
          row={global}
          orgName="Global · default para todas las orgs"
          onChanged={onChanged}
          isGlobal
        />
      )}

      {overrides.length > 0 && (
        <div className="mt-4 pt-4 border-t border-border space-y-2">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
            Overrides por org · {overrides.length}
          </div>
          {overrides.map(o => (
            <ProviderConfigRowEditor
              key={o.scope}
              row={o}
              orgName={orgNames[o.scope] || o.scope}
              onChanged={onChanged}
            />
          ))}
        </div>
      )}

      {addingOpen && (
        <AddOverrideModal
          onClose={() => setAddingOpen(false)}
          onSaved={() => { setAddingOpen(false); onChanged(); }}
        />
      )}
    </section>
  );
}

function ProviderConfigRowEditor({
  row, orgName, onChanged, isGlobal,
}: {
  row: ProviderConfigRow; orgName: string;
  onChanged: () => void; isGlobal?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [provider, setProvider] = useState(row.provider);
  const [mode, setMode]         = useState(row.mode);
  const [enabled, setEnabled]   = useState(row.enabled);
  const [busy, setBusy]         = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      await putProviderConfig(row.scope, { provider, mode, enabled });
      toast.success(`Actualizado: ${row.scope}`);
      setEditing(false); onChanged();
    } catch (e: any) {
      toast.error(e?.message || "No se pudo guardar");
    } finally { setBusy(false); }
  };

  const remove = async () => {
    if (isGlobal) return;
    setBusy(true);
    try {
      await deleteOrgOverride(row.scope);
      toast.success(`Override eliminado: ${row.scope}`);
      onChanged();
    } catch (e: any) {
      toast.error(e?.message || "No se pudo eliminar");
    } finally { setBusy(false); }
  };

  return (
    <div className="rounded border border-border bg-surface p-3"
         data-testid={`ramp-config-row-${row.scope}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="font-display font-bold text-fg text-sm truncate">
            {orgName}
          </div>
          <div className="text-[10px] font-mono text-fg-subtle truncate">
            scope = {row.scope}
            {row.updated_by && <> · por {row.updated_by}</>}
            {row.updated_at && <> · {new Date(row.updated_at).toLocaleString()}</>}
          </div>
        </div>
        {!editing && (
          <div className="flex items-center gap-2 flex-wrap">
            <Badge tone={row.provider === "andeslabs" ? "info" : "auto"}>
              {row.provider}
            </Badge>
            <Badge tone={row.mode === "real" ? "success"
                          : row.mode === "sandbox" ? "warning" : "auto"}>
              {row.mode}
            </Badge>
            <Badge tone={row.enabled ? "success" : "danger"}>
              {row.enabled ? "enabled" : "disabled"}
            </Badge>
            <button onClick={() => setEditing(true)}
                    data-testid={`ramp-config-edit-${row.scope}`}
                    className="prosper-btn-ghost h-7 text-[11px] gap-1">
              <Edit3 size={11}/> Editar
            </button>
            {!isGlobal && (
              <button onClick={remove} disabled={busy}
                      data-testid={`ramp-config-delete-${row.scope}`}
                      className="prosper-btn-ghost h-7 text-[11px] text-danger gap-1">
                <Trash2 size={11}/>
              </button>
            )}
          </div>
        )}
      </div>
      {editing && (
        <div className="mt-3 grid grid-cols-1 md:grid-cols-4 gap-2 items-end">
          <SelectField label="Proveedor" value={provider} onChange={setProvider}
                        testid={`ramp-config-${row.scope}-provider`}
                        options={["alfred", "andeslabs"]}/>
          <SelectField label="Modo" value={mode} onChange={setMode}
                        testid={`ramp-config-${row.scope}-mode`}
                        options={["mock", "sandbox", "real"]}/>
          <SelectField label="Enabled" value={enabled ? "true" : "false"}
                        onChange={v => setEnabled(v === "true")}
                        testid={`ramp-config-${row.scope}-enabled`}
                        options={["true", "false"]}/>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setEditing(false)}
                    className="prosper-btn-ghost h-9 text-xs">
              <X size={12}/> Cancelar
            </button>
            <button onClick={save} disabled={busy}
                    data-testid={`ramp-config-save-${row.scope}`}
                    className="prosper-btn-primary h-9 text-xs gap-1.5">
              <Save size={12}/> Guardar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SelectField({ label, value, onChange, options, testid }: {
  label: string; value: string; onChange: (v: any) => void;
  options: string[]; testid?: string;
}) {
  return (
    <label className="block">
      <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
        {label}
      </span>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        data-testid={testid}
        className="mt-1 w-full px-2.5 h-9 rounded border border-border bg-bg text-fg text-sm font-mono focus:outline-none focus:border-primary">
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

function AddOverrideModal({ onClose, onSaved }: {
  onClose: () => void; onSaved: () => void;
}) {
  const [orgId, setOrgId]       = useState("");
  const [provider, setProvider] = useState("andeslabs");
  const [mode, setMode]         = useState("sandbox");
  const [busy, setBusy]         = useState(false);

  const save = async () => {
    if (!orgId.trim()) {
      toast.error("Ingresá el org_id");
      return;
    }
    setBusy(true);
    try {
      await putProviderConfig(orgId.trim(),
        { provider, mode, enabled: true });
      toast.success(`Override creado para ${orgId}`);
      onSaved();
    } catch (e: any) {
      toast.error(e?.message || "No se pudo crear");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-bg/70 backdrop-blur-sm grid place-items-center p-4"
         onClick={onClose} data-testid="ramp-add-override-modal">
      <div className="prosper-card p-5 max-w-md w-full"
           onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-bold text-fg text-lg mb-3">
          Override de proveedor por organización
        </h3>
        <p className="text-xs text-fg-muted mb-4">
          La org indicada usará este proveedor en vez del global. Útil para
          migrar clientes uno por uno.
        </p>
        <div className="space-y-3">
          <label className="block">
            <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              org_id
            </span>
            <input
              data-testid="ramp-add-override-org"
              value={orgId} onChange={e => setOrgId(e.target.value)}
              placeholder="org_seed_alemany"
              className="mt-1 w-full px-3 h-9 rounded border border-border bg-bg text-fg text-sm font-mono focus:outline-none focus:border-primary"/>
          </label>
          <SelectField label="Proveedor" value={provider} onChange={setProvider}
                        testid="ramp-add-override-provider"
                        options={["alfred", "andeslabs"]}/>
          <SelectField label="Modo" value={mode} onChange={setMode}
                        testid="ramp-add-override-mode"
                        options={["mock", "sandbox", "real"]}/>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose}
                  className="prosper-btn-ghost h-9 text-xs">Cancelar</button>
          <button onClick={save} disabled={busy}
                  data-testid="ramp-add-override-save"
                  className="prosper-btn-primary h-9 text-xs gap-1.5">
            <Save size={12}/> Crear override
          </button>
        </div>
      </div>
    </div>
  );
}
