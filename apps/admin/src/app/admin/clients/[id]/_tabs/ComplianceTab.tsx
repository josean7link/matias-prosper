"use client";
import Link from "next/link";
import { Badge } from "@prosper/ui";

export default function ComplianceTab({ orgId, risk }: { orgId: string; risk: any | null }) {
  return (
    <div className="space-y-4" data-testid="tab-content-compliance">
      <div className="prosper-card p-5">
        <h3 className="font-display font-bold text-sm mb-3">Risk score</h3>
        {risk ? (
          <div>
            <div className="flex items-center gap-3">
              <span className="font-display font-extrabold text-3xl">{risk.score}</span>
              <Badge size="md" tone={risk.profile === "critical" ? "danger"
                : risk.profile === "high" ? "warning" : risk.profile === "medium" ? "info" : "success"}>
                {risk.profile}
              </Badge>
            </div>
            <div className="mt-3 space-y-1.5">
              {(risk.drivers || []).map((d: any) => (
                <div key={d.key} className="flex items-center justify-between text-xs">
                  <span>{d.label}</span>
                  <span className="font-mono tabular text-fg-subtle">
                    +{d.score}pts <span className="text-fg-muted">/ peso {d.weight}%</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : <p className="text-fg-subtle text-xs italic">Sin score calculado todavía.</p>}
      </div>

      <div className="prosper-card p-5">
        <h3 className="font-display font-bold text-sm mb-2">Límites & KYB completo</h3>
        <p className="text-xs text-fg-muted mb-3">
          Los caps y la decisión de KYB con checklist se editan desde el módulo Compliance.
        </p>
        <div className="flex gap-2">
          <Link href={`/admin/compliance/limits`}
            className="prosper-btn-ghost h-9 text-xs">Ir a Límites</Link>
          <Link href={`/admin/compliance/kyb`}
            className="prosper-btn-ghost h-9 text-xs">Ir a KYB queue</Link>
          <Link href={`/admin/compliance/risk`}
            className="prosper-btn-ghost h-9 text-xs">Ir a Risk overview</Link>
        </div>
      </div>
    </div>
  );
}
