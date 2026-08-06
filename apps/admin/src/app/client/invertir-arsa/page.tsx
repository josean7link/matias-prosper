import { redirect } from "next/navigation";

/**
 * Legacy ARSa invest screen. Superseded by `/client/invest?asset=arsa`,
 * which uses the same modality selector + the new on-chain transfer flow
 * (Feb 2026 P0). Keep the URL alive so older links don't 404.
 */
export default function InvertirArsaRedirect() {
  redirect("/client/invest?asset=arsa");
}
