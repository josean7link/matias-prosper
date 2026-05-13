import { redirect } from "next/navigation";

export default function HomePage() {
  // Demo-friendly: surface the magic-link landing as the default entry point
  // in preview. Real auth middleware still protects /admin and /client.
  redirect("/access");
}
