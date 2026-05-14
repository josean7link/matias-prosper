import Link from "next/link";
import { PublicFooter } from "@/components/PublicFooter";

export const metadata = {
  title: "Términos de Servicio · Prosper",
  description: "Términos de uso de la plataforma Prosper.",
};

export default function TermsPage() {
  return (
    <div className="min-h-screen bg-bg flex flex-col" data-testid="terms-page">
      <header className="border-b border-border">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-5 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-full bg-primary/10 grid place-items-center text-primary">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
                <path d="M12 2c-1.5 3.5-5 4-5 7s3.5 3.5 5 7c1.5-3.5 5-4 5-7s-3.5-3.5-5-7z"/>
              </svg>
            </div>
            <span className="font-display font-bold text-fg lowercase tracking-tight">prosper</span>
          </Link>
          <Link href="/privacy" className="text-xs text-fg-muted hover:text-primary">
            Privacidad →
          </Link>
        </div>
      </header>

      <main className="flex-1">
        <article className="max-w-3xl mx-auto px-4 sm:px-6 py-12 prose prose-sm">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
            Legal
          </div>
          <h1 className="font-display font-bold text-3xl sm:text-4xl text-fg mb-2">
            Términos de Servicio
          </h1>
          <p className="text-xs text-fg-muted font-mono mb-8">
            Última actualización: 14 de mayo de 2026
          </p>

          <Section title="1. Aceptación">
            Estos Términos de Servicio (los <strong>"Términos"</strong>) regulan el uso
            de la plataforma Prosper. Al acceder a la plataforma, el cliente declara haber
            leído, comprendido y aceptado estos Términos. Si no estás de acuerdo, no podés
            utilizar el servicio.
          </Section>

          <Section title="2. Definiciones">
            <ul className="list-disc list-inside">
              <li><strong>Plataforma</strong>: el conjunto de aplicaciones web, APIs e
                  integraciones provistas por Prosper.</li>
              <li><strong>Cliente</strong>: la persona jurídica que firma el contrato
                  de servicio y a través de la cual operan los usuarios.</li>
              <li><strong>Usuario</strong>: la persona física habilitada por el Cliente
                  para operar dentro de la Plataforma.</li>
              <li><strong>Token Prosper (PUSD)</strong>: representación digital del
                  rendimiento generado por los activos subyacentes custodiados por
                  Arvest Trust.</li>
            </ul>
          </Section>

          <Section title="3. Servicios">
            Prosper provee: (i) onboarding KYB/KYC, (ii) onramp/offramp vía Alfred,
            (iii) suscripción y rescate de Token Prosper, (iv) reporting regulatorio
            y (v) integraciones API + Webhooks. Los servicios pueden modificarse con
            preaviso de 30 días.
          </Section>

          <Section title="4. Obligaciones del Cliente">
            El Cliente se compromete a: (a) proveer información veraz durante el KYB,
            (b) mantener actualizados los UBOs y documentación societaria, (c) cumplir
            con las normas de PLA/FT aplicables, (d) custodiar las API keys y no
            compartirlas con terceros, (e) notificar incidentes de seguridad dentro
            de las 24 horas.
          </Section>

          <Section title="5. Cumplimiento regulatorio">
            Prosper opera bajo el marco del registro PSAV de la CNV (Argentina), con
            custodio fiduciario Arvest Trust y depositario Caja de Valores. Las
            transacciones están sujetas a Travel Rule (umbral USD 1.000), sanctions
            screening y monitoreo continuo (KYT).
          </Section>

          <Section title="6. Limitación de responsabilidad">
            Prosper no es responsable por: pérdidas derivadas de fluctuaciones de
            mercado, errores en las redes blockchain subyacentes, interrupciones
            operativas de proveedores externos (Alfred, Stellar), o uso indebido
            de credenciales del Cliente. El monto máximo de responsabilidad agregada
            se limita a las comisiones efectivamente pagadas por el Cliente en los
            últimos 12 meses.
          </Section>

          <Section title="7. Privacidad">
            El tratamiento de datos personales se rige por nuestra{" "}
            <Link href="/privacy" className="text-primary hover:underline">
              Política de Privacidad
            </Link>.
          </Section>

          <Section title="8. Terminación">
            Cualquiera de las partes puede rescindir el contrato con preaviso de 90
            días. Prosper puede suspender inmediatamente la cuenta del Cliente ante
            sospechas fundadas de lavado de activos, fraude o incumplimiento material
            de estos Términos.
          </Section>

          <Section title="9. Ley aplicable y jurisdicción">
            Estos Términos se rigen por las leyes de la República Argentina. Cualquier
            controversia será sometida a los tribunales ordinarios de la Ciudad
            Autónoma de Buenos Aires.
          </Section>

          <Section title="10. Contacto">
            Para consultas legales o regulatorias:{" "}
            <a href="mailto:legal@prosper.foundation"
               className="text-primary hover:underline">legal@prosper.foundation</a>.
          </Section>
        </article>
      </main>

      <PublicFooter />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="font-display font-bold text-lg text-fg mb-2">{title}</h2>
      <div className="text-sm text-fg-muted leading-relaxed space-y-2">{children}</div>
    </section>
  );
}
