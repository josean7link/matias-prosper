"use client";
import { notFound, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { KybCard, KybShell, buttonCls, inputCls, labelCls, kybEnabled }
  from "../../_components/KybShell";

function flag(iso2: string): string {
  return String.fromCodePoint(
    ...iso2.toUpperCase().split("").map((c) => 127397 + c.charCodeAt(0)));
}

const COUNTRIES: Array<[string, string]> = [
  ["AR", "Argentina"], ["BO", "Bolivia"], ["BR", "Brasil"], ["CA", "Canadá"],
  ["CL", "Chile"], ["CO", "Colombia"], ["CR", "Costa Rica"],
  ["DE", "Alemania"], ["DO", "Rep. Dominicana"], ["EC", "Ecuador"],
  ["ES", "España"], ["FR", "Francia"], ["GB", "Reino Unido"],
  ["GT", "Guatemala"], ["HN", "Honduras"], ["IT", "Italia"],
  ["MX", "México"], ["NL", "Países Bajos"], ["NI", "Nicaragua"],
  ["PA", "Panamá"], ["PE", "Perú"], ["PT", "Portugal"], ["PY", "Paraguay"],
  ["SV", "El Salvador"], ["US", "Estados Unidos"], ["UY", "Uruguay"],
  ["VE", "Venezuela"],
];

export default function KybSignupCountryPage() {
  if (!kybEnabled()) notFound();
  const router = useRouter();
  const [country, setCountry] = useState("AR");
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
      await api("/v1/kyb/signup/country", {
        method: "POST",
        body: JSON.stringify({ signup_token: token, country }),
      });
      router.push("/kyb/signup/check-email");
    } catch (err: any) {
      toast.error(err?.message || "No pudimos guardar el país");
      if (err?.status === 401) router.push("/kyb/signup");
    } finally {
      setBusy(false);
    }
  }

  return (
    <KybShell step="Paso 3 de 3">
      <KybCard title="País de tu empresa"
               subtitle="Selecciona el país de creación de tu empresa.">
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className={labelCls} htmlFor="kyb-country">País</label>
            <select id="kyb-country" data-testid="kyb-country-select"
                    value={country} className={inputCls}
                    onChange={(e) => setCountry(e.target.value)}>
              {COUNTRIES.map(([iso, name]) => (
                <option key={iso} value={iso}>{flag(iso)} {name}</option>
              ))}
            </select>
          </div>
          <button type="submit" disabled={busy} className={buttonCls}
                  data-testid="kyb-country-submit-button">
            {busy ? "Finalizando…" : "Finalizar"}
          </button>
        </form>
      </KybCard>
    </KybShell>
  );
}
