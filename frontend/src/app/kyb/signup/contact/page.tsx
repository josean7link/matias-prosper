"use client";
import { notFound, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { KybCard, KybShell, buttonCls, inputCls, labelCls, kybEnabled }
  from "../../_components/KybShell";

const CODES = [
  { code: "+54", label: "🇦🇷 Argentina (+54)" },
  { code: "+55", label: "🇧🇷 Brasil (+55)" },
  { code: "+56", label: "🇨🇱 Chile (+56)" },
  { code: "+598", label: "🇺🇾 Uruguay (+598)" },
  { code: "+595", label: "🇵🇾 Paraguay (+595)" },
  { code: "+591", label: "🇧🇴 Bolivia (+591)" },
  { code: "+51", label: "🇵🇪 Perú (+51)" },
  { code: "+57", label: "🇨🇴 Colombia (+57)" },
  { code: "+52", label: "🇲🇽 México (+52)" },
  { code: "+593", label: "🇪🇨 Ecuador (+593)" },
  { code: "+1", label: "🇺🇸 EE. UU. / Canadá (+1)" },
  { code: "+34", label: "🇪🇸 España (+34)" },
  { code: "+44", label: "🇬🇧 Reino Unido (+44)" },
];

export default function KybSignupContactPage() {
  if (!kybEnabled()) notFound();
  const router = useRouter();
  const [name, setName] = useState("");
  const [cc, setCc] = useState("+54");
  const [number, setNumber] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const token = sessionStorage.getItem("kyb_signup_token");
    if (!token) {
      toast.error("Tu sesión de registro expiró. Empezá de nuevo desde el primer paso.");
      router.push("/kyb/signup");
      return;
    }
    setBusy(true);
    try {
      await api("/v1/kyb/signup/contact", {
        method: "POST",
        body: JSON.stringify({
          signup_token: token, full_name: name,
          phone: { country_code: cc, number },
        }),
      });
      router.push("/kyb/signup/country");
    } catch (err: any) {
      toast.error(err?.message || "No pudimos guardar tus datos");
      if (err?.status === 401) router.push("/kyb/signup");
    } finally {
      setBusy(false);
    }
  }

  return (
    <KybShell step="Paso 2 de 3">
      <KybCard title="Datos de contacto"
               subtitle="Pedimos estos datos para que podamos comunicarnos contigo y ayudarte a agilizar el proceso de registro.">
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className={labelCls} htmlFor="kyb-fullname">Nombre y apellido</label>
            <input id="kyb-fullname" data-testid="kyb-contact-name-input"
                   type="text" required minLength={2} value={name}
                   className={inputCls} placeholder="Como figura en tu documento"
                   onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="kyb-phone">Teléfono</label>
            <div className="flex gap-2">
              <select value={cc} data-testid="kyb-contact-country-code-select"
                      className={inputCls + " !w-44"}
                      onChange={(e) => setCc(e.target.value)}>
                {CODES.map((c) => (
                  <option key={c.code + c.label} value={c.code}>{c.label}</option>
                ))}
              </select>
              <input id="kyb-phone" data-testid="kyb-contact-phone-input"
                     type="tel" required minLength={5} value={number}
                     className={inputCls} placeholder="11 5555 5555"
                     onChange={(e) => setNumber(e.target.value)} />
            </div>
          </div>
          <button type="submit" disabled={busy} className={buttonCls}
                  data-testid="kyb-contact-submit-button">
            {busy ? "Guardando…" : "Continuar"}
          </button>
        </form>
      </KybCard>
    </KybShell>
  );
}
