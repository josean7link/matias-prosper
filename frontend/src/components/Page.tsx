/**
 * Re-exports + local-only helpers for app pages.
 * PageHeader now lives in @prosper/ui — import it from there directly.
 */
export { PageHeader } from "@prosper/ui";
export type { Breadcrumb } from "@prosper/ui";

export function ComingSoon({ what }: { what: string }) {
  return (
    <div className="prosper-card p-12 text-center" data-testid="coming-soon">
      <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-primary mb-2">
        Próximamente
      </div>
      <h2 className="font-display font-bold text-2xl text-fg mb-2">{what}</h2>
      <p className="text-sm text-fg-muted max-w-md mx-auto">
        Esta sección estará disponible en las próximas fases del desarrollo. Estamos
        construyendo Prosper en 12 fases — esta es la Fase 0 (bootstrap).
      </p>
    </div>
  );
}
