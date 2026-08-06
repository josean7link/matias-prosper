"use client";
import Link from "next/link";
import {
  Shield, Users, ScrollText, Coins, Building2, ArrowRight, Sparkles,
} from "lucide-react";
import { ProsperLogo } from "@/components/ProsperLogo";
import { ThemeToggleStandalone } from "@/components/ThemeToggle";
import { cn } from "@/lib/utils";

type Account = {
  email: string;
  role: string;
  roleLabel: string;
  description: string;
  highlights: string[];
  destination: string;
  destinationLabel: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  accent: "primary" | "success" | "warning" | "danger" | "muted";
  org?: string;
};

const ACCENT: Record<Account["accent"], { bg: string; fg: string; border: string }> = {
  primary: { bg: "bg-primary/10",  fg: "text-primary", border: "border-primary/30" },
  success: { bg: "bg-success/10",  fg: "text-success", border: "border-success/30" },
  warning: { bg: "bg-warning/10",  fg: "text-warning", border: "border-warning/30" },
  danger:  { bg: "bg-danger/10",   fg: "text-danger",  border: "border-danger/30"  },
  muted:   { bg: "bg-surface-hover", fg: "text-fg-muted", border: "border-border"  },
};

const STAFF: Account[] = [
  {
    email: "admin@prosper.foundation",
    role: "super_admin",
    roleLabel: "Super Admin",
    description: "Acceso completo al panel de Prosper. Configuración de plataforma, todos los módulos.",
    highlights: ["Configuración de la plataforma", "Acceso total a Compliance, Operaciones y Negocio", "Decisiones KYC/KYB"],
    destination: "/admin",
    destinationLabel: "Dashboard ejecutivo",
    icon: Shield,
    accent: "danger",
  },
  {
    email: "ops@prosper.foundation",
    role: "admin",
    roleLabel: "Admin Operaciones",
    description: "Operaciones diarias: ledger, lifecycle de transacciones, fondos.",
    highlights: ["Ledger global", "Timeline de transacciones", "Fondos & treasury"],
    destination: "/admin/operations",
    destinationLabel: "Centro de operaciones",
    icon: Coins,
    accent: "primary",
  },
  {
    email: "compliance@prosper.foundation",
    role: "compliance_officer",
    roleLabel: "Compliance Officer",
    description: "KYC, KYB, KYT, risk scoring, alertas y reportes regulatorios.",
    highlights: ["KYB con checklist obligatorio", "KYT transaction monitoring", "SAR / STR drafts"],
    destination: "/admin/compliance/kyc",
    destinationLabel: "Centro de compliance",
    icon: ScrollText,
    accent: "warning",
  },
  {
    email: "finance@prosper.foundation",
    role: "finance",
    roleLabel: "Finance",
    description: "Vista de negocio: clientes, revenue, yields, cohortes de adquisición.",
    highlights: ["Master list de clientes", "Revenue breakdown 12m", "Cohort analysis"],
    destination: "/admin/business/clients",
    destinationLabel: "Portal de negocio",
    icon: Sparkles,
    accent: "success",
  },
];

const CLIENTS: Account[] = [
  {
    email: "client.admin@alemany.capital",
    role: "client_admin",
    roleLabel: "Cliente · Admin",
    description: "Vista cliente: posiciones, depósitos, retiros, perfil.",
    highlights: ["Posiciones e investments", "Depósito / withdraw", "Yield del cliente"],
    destination: "/client",
    destinationLabel: "Portal cliente",
    icon: Building2,
    accent: "primary",
    org: "Alemany Capital",
  },
  {
    email: "client.admin@finpact.io",
    role: "client_admin",
    roleLabel: "Cliente · Admin",
    description: "Segundo cliente seedeado, mismo rol que Alemany pero distinto org.",
    highlights: ["Test multi-tenant isolation", "Distinto risk profile", "Distinto cap config"],
    destination: "/client",
    destinationLabel: "Portal cliente",
    icon: Users,
    accent: "muted",
    org: "Finpact",
  },
];

function magicLink(email: string, dest: string) {
  const next = encodeURIComponent(dest);
  return `/api/v1/auth/dev-login?email=${encodeURIComponent(email)}&next=${next}`;
}

export default function AccessPage() {
  return (
    <div className="min-h-screen bg-bg flex flex-col">
      <header className="px-6 py-5 flex items-center justify-between border-b border-border">
        <ProsperLogo />
        <div className="flex items-center gap-3">
          <Link href="/login"
            data-testid="access-real-login"
            className="text-xs font-mono uppercase tracking-wider text-fg-subtle hover:text-fg">
            Real login →
          </Link>
          <ThemeToggleStandalone />
        </div>
      </header>

      <main className="flex-1 px-6 py-10 sm:py-14">
        <div className="max-w-[1200px] mx-auto" data-testid="access-page">
          {/* Hero */}
          <div className="max-w-2xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full
                            bg-warning/10 text-warning border border-warning/30
                            text-[10px] font-mono uppercase tracking-[0.2em] mb-4"
                 data-testid="access-dev-banner">
              <Sparkles size={11}/> Preview · dev magic links
            </div>
            <h1 className="font-display font-extrabold text-4xl sm:text-5xl text-fg leading-tight mb-3">
              Demo access
            </h1>
            <p className="text-fg-muted text-base max-w-xl">
              Entrá con un click a la cuenta del rol que quieras explorar. En producción
              cada usuario inicia sesión con su email y un código de 4 dígitos.
            </p>
          </div>

          {/* Internal staff */}
          <section className="mt-10" data-testid="access-section-staff">
            <div className="flex items-end justify-between mb-4">
              <h2 className="text-[10px] font-mono uppercase tracking-[0.2em] text-fg-subtle">
                Internal staff · 4 cuentas
              </h2>
              <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
                @prosper.foundation
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {STAFF.map((a) => <AccountCard key={a.email} account={a} />)}
            </div>
          </section>

          {/* Client accounts */}
          <section className="mt-10" data-testid="access-section-clients">
            <div className="flex items-end justify-between mb-4">
              <h2 className="text-[10px] font-mono uppercase tracking-[0.2em] text-fg-subtle">
                Clientes seedeados · 2 cuentas
              </h2>
              <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
                multi-tenant test
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {CLIENTS.map((a) => <AccountCard key={a.email} account={a} />)}
            </div>
          </section>

          {/* Shortcuts */}
          <section className="mt-10" data-testid="access-section-shortcuts">
            <h2 className="text-[10px] font-mono uppercase tracking-[0.2em] text-fg-subtle mb-4">
              Atajos de navegación · {STAFF.length + CLIENTS.length} roles, ∞ pantallas
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
              {[
                { label: "Admin dashboard",    href: "/admin",                          email: "admin@prosper.foundation" },
                { label: "Operaciones · ledger", href: "/admin/operations/transactions", email: "ops@prosper.foundation" },
                { label: "Negocio · revenue",  href: "/admin/business/revenue",         email: "finance@prosper.foundation" },
                { label: "Negocio · cohortes", href: "/admin/business/cohorts",         email: "finance@prosper.foundation" },
                { label: "Compliance · KYC",   href: "/admin/compliance/kyc",           email: "compliance@prosper.foundation" },
                { label: "Compliance · KYB",   href: "/admin/compliance/kyb",           email: "compliance@prosper.foundation" },
                { label: "Compliance · KYT",   href: "/admin/compliance/kyt",           email: "compliance@prosper.foundation" },
                { label: "Compliance · Riesgo", href: "/admin/compliance/risk",         email: "compliance@prosper.foundation" },
              ].map((s) => (
                <a key={s.href} href={magicLink(s.email, s.href)}
                  data-testid={`access-shortcut-${s.href}`}
                  className="prosper-card p-3 hover:border-primary transition-colors group">
                  <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle truncate">
                    {s.email.split("@")[0]}
                  </div>
                  <div className="text-xs text-fg mt-0.5 flex items-center gap-1.5">
                    <span className="truncate">{s.label}</span>
                    <ArrowRight size={11} className="shrink-0 text-fg-subtle group-hover:text-primary
                                                     group-hover:translate-x-0.5 transition-all" />
                  </div>
                </a>
              ))}
            </div>
          </section>

          {/* Tech footer */}
          <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-fg-subtle mt-12">
            <span className="text-fg">/api/v1/auth/dev-login</span> · solo en preview · deshabilitado cuando
            <span className="text-fg ml-1">RESEND_API_KEY</span> esté configurado.
          </p>
        </div>
      </main>

      <footer className="px-6 py-4 text-xs text-fg-subtle font-mono uppercase tracking-[0.18em]
                          border-t border-border">
        © prosper · borderless on-chain financial services
      </footer>
    </div>
  );
}

function AccountCard({ account: a }: { account: Account }) {
  const ac = ACCENT[a.accent];
  const Icon = a.icon;
  return (
    <div
      data-testid={`access-card-${a.email}`}
      className="prosper-card p-5 flex flex-col hover:shadow-card-hover transition-shadow">
      <div className="flex items-start gap-3 mb-3">
        <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center shrink-0",
                            ac.bg, ac.fg)}>
          <Icon size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-display font-bold text-sm text-fg">{a.roleLabel}</h3>
            <span className={cn("inline-flex items-center px-1.5 py-0.5 rounded text-[9px]",
                                 "font-mono uppercase tracking-wider border",
                                 ac.border, ac.fg, ac.bg)}>
              {a.role}
            </span>
          </div>
          <div className="text-[11px] font-mono text-fg-subtle mt-0.5 truncate">{a.email}</div>
          {a.org && (
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-muted mt-1">
              org · {a.org}
            </div>
          )}
        </div>
      </div>

      <p className="text-xs text-fg-muted leading-relaxed">{a.description}</p>

      <ul className="mt-3 space-y-1.5">
        {a.highlights.map((h, i) => (
          <li key={i} className="text-[11px] text-fg-subtle flex items-start gap-1.5">
            <span className={cn("inline-block w-1 h-1 rounded-full mt-1.5 shrink-0", ac.fg.replace("text-", "bg-"))}/>
            <span>{h}</span>
          </li>
        ))}
      </ul>

      <div className="mt-4 flex items-center gap-2">
        <a href={magicLink(a.email, a.destination)}
          data-testid={`access-go-${a.email}`}
          className="prosper-btn-primary flex-1 h-9 text-xs gap-1.5">
          {a.destinationLabel}
          <ArrowRight size={13} />
        </a>
        <button onClick={() => navigator.clipboard?.writeText(a.email)}
          data-testid={`access-copy-${a.email}`}
          title="Copy email"
          className="prosper-btn-ghost h-9 px-3 text-[10px] font-mono uppercase tracking-wider">
          copy
        </button>
      </div>
    </div>
  );
}
