export function PageHeader({ title, subtitle, kicker }: {
  title: string; subtitle?: string; kicker?: string;
}) {
  return (
    <div className="mb-8" data-testid="page-header">
      {kicker && (
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-1">
          {kicker}
        </div>
      )}
      <h1 className="font-display font-bold text-3xl text-fg leading-tight">{title}</h1>
      {subtitle && <p className="text-sm text-fg-muted mt-1.5">{subtitle}</p>}
    </div>
  );
}

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
