"use client";
import Link from "next/link";
import useSWR from "swr";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, Clock, XCircle, RefreshCw } from "lucide-react";
import { ProsperLogo } from "@/components/ProsperLogo";
import { api } from "@/lib/api";
import { Badge } from "@prosper/ui";

interface AppStatus {
  application_id: string;
  org_id: string;
  legal_name: string;
  status: "in_review" | "approved" | "rejected";
  kyb_status: string;
  decision?: string | null;
  submitted_at: string;
  aiprise_mode?: "live" | "simulated" | null;
}

export default function ApplyStatusPage() {
  const params = useSearchParams();
  const appId = params.get("app_id");
  const { data, isLoading, mutate } = useSWR<AppStatus>(
    appId ? `/v1/onboarding/apply/${appId}` : null,
    (p: string) => api(p),
    { refreshInterval: 10_000 },
  );

  if (!appId) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg">
        <p className="text-fg-subtle text-sm">Missing app_id</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-6"
         data-testid="apply-status">
      <div className="prosper-card max-w-md w-full p-7 text-center">
        <div className="flex items-center justify-center gap-2 mb-4">
          <ProsperLogo />
        </div>

        {isLoading || !data ? (
          <p className="text-fg-subtle text-sm">Loading…</p>
        ) : data.status === "approved" ? (
          <Result icon={<CheckCircle2 size={56} className="text-success mx-auto" />}
                  title="Application approved"
                  msg={`Welcome aboard, ${data.legal_name}. Your account is being provisioned.`}
                  testid="status-approved" />
        ) : data.status === "rejected" ? (
          <Result icon={<XCircle size={56} className="text-danger mx-auto" />}
                  title="Application rejected"
                  msg="Our compliance team couldn't approve this application. Please contact us if you believe this is in error."
                  testid="status-rejected" />
        ) : (
          <Result icon={<Clock size={56} className="text-warning mx-auto" />}
                  title="Under review"
                  msg="We've received your application and our compliance team is reviewing it. We'll email you within 1 business day."
                  testid="status-pending" />
        )}

        {data && (
          <div className="mt-6 pt-4 border-t border-border text-left
                          text-[11px] font-mono text-fg-subtle space-y-1">
            <div>app_id · {data.application_id}</div>
            <div>org_id · {data.org_id}</div>
            <div>
              kyb_status · <Badge tone="auto" size="sm">{data.kyb_status}</Badge>
              {data.aiprise_mode === "simulated" && (
                <span className="ml-2 inline-block text-[9px] uppercase
                                  tracking-wider bg-warning/10 text-warning px-1.5 py-0.5 rounded">
                  sim
                </span>
              )}
            </div>
          </div>
        )}

        <div className="mt-5 flex items-center justify-between text-xs">
          <Link href="/" className="text-fg-subtle hover:text-fg
                                     font-mono uppercase tracking-wider">
            Home
          </Link>
          <button onClick={() => mutate()}
                  data-testid="status-refresh"
                  className="text-primary font-mono uppercase tracking-wider
                             flex items-center gap-1 hover:underline">
            <RefreshCw size={11} /> Refresh
          </button>
        </div>
      </div>
    </div>
  );
}

function Result({ icon, title, msg, testid }:
  { icon: React.ReactNode; title: string; msg: string; testid: string }) {
  return (
    <div data-testid={testid}>
      {icon}
      <h1 className="font-display font-bold text-xl text-fg mt-3">{title}</h1>
      <p className="text-sm text-fg-muted mt-2 max-w-xs mx-auto">{msg}</p>
    </div>
  );
}
