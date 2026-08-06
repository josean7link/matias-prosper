"use client";
import Link from "next/link";
import {
  ArrowRight, ShieldCheck, Sparkles, Wallet, TrendingUp,
  CheckCircle2, Globe, LockKeyhole,
} from "lucide-react";
import { ProsperLogo } from "@/components/ProsperLogo";
import { ThemeToggleStandalone } from "@/components/ThemeToggle";

export default function HomePage() {
  return (
    <div className="min-h-screen bg-bg flex flex-col" data-testid="landing-page">
      {/* ----------- Top nav ----------- */}
      <header className="border-b border-border bg-bg/80 backdrop-blur sticky top-0 z-30">
        <div className="max-w-[1200px] mx-auto px-6 h-16 flex items-center justify-between">
          <ProsperLogo />
          <nav className="flex items-center gap-3">
            <Link
              href="/login"
              data-testid="landing-cta-login"
              className="prosper-btn-ghost h-9 px-4 text-xs font-mono uppercase tracking-wider"
            >
              Ya tengo cuenta
            </Link>
            <Link
              href="/apply"
              data-testid="landing-cta-apply-nav"
              className="prosper-btn-primary h-9 px-4 text-xs font-mono uppercase tracking-wider gap-1.5"
            >
              Abrir cuenta <ArrowRight size={12} />
            </Link>
            <span className="hidden sm:inline-flex"><ThemeToggleStandalone /></span>
          </nav>
        </div>
      </header>

      {/* ----------- Hero ----------- */}
      <main className="flex-1">
        <section className="max-w-[1200px] mx-auto px-6 pt-16 pb-12 sm:pt-24 sm:pb-20">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <div>
              <div
                className="inline-flex items-center gap-2 px-3 py-1 rounded-full
                           bg-primary/10 text-primary border border-primary/30
                           text-[10px] font-mono uppercase tracking-[0.2em] mb-5"
                data-testid="landing-kicker"
              >
                <Sparkles size={11}/> Pesos digitales · Yield on-chain
              </div>
              <h1 className="font-display font-extrabold text-4xl sm:text-5xl lg:text-6xl
                             text-fg leading-[1.05] tracking-tight mb-5">
                Tu plata en pesos.
                <br />
                <span className="text-primary">Rendimiento en dólares.</span>
              </h1>
              <p className="text-base sm:text-lg text-fg-muted max-w-xl mb-8 leading-relaxed">
                Abrí tu cuenta Prosper en minutos. Cargá pesos a tu CVU, los convertimos a ARSa
                (peso digital 1:1) e invertí en yield real respaldado por dólares — todo on-chain,
                sin abandonar pesos.
              </p>

              <div className="flex flex-col sm:flex-row gap-3" data-testid="landing-hero-ctas">
                <Link
                  href="/apply"
                  data-testid="landing-cta-apply"
                  className="prosper-btn-primary h-12 px-6 text-sm gap-2"
                >
                  Abrir cuenta gratis <ArrowRight size={14} />
                </Link>
                <Link
                  href="/login"
                  data-testid="landing-cta-already"
                  className="prosper-btn-ghost h-12 px-6 text-sm border border-border"
                >
                  Ya tengo cuenta
                </Link>
              </div>

              <ul className="mt-7 flex flex-wrap gap-x-5 gap-y-2 text-xs text-fg-subtle">
                {[
                  "5 minutos · 100% online",
                  "CVU propio · alias propio",
                  "Custodiado por Prosper",
                ].map((t) => (
                  <li key={t} className="inline-flex items-center gap-1.5">
                    <CheckCircle2 size={12} className="text-success"/> {t}
                  </li>
                ))}
              </ul>
            </div>

            {/* Visual block — large ARSa balance card-mockup */}
            <div className="relative">
              <div
                className="rounded-2xl border border-primary/30 p-7 shadow-card-hover
                           bg-gradient-to-br from-primary/95 via-primary to-[#1942C5]
                           text-white"
                data-testid="landing-hero-card"
              >
                <div className="flex items-center justify-between mb-6">
                  <div className="text-[10px] font-mono uppercase tracking-[0.2em] opacity-70">
                    Tu cuenta ARSa
                  </div>
                  <span className="text-[10px] font-mono uppercase tracking-wider
                                   px-2 py-0.5 rounded-full bg-white/15">
                    peso digital · 1:1
                  </span>
                </div>
                <div className="text-[11px] font-mono uppercase tracking-wider opacity-70 mb-1">
                  Saldo disponible
                </div>
                <div className="font-display font-extrabold text-5xl tabular tracking-tight mb-6">
                  $ 1.250.000,00
                </div>
                <dl className="grid grid-cols-2 gap-4 text-xs">
                  <div>
                    <dt className="opacity-70 mb-0.5">CVU</dt>
                    <dd className="font-mono">0000 0037 35•• •• •• 17</dd>
                  </div>
                  <div>
                    <dt className="opacity-70 mb-0.5">Alias</dt>
                    <dd className="font-mono">tu.alias.andes</dd>
                  </div>
                </dl>
                <div className="mt-6 pt-5 border-t border-white/20 grid grid-cols-2 gap-3 text-xs">
                  <div className="bg-white/10 rounded-lg px-3 py-2">
                    <div className="opacity-70 text-[10px] font-mono uppercase tracking-wider">
                      Yield acumulado
                    </div>
                    <div className="font-display font-bold text-lg">+ US$ 42,18</div>
                  </div>
                  <div className="bg-white/10 rounded-lg px-3 py-2">
                    <div className="opacity-70 text-[10px] font-mono uppercase tracking-wider">
                      APR promedio
                    </div>
                    <div className="font-display font-bold text-lg">7,5 %</div>
                  </div>
                </div>
              </div>
              <div
                className="absolute -bottom-3 -right-3 h-32 w-32 rounded-full
                           bg-primary/20 blur-3xl -z-10"
                aria-hidden
              />
            </div>
          </div>
        </section>

        {/* ----------- Steps ----------- */}
        <section
          className="border-y border-border bg-surface/50 py-14"
          data-testid="landing-steps"
        >
          <div className="max-w-[1200px] mx-auto px-6">
            <div className="mb-10 max-w-xl">
              <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-fg-subtle mb-2">
                Cómo funciona
              </div>
              <h2 className="font-display font-bold text-3xl text-fg">
                Tres pasos. Cinco minutos.
              </h2>
            </div>
            <ol className="grid md:grid-cols-3 gap-5">
              {[
                {
                  n: "01",
                  icon: <ShieldCheck size={16} />,
                  title: "Verificá tu identidad",
                  msg: "Cargás 3 fotos (selfie + DNI frente y dorso) desde el navegador. Validamos automáticamente con Andes.",
                },
                {
                  n: "02",
                  icon: <Wallet size={16} />,
                  title: "Recibí tu CVU",
                  msg: "Te emitimos un CVU + alias propios. Transferí pesos desde cualquier banco; se acreditan como ARSa al instante.",
                },
                {
                  n: "03",
                  icon: <TrendingUp size={16} />,
                  title: "Invertí y ganá yield",
                  msg: "Tus pesos generan yield respaldado por dólares on-chain. Retirás cuando quieras a tu CVU original.",
                },
              ].map((s) => (
                <li
                  key={s.n}
                  className="prosper-card p-5"
                  data-testid={`landing-step-${s.n}`}
                >
                  <div className="flex items-center gap-3 mb-3">
                    <div className="h-9 w-9 rounded-full bg-primary/10 text-primary
                                    flex items-center justify-center">
                      {s.icon}
                    </div>
                    <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
                      Paso {s.n}
                    </span>
                  </div>
                  <h3 className="font-display font-bold text-lg text-fg mb-1">{s.title}</h3>
                  <p className="text-sm text-fg-muted leading-relaxed">{s.msg}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ----------- Trust ----------- */}
        <section className="max-w-[1200px] mx-auto px-6 py-14" data-testid="landing-trust">
          <div className="grid md:grid-cols-3 gap-5">
            {[
              {
                icon: <ShieldCheck size={16} />,
                title: "Compliance regulado",
                msg: "KYC/KYB en tiempo real con Andes Labs. Operamos bajo el stack regulatorio CNV + Arvest + Caja de Valores.",
              },
              {
                icon: <LockKeyhole size={16} />,
                title: "Custodia institucional",
                msg: "Tus activos quedan custodiados por Moody's-rated infrastructure. Cada peso ARSa está respaldado 1:1.",
              },
              {
                icon: <Globe size={16} />,
                title: "Pesos sin fricción",
                msg: "Cargás y retirás en pesos, vía CVU/alias. Sin comisiones por carga ni comisión de salida. Yield 100% en dólares.",
              },
            ].map((t, i) => (
              <div key={i} className="flex items-start gap-3" data-testid={`landing-trust-${i}`}>
                <div className="h-9 w-9 rounded-lg bg-success/10 text-success
                                flex items-center justify-center shrink-0">
                  {t.icon}
                </div>
                <div>
                  <h3 className="font-display font-bold text-sm text-fg mb-1">{t.title}</h3>
                  <p className="text-xs text-fg-muted leading-relaxed">{t.msg}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ----------- Final CTA ----------- */}
        <section className="max-w-[1200px] mx-auto px-6 pb-20" data-testid="landing-final-cta">
          <div className="prosper-card p-8 sm:p-12 flex flex-col sm:flex-row items-start
                          sm:items-center justify-between gap-5">
            <div>
              <h3 className="font-display font-bold text-2xl sm:text-3xl text-fg mb-2">
                Empezá hoy
              </h3>
              <p className="text-sm text-fg-muted max-w-md">
                Apertura 100% online, sin papeleo, sin sucursales. Apto para personas físicas con CUIT argentino.
              </p>
            </div>
            <div className="flex flex-col sm:flex-row gap-2.5">
              <Link
                href="/apply"
                data-testid="landing-cta-apply-bottom"
                className="prosper-btn-primary h-11 px-6 text-sm gap-2"
              >
                Abrir cuenta <ArrowRight size={14} />
              </Link>
              <Link
                href="/login"
                data-testid="landing-cta-login-bottom"
                className="prosper-btn-ghost h-11 px-5 text-sm border border-border"
              >
                Iniciar sesión
              </Link>
            </div>
          </div>
        </section>
      </main>

      {/* ----------- Footer ----------- */}
      <footer className="border-t border-border bg-bg">
        <div className="max-w-[1200px] mx-auto px-6 py-8 flex flex-col sm:flex-row
                        items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <ProsperLogo />
            <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-fg-subtle">
              borderless on-chain financial services
            </span>
          </div>
          <ul className="flex items-center gap-5 text-[11px] font-mono uppercase tracking-wider
                         text-fg-subtle">
            <li><Link href="/status"  className="hover:text-fg">Status</Link></li>
            <li><Link href="/terms"   className="hover:text-fg">Términos</Link></li>
            <li><Link href="/privacy" className="hover:text-fg">Privacidad</Link></li>
            <li>
              <Link href="/access" className="hover:text-fg" data-testid="landing-access-staff">
                Acceso staff
              </Link>
            </li>
          </ul>
        </div>
      </footer>
    </div>
  );
}
