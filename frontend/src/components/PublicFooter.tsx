"use client";
import Link from "next/link";

export function PublicFooter() {
  return (
    <footer className="border-t border-border mt-16 pt-8 pb-10"
            data-testid="public-footer">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-8 mb-8">
          <div className="sm:col-span-2">
            <div className="flex items-center gap-2 mb-3">
              <div className="h-7 w-7 rounded-full bg-primary/10 grid place-items-center text-primary">
                <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
                  <path d="M12 2c-1.5 3.5-5 4-5 7s3.5 3.5 5 7c1.5-3.5 5-4 5-7s-3.5-3.5-5-7z"/>
                </svg>
              </div>
              <span className="font-display font-bold text-fg lowercase tracking-tight">prosper</span>
            </div>
            <p className="text-xs text-fg-muted max-w-sm leading-relaxed">
              Plataforma de yield tokenizado para empresas latinoamericanas.
              Onboarding, compliance y operación en una sola consola.
            </p>
          </div>

          <div>
            <h4 className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-3">
              Producto
            </h4>
            <ul className="space-y-2 text-xs">
              <li><FooterLink href="/apply">Aplicar a Prosper</FooterLink></li>
              <li><FooterLink href="/status">Status</FooterLink></li>
              <li><FooterLink href="/access">Acceso demo</FooterLink></li>
            </ul>
          </div>

          <div>
            <h4 className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-3">
              Legal
            </h4>
            <ul className="space-y-2 text-xs">
              <li><FooterLink href="/terms">Términos</FooterLink></li>
              <li><FooterLink href="/privacy">Privacidad</FooterLink></li>
              <li><FooterLink href="mailto:compliance@prosper.foundation">Compliance</FooterLink></li>
            </ul>
          </div>
        </div>

        {/* Regulatory stack ribbon */}
        <div className="border-t border-border pt-6">
          <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-3 text-center">
            Stack regulatorio
          </div>
          <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-xs text-fg-muted">
            <RegItem label="Arvest" sub="Custodio fiduciario" />
            <RegItem label="CNV"    sub="Argentina · Reg. PSAV" />
            <RegItem label="Caja de Valores" sub="Depositario" />
            <RegItem label="Moody's" sub="Rating de activos" />
          </div>
        </div>

        <div className="mt-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-[11px] text-fg-subtle">
          <div>© 2026 Prosper. Todos los derechos reservados.</div>
          <div className="font-mono">v0.2.0 · construido en LATAM</div>
        </div>
      </div>
    </footer>
  );
}

function FooterLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href as never} className="text-fg-muted hover:text-primary transition-colors">
      {children}
    </Link>
  );
}

function RegItem({ label, sub }: { label: string; sub: string }) {
  return (
    <div className="flex flex-col items-center text-center">
      <div className="text-sm font-display font-bold text-fg">{label}</div>
      <div className="text-[10px] text-fg-subtle">{sub}</div>
    </div>
  );
}
