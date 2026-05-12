"use client";
import { useSearchParams, useRouter } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { CheckCircle2, XCircle, Clock, ShieldCheck } from "lucide-react";
import { ProsperLogo } from "@/components/ProsperLogo";
import { api } from "@/lib/api";

/**
 * /apply/simulate — local-dev fallback when AiPrise template IDs are not yet
 * configured. Lets the applicant "simulate" the AiPrise outcome so the end-to-
 * end flow is exercisable without real credentials. In production with real
 * AiPrise templates set, applicants are redirected to AiPrise's hosted UI
 * instead and never see this screen.
 */
export default function ApplySimulatePage() {
  const params = useSearchParams();
  const router = useRouter();
  const sessionId = params.get("session_id");
  const kind = (params.get("kind") || "kyb") as "kyc" | "kyb";
  const next = params.get("next") || "/apply/status";
  const [busy, setBusy] = useState<string | null>(null);

  const decide = async (decision: "approved" | "rejected" | "pending_review") => {
    if (!sessionId) return;
    setBusy(decision);
    try {
      await api("/v1/onboarding/apply/simulate", {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId, decision }),
      });
      toast.success(`Simulated ${decision}`);
      router.push(next);
    } catch (err: any) {
      toast.error(err?.message || "Simulation failed");
    } finally {
      setBusy(null);
    }
  };

  if (!sessionId) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg">
        <p className="text-fg-subtle text-sm">Invalid simulator URL</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-6"
         data-testid="apply-simulate">
      <div className="prosper-card max-w-md w-full p-6">
        <div className="flex items-center gap-2 mb-1">
          <ProsperLogo />
          <span className="ml-auto text-[9px] font-mono uppercase tracking-wider
                            text-warning bg-warning/10 px-1.5 py-0.5 rounded">
            DEV SIM
          </span>
        </div>
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
          AiPrise sandbox · simulator
        </div>
        <h1 className="font-display font-bold text-xl text-fg mt-1 flex items-center gap-2">
          <ShieldCheck size={18} />
          {kind === "kyb" ? "Business" : "Identity"} verification
        </h1>
        <p className="text-xs text-fg-muted mt-2">
          AiPrise template IDs are not configured yet — this screen lets you pick
          the outcome to simulate. With real templates configured, you'll be
          redirected to AiPrise's hosted UI here instead.
        </p>
        <p className="text-[10px] font-mono text-fg-subtle mt-2 break-all">
          session_id: {sessionId}
        </p>

        <div className="mt-5 space-y-2">
          <SimBtn label="Approve" decision="approved" busy={busy}
            icon={<CheckCircle2 size={14} />} onClick={decide}
            className="bg-success text-white hover:bg-success/90"
            testid="sim-approve" />
          <SimBtn label="Hold for review" decision="pending_review" busy={busy}
            icon={<Clock size={14} />} onClick={decide}
            className="bg-warning text-white hover:bg-warning/90"
            testid="sim-review" />
          <SimBtn label="Reject" decision="rejected" busy={busy}
            icon={<XCircle size={14} />} onClick={decide}
            className="bg-danger text-white hover:bg-danger/90"
            testid="sim-reject" />
        </div>

        <Link href="/" className="block mt-5 text-center text-[11px] font-mono
                                   uppercase tracking-wider text-fg-subtle hover:text-fg">
          Cancel
        </Link>
      </div>
    </div>
  );
}

function SimBtn({ label, decision, busy, icon, onClick, className, testid }:
  { label: string; decision: "approved" | "rejected" | "pending_review";
    busy: string | null; icon: React.ReactNode;
    onClick: (d: "approved" | "rejected" | "pending_review") => void;
    className: string; testid: string }) {
  const isBusy = busy === decision;
  return (
    <button onClick={() => onClick(decision)} disabled={busy !== null}
      data-testid={testid}
      className={`w-full h-10 rounded text-sm font-medium flex items-center
                  justify-center gap-2 transition-opacity disabled:opacity-50 ${className}`}>
      {icon} {isBusy ? "…" : label}
    </button>
  );
}
