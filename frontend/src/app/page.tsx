import { redirect } from "next/navigation";

export default function HomePage() {
  // Default landing: Admin home. Auth middleware redirects to /login if no session.
  redirect("/admin");
}
