import { redirect } from "next/navigation";

/**
 * Legacy progress page for the old "invertir-arsa" intent flow (Phase 21).
 * Replaced by the on-chain transfer flow at `/client/invest?asset=arsa`
 * (Feb 2026 P0), where pending placeholders live in `/client/investments`.
 * Anything that linked here ends up at the investments list.
 */
export default function InvertirArsaIdRedirect() {
  redirect("/client/investments");
}
