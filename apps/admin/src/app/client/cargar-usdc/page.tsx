"use client";
/**
 * /client/cargar-usdc — P1-1 (Feb 2026)
 *
 * CMS protocol deposit flow for USDC. The client transfers USDC from an
 * external Stellar wallet (Lobstr, Freighter, exchange) to the address
 * provisioned for the org by /api/v1/cms/cashin. The poller
 * (jobs/staking_sync.py) picks the on-chain transfer up automatically
 * and creates the corresponding position.
 *
 * Mandatory UX guards:
 *   - Network warning is shown UPFRONT and the user has to acknowledge
 *     it explicitly before the address is unblurred / copy-able.
 *   - Modality picker (end | month) — each modality has its own wallet.
 *   - QR + monospace address with copy + Stellar Expert link.
 */
import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { QRCodeSVG } from "qrcode.react";
import {
  AlertTriangle, ArrowLeft, Check, Copy, ExternalLink,
  Lock, CalendarClock, ShieldAlert, RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader, Badge } from "@prosper/ui";
import { api } from "@/lib/api";
import { useClientMe } from "@/lib/client-portal";

type Modality = "end" | "month";

interface Wallet {
  modality: Modality;
  address: string;
  prosper_user_id: string;
  created: boolean;
}

interface DepositWalletsResp {
  wallets: Wallet[];
  network: string;
  asset: string;
  asset_issuer: string;
  prosper_id: string;
  safety_warning: string;
  fetched_at: string;
}

const STELLAR_EXPLORER_ACCOUNT = "https://stellar.expert/explorer/public/account";

export default function CargarUsdcPage() {
  const { data: me } = useClientMe();
  const canOperate = me?.features?.can_operate ?? false;

  const { data, error, isLoading, mutate } = useSWR<DepositWalletsResp>(
    canOperate ? "/v1/client/deposit-wallets" : null,
    (p: string) => api(p));

  const [modality, setModality] = useState<Modality>("end");
  const [acknowledged, setAcknowledged] = useState(false);
  const [copied, setCopied] = useState(false);

  const wallet = (data?.wallets || []).find((w) => w.modality === modality);

  const onCopy = async () => {
    if (!wallet) return;
    await navigator.clipboard.writeText(wallet.address);
    setCopied(true);
    toast.success("Dirección copiada al portapapeles");
    setTimeout(() => setCopied(false), 2500);
  };

  if (!canOperate) {
    return (
      <div data-testid="cargar-usdc-blocked">
        <PageHeader
          breadcrumbs={[{ label: "Inicio", href: "/client" }, { label: "Cargar USDC" }]}
          kicker={undefined}
          title="Cargar USDC"
        />
        <div className="prosper-card p-10 text-center">
          <AlertTriangle size={24} className="mx-auto text-warning mb-2" />
          <p className="text-sm text-fg-muted">
            Tu KYB no está aprobado todavía. No podés recibir transferencias.
          </p>
          <Link href="/apply"
                className="prosper-btn-primary inline-flex h-10 px-5 mt-4 text-sm">
            Continuar onboarding
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="cargar-usdc-page">
      <PageHeader
        breadcrumbs={[{ label: "Inicio", href: "/client" }, { label: "Cargar USDC" }]}
        kicker={undefined}
        title="Cargar USDC desde tu wallet externa"
        subtitle="Transferí USDC desde Lobstr, Freighter o un exchange a tu dirección Stellar asignada. El depósito se detecta automáticamente."
        actions={
          <Link href="/client" className="prosper-btn-ghost h-9 px-3 text-xs gap-1.5"
                data-testid="cargar-usdc-back">
            <ArrowLeft size={13}/> Volver al dashboard
          </Link>}
      />

      {/* ============================================================
          MANDATORY SAFETY WARNING — surfaced first, always visible,
          requires explicit acknowledgment to proceed.
         ============================================================ */}
      <div className="rounded-xl border-2 border-danger bg-danger/5 p-5 mb-6"
           data-testid="cargar-usdc-warning">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-full bg-danger/15 text-danger
                            flex items-center justify-center shrink-0">
            <ShieldAlert size={20} />
          </div>
          <div className="flex-1">
            <h2 className="font-display font-bold text-base text-danger">
              ⚠️ ADVERTENCIA · Red Stellar únicamente
            </h2>
            <p className="text-sm text-fg mt-1 leading-relaxed">
              <strong>Enviá USDC ÚNICAMENTE en la red Stellar.</strong>{" "}
              Cualquier transferencia desde otra red (<span className="font-mono">Ethereum, Polygon, BSC, Tron, Solana</span>)
              implica la <strong>pérdida total e irreversible</strong> de los fondos.
              Los depósitos on-chain no se pueden revertir.
            </p>
            <p className="text-xs text-fg-muted mt-2">
              Si tu wallet externa no soporta la red Stellar (assetCode <code className="font-mono">USDC</code>,
              issuer <code className="font-mono">Centre.io</code>), no envíes nada — usá Lobstr o Freighter en su lugar.
            </p>
            {!acknowledged && (
              <label className="flex items-center gap-2 mt-4 cursor-pointer
                                  bg-bg-elevated rounded-lg p-3 border border-border hover:border-danger
                                  transition-colors"
                       data-testid="cargar-usdc-ack-label">
                <input type="checkbox"
                       onChange={(e) => setAcknowledged(e.target.checked)}
                       className="h-4 w-4 accent-danger"
                       data-testid="cargar-usdc-ack" />
                <span className="text-sm text-fg">
                  Entiendo y voy a enviar USDC <strong>solo</strong> por la red Stellar.
                </span>
              </label>
            )}
            {acknowledged && (
              <div className="flex items-center gap-2 mt-3 text-xs text-success font-mono">
                <Check size={12}/> Confirmado · podés continuar
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ============================================================
          Modality picker — each modality has its own wallet address.
         ============================================================ */}
      <div className="mb-5" data-testid="cargar-usdc-modality-picker">
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
          ¿A qué modalidad querés acreditar este depósito?
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <ModalityOption
            modality="end"
            active={modality === "end"}
            disabled={!acknowledged}
            onClick={() => setModality("end")}
            title="Al vencimiento (end)"
            subtitle="Cobrás capital + intereses al final del plazo de 12 meses."
            icon={<Lock size={14} />}
          />
          <ModalityOption
            modality="month"
            active={modality === "month"}
            disabled={!acknowledged}
            onClick={() => setModality("month")}
            title="Mensual (month)"
            subtitle="Cobrás intereses mes a mes, capital al vencimiento."
            icon={<CalendarClock size={14} />}
          />
        </div>
      </div>

      {/* ============================================================
          Address card — blurred until the user acknowledges.
         ============================================================ */}
      <div className={"prosper-card p-6 transition-all " +
                       (!acknowledged ? "opacity-40 pointer-events-none select-none blur-sm"
                                       : "")}
           data-testid="cargar-usdc-address-card">
        {isLoading && !data && (
          <div className="text-center py-10 text-fg-subtle text-sm">Cargando wallet…</div>
        )}

        {error && (
          <div className="text-center py-10">
            <AlertTriangle size={20} className="mx-auto text-warning mb-2" />
            <div className="text-sm text-fg-muted">
              No se pudo obtener tu wallet asignada.
            </div>
            <button onClick={() => mutate()}
                    className="prosper-btn-ghost h-9 px-3 text-xs gap-1 mt-3">
              <RefreshCw size={12}/> Reintentar
            </button>
          </div>
        )}

        {wallet && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-center">
            {/* LEFT — QR */}
            <div className="flex flex-col items-center justify-center"
                 data-testid="cargar-usdc-qr-wrap">
              <div className="rounded-lg bg-white p-4 inline-block">
                <QRCodeSVG
                  value={wallet.address}
                  size={196}
                  level="H"
                  data-testid="cargar-usdc-qr"
                />
              </div>
              <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mt-3">
                Modalidad: <span className="text-fg">{modality}</span>
              </div>
            </div>

            {/* RIGHT — Address + details */}
            <div>
              <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
                Tu dirección Stellar · USDC
              </div>
              <h3 className="font-display font-bold text-lg text-fg mt-0.5 mb-2">
                Wallet asignada para “{modality}”
              </h3>

              <div className="rounded border border-border bg-bg-elevated p-3 mb-3">
                <code className="block text-xs font-mono break-all text-fg leading-relaxed
                                  select-all"
                       data-testid="cargar-usdc-address">{wallet.address}</code>
              </div>

              <div className="flex flex-wrap gap-2">
                <button onClick={onCopy}
                        className="prosper-btn-primary h-9 px-3 text-xs gap-1.5"
                        data-testid="cargar-usdc-copy">
                  {copied ? <><Check size={13}/> Copiado</>
                            : <><Copy size={13}/> Copiar dirección</>}
                </button>
                <a href={`${STELLAR_EXPLORER_ACCOUNT}/${wallet.address}`}
                   target="_blank" rel="noopener noreferrer"
                   className="prosper-btn-ghost h-9 px-3 text-xs gap-1.5"
                   data-testid="cargar-usdc-expert">
                  <ExternalLink size={13}/> Ver en Stellar Expert
                </a>
              </div>

              {/* Network labels */}
              <div className="flex flex-wrap gap-2 mt-4 text-[10px] font-mono">
                <Badge tone="info">network · Stellar</Badge>
                <Badge tone="info">asset · USDC</Badge>
                {data?.prosper_id && (
                  <Badge tone="default">prosperId · {data.prosper_id.slice(0, 20)}</Badge>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ============================================================
          Step-by-step instructions
         ============================================================ */}
      <div className="prosper-card p-5 mt-6" data-testid="cargar-usdc-instructions">
        <h3 className="font-display font-bold text-base text-fg mb-3">
          ¿Cómo transferir?
        </h3>
        <ol className="space-y-2 text-sm text-fg-muted list-decimal pl-5">
          <li>Abrí tu wallet externa (<strong>Lobstr</strong>, <strong>Freighter</strong>,
            o exchange compatible con Stellar como Kraken o Bitstamp).</li>
          <li>Iniciá un envío seleccionando <strong>USDC (red Stellar)</strong>.</li>
          <li>Pegá la dirección de arriba en el campo destinatario.</li>
          <li>Confirmá el monto y enviá la transacción. <strong>No hace falta agregar memo</strong>
            {" "}— el contrato Prosper lo emite automáticamente al recibir el depósito.</li>
          <li>En 1–3 minutos vas a ver tu nueva posición en{" "}
            <Link href="/client/investments" className="text-primary hover:underline">
              /client/investments
            </Link>. Si no aparece después de 10 minutos, contactanos.</li>
        </ol>
      </div>
    </div>
  );
}

function ModalityOption({ modality, active, disabled, onClick,
                          title, subtitle, icon }:
  { modality: Modality; active: boolean; disabled: boolean;
    onClick: () => void; title: string; subtitle: string;
    icon: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
            data-testid={`cargar-usdc-modality-${modality}`}
            className={`p-4 rounded-xl border text-left transition-all
                        ${active
                          ? "border-primary bg-primary/5 ring-1 ring-primary"
                          : "border-border hover:bg-surface-hover"}
                        ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className={active ? "text-primary" : "text-fg-muted"}>{icon}</span>
        <span className="font-display font-bold text-sm text-fg">{title}</span>
      </div>
      <div className="text-[11px] text-fg-muted line-clamp-2">{subtitle}</div>
    </button>
  );
}
