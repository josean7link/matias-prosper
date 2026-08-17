"use client";
/** Shell compartido de las pantallas públicas del signup KYB (Fase 2). */
import Link from "next/link";
import { ProsperLogo } from "@/components/ProsperLogo";

export function kybEnabled(): boolean {
  return process.env.NEXT_PUBLIC_KYB_MODULE_ENABLED === "true";
}

export function KybShell({ children, step }: {
  children: React.ReactNode; step?: string;
}) {
  return (
    <div className="min-h-screen bg-bg flex flex-col" data-testid="kyb-shell">
      <header className="border-b border-border bg-surface">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2" data-testid="kyb-logo-link">
            <ProsperLogo />
          </Link>
          {step && (
            <span className="text-xs text-fg-muted" data-testid="kyb-step-label">{step}</span>
          )}
        </div>
      </header>
      <main className="flex-1 flex items-start justify-center px-4 py-12">
        <div className="w-full max-w-md">{children}</div>
      </main>
      <footer className="border-t border-border py-6 text-center text-xs text-fg-muted">
        Prosper Protocol · Infraestructura de rendimiento regulada por CNV
      </footer>
    </div>
  );
}

export function KybCard({ children, title, subtitle }: {
  children: React.ReactNode; title: string; subtitle?: string;
}) {
  return (
    <div className="bg-surface border border-border rounded-2xl p-8 shadow-sm"
         data-testid="kyb-card">
      <h1 className="text-2xl font-semibold text-fg mb-1">{title}</h1>
      {subtitle && <p className="text-sm text-fg-muted mb-6">{subtitle}</p>}
      {children}
    </div>
  );
}

export const inputCls =
  "w-full rounded-lg border border-border bg-bg px-3.5 py-2.5 text-sm " +
  "text-fg placeholder:text-fg-muted focus:outline-none focus:ring-2 " +
  "focus:ring-primary/40 focus:border-primary transition-colors";

export const buttonCls =
  "w-full rounded-lg bg-primary text-white font-medium py-2.5 text-sm " +
  "hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed " +
  "transition-opacity";

export const labelCls = "block text-sm font-medium text-fg mb-1.5";
