import Link from "next/link";
import { PublicFooter } from "@/components/PublicFooter";

export const metadata = {
  title: "Política de Privacidad · Prosper",
  description: "Cómo Prosper recolecta, usa y protege tus datos personales.",
};

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-bg flex flex-col" data-testid="privacy-page">
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
          <Link href="/terms" className="text-xs text-fg-muted hover:text-primary">
            ← Términos
          </Link>
        </div>
      </header>

      <main className="flex-1">
        <article className="max-w-3xl mx-auto px-4 sm:px-6 py-12">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
            Legal
          </div>
          <h1 className="font-display font-bold text-3xl sm:text-4xl text-fg mb-2">
            Política de Privacidad
          </h1>
          <p className="text-xs text-fg-muted font-mono mb-8">
            Última actualización: 14 de mayo de 2026
          </p>

          <Section title="1. Datos que recolectamos">
            <ul className="list-disc list-inside">
              <li><strong>Identidad</strong>: nombre, DNI/Pasaporte, fecha de nacimiento,
                  nacionalidad, dirección.</li>
              <li><strong>Empresa</strong>: razón social, CUIT/Tax ID, jurisdicción,
                  estructura societaria, UBOs.</li>
              <li><strong>Contacto</strong>: email, teléfono, dirección postal.</li>
              <li><strong>Operacionales</strong>: transacciones, balances, dirección
                  Stellar, IPs y dispositivos.</li>
              <li><strong>Documentos KYB/KYC</strong>: certificados, estados financieros,
                  proof of address.</li>
            </ul>
          </Section>

          <Section title="2. Cómo usamos los datos">
            <ul className="list-disc list-inside">
              <li>Onboarding y due diligence regulatoria (AiPrise + Travel Rule + Sanctions).</li>
              <li>Provisión y mejora del servicio.</li>
              <li>Cumplimiento de obligaciones contables, impositivas y regulatorias
                  (UIF, AFIP, CNV).</li>
              <li>Notificaciones operativas y de seguridad.</li>
              <li>Análisis agregado y anónimo para mejorar la plataforma.</li>
            </ul>
          </Section>

          <Section title="3. Compartido con terceros">
            Compartimos datos estrictamente necesarios con:
            <ul className="list-disc list-inside mt-2">
              <li><strong>AiPrise</strong> — verificación KYB/KYC.</li>
              <li><strong>TRM Labs</strong> — screening de wallets on-chain.</li>
              <li><strong>Alfred</strong> — onramp / offramp fiat.</li>
              <li><strong>Arvest Trust</strong> — custodio fiduciario.</li>
              <li><strong>Resend</strong> — entrega de emails transaccionales.</li>
              <li><strong>Autoridades regulatorias</strong> — UIF, CNV, AFIP, ante
                  requerimientos formales.</li>
            </ul>
          </Section>

          <Section title="4. Retención">
            Conservamos los datos: (a) durante la vigencia de la relación contractual,
            (b) por <strong>10 años adicionales</strong> luego de la baja, conforme a
            la Ley 25.246 de PLA/FT y normativa complementaria.
          </Section>

          <Section title="5. Tus derechos">
            Conforme a la Ley 25.326 de Protección de Datos Personales, podés solicitar:
            acceso, rectificación, actualización, supresión o portabilidad de tus datos.
            Algunos derechos pueden estar limitados por obligaciones regulatorias de
            retención. Escribinos a{" "}
            <a className="text-primary hover:underline"
               href="mailto:privacy@prosper.foundation">privacy@prosper.foundation</a>.
          </Section>

          <Section title="6. Seguridad">
            <ul className="list-disc list-inside">
              <li>Encriptación en reposo (AES-256) y en tránsito (TLS 1.3).</li>
              <li>MFA TOTP disponible para todos los usuarios.</li>
              <li>Logs de auditoría inmutables.</li>
              <li>Backups encriptados con retención de 30 días.</li>
              <li>Penetration testing anual por proveedor externo.</li>
            </ul>
          </Section>

          <Section title="7. Cookies">
            Usamos cookies estrictamente necesarias para la autenticación (cookie
            <code className="text-xs bg-bg-muted px-1 rounded mx-1">prosper_session</code>,
            HttpOnly + Secure + SameSite=Lax). No usamos cookies de tracking ni de
            terceros con fines publicitarios.
          </Section>

          <Section title="8. Cambios">
            Actualizaremos esta Política periódicamente. Te notificaremos por email
            los cambios materiales con 30 días de anticipación.
          </Section>

          <Section title="9. Contacto del Oficial de Protección de Datos">
            <a className="text-primary hover:underline"
               href="mailto:dpo@prosper.foundation">dpo@prosper.foundation</a>
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
