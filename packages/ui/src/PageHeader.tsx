import { ChevronRight } from "lucide-react";

export interface Breadcrumb {
  label: string;
  href?: string;
}

export interface PageHeaderProps {
  /** Main page title — rendered in Chivo bold. */
  title: string;
  /** Optional one-line subtitle below the title. */
  subtitle?: string;
  /** Optional small all-caps kicker rendered above the title. */
  kicker?: string;
  /** Breadcrumb trail (rendered above the kicker). The last item is never linked. */
  breadcrumbs?: Breadcrumb[];
  /** Right-side action slot — typically Buttons, env pills, filters, etc. */
  actions?: React.ReactNode;
  /** Override the default bottom spacing. */
  className?: string;
}

export function PageHeader({
  title, subtitle, kicker, breadcrumbs, actions, className,
}: PageHeaderProps) {
  return (
    <header
      className={`mb-8 ${className ?? ""}`}
      data-testid="page-header"
    >
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav
          aria-label="Breadcrumb"
          className="mb-3 flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-[0.12em] text-fg-subtle"
          data-testid="page-breadcrumbs"
        >
          {breadcrumbs.map((crumb, i) => {
            const isLast = i === breadcrumbs.length - 1;
            return (
              <span key={`${crumb.label}-${i}`} className="inline-flex items-center gap-1.5">
                {crumb.href && !isLast ? (
                  <a
                    href={crumb.href}
                    className="hover:text-fg transition-colors"
                  >
                    {crumb.label}
                  </a>
                ) : (
                  <span className={isLast ? "text-fg-muted" : ""}>{crumb.label}</span>
                )}
                {!isLast && <ChevronRight size={11} className="opacity-60" />}
              </span>
            );
          })}
        </nav>
      )}

      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div className="min-w-0 flex-1">
          {kicker && (
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-1">
              {kicker}
            </div>
          )}
          <h1 className="font-display font-bold text-3xl sm:text-[34px] text-fg leading-tight tracking-tight">
            {title}
          </h1>
          {subtitle && (
            <p className="text-sm text-fg-muted mt-1.5 max-w-2xl">
              {subtitle}
            </p>
          )}
        </div>

        {actions && (
          <div
            className="flex items-center gap-2 shrink-0"
            data-testid="page-header-actions"
          >
            {actions}
          </div>
        )}
      </div>
    </header>
  );
}
