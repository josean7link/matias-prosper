/**
 * Etiquetas, tonos y formatos compartidos del portal cliente (Feb 2026).
 *
 * Objetivo: una sola fuente de verdad para cómo se rotulan estados,
 * cómo se formatean montos y fechas, y qué set de badges usamos en TODO
 * el portal. Reemplaza el copy disperso (mezcla EN/ES) por strings
 * consistentes en español.
 */

export type StatusBadgeTone =
  | "success"   // todo OK / completado / activo
  | "warning"   // pending / detectando
  | "danger"    // fallido / rechazado
  | "info"      // procesando / en curso
  | "default";  // genérico

/**
 * Set canónico de estados — cualquier `status` que aparezca en el
 * portal cliente DEBE pasar por este mapeo para tener el mismo label
 * y el mismo tono en cualquier pantalla.
 */
const STATUS_TABLE: Record<string, { label: string; tone: StatusBadgeTone }> = {
  // Position lifecycle
  active:                    { label: "Activa",                tone: "success" },
  matured:                   { label: "Vencida",               tone: "default" },
  redeemed:                  { label: "Rescatada",             tone: "default" },
  cancelled:                 { label: "Cancelada",             tone: "default" },
  pending_onchain:           { label: "Detectando depósito",   tone: "warning" },
  expired_pending_onchain:   { label: "Expirada sin depósito", tone: "danger"  },

  // Transactions / movements
  confirmed:                 { label: "Completado",            tone: "success" },
  pending:                   { label: "Pendiente",             tone: "warning" },
  processing:                { label: "Procesando",            tone: "info"    },
  failed:                    { label: "Fallido",               tone: "danger"  },
  rejected:                  { label: "Rechazado",             tone: "danger"  },

  // KYB / onboarding
  approved:                  { label: "Aprobado",              tone: "success" },
  in_review:                 { label: "En revisión",           tone: "info"    },
  needs_info:                { label: "Falta info",            tone: "warning" },
};

export function statusLabel(raw: string | undefined | null): string {
  if (!raw) return "—";
  return STATUS_TABLE[raw]?.label ?? raw;
}

export function statusTone(raw: string | undefined | null): StatusBadgeTone {
  if (!raw) return "default";
  return STATUS_TABLE[raw]?.tone ?? "default";
}

// ---------------------------------------------------------------------------
// Number / currency formatting — Feb 2026 single-convention rule
// ---------------------------------------------------------------------------
// ARSa  → 1.234,56 ARSa   (es-AR convention, peso digital)
// USDC  → 1,234.56 USDC   (en-US convention, dólar digital)
//
// Each currency stays in its own format across the entire portal. No mixing.

const ARSA_FMT = new Intl.NumberFormat("es-AR", {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
});
const USDC_FMT = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
});

export function fmtAmount(value: number, asset: "arsa" | "usdc" | "ARSa" | "USDC"): string {
  const a = String(asset).toLowerCase();
  if (a === "arsa") return `${ARSA_FMT.format(value)} ARSa`;
  return `${USDC_FMT.format(value)} USDC`;
}

/** Same as fmtAmount but without the unit suffix — útil en columnas de
 *  tabla donde la unidad está en el header. */
export function fmtAmountBare(value: number, asset: "arsa" | "usdc" | "ARSa" | "USDC"): string {
  return String(asset).toLowerCase() === "arsa"
    ? ARSA_FMT.format(value)
    : USDC_FMT.format(value);
}

// ---------------------------------------------------------------------------
// Dates — single format `dd/mm/aaaa` (Argentina) for the entire portal
// ---------------------------------------------------------------------------
const DATE_FMT = new Intl.DateTimeFormat("es-AR", {
  day: "2-digit", month: "2-digit", year: "numeric",
});
const DATETIME_FMT = new Intl.DateTimeFormat("es-AR", {
  day: "2-digit", month: "2-digit", year: "numeric",
  hour: "2-digit", minute: "2-digit",
});

export function fmtDate(iso: string | Date | undefined | null): string {
  if (!iso) return "—";
  try {
    const d = typeof iso === "string" ? new Date(iso) : iso;
    return DATE_FMT.format(d);
  } catch {
    return "—";
  }
}

export function fmtDateTime(iso: string | Date | undefined | null): string {
  if (!iso) return "—";
  try {
    const d = typeof iso === "string" ? new Date(iso) : iso;
    return DATETIME_FMT.format(d);
  } catch {
    return "—";
  }
}

// ---------------------------------------------------------------------------
// Transaction type labels — paralelo a statusLabel/modalityLabel para que los
// <select> de filtros y las tablas usen la misma fuente de verdad.
// ---------------------------------------------------------------------------
const TYPE_TABLE: Record<string, string> = {
  onramp:        "Carga de fondos",
  offramp:       "Retiro",
  deposit:       "Carga de fondos",
  withdraw:      "Retiro",
  subscribe:     "Inversión",
  redeem:        "Rescate",
  yield_accrual: "Rendimiento devengado",
  payout:        "Pago",
  fee:           "Comisión",
  reversed:      "Revertido",
};

export function typeLabel(raw: string | undefined | null): string {
  if (!raw) return "—";
  return TYPE_TABLE[raw] ?? raw;
}
const MODALITY_TABLE: Record<string, string> = {
  end:        "Al vencimiento",
  month:      "Mensual",
  liquid_v1:  "Líquida",
  liquid:     "Líquida",
  monthly:    "Mensual",
};

export function modalityLabel(raw: string | undefined | null): string {
  if (!raw) return "—";
  return MODALITY_TABLE[raw] ?? raw;
}
