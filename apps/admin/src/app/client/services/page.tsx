import { redirect } from "next/navigation";

/**
 * Legacy placeholder route. The "Servicios futuros" copy was a Fase 0
 * scaffolding page that never had real content. We collapse it into the
 * regular dashboard so any deep-link still lands somewhere coherent.
 */
export default function ServicesRedirect() {
  redirect("/client");
}
