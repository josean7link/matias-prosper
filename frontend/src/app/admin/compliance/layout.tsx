"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  UserCheck, Building2, Activity, AlertTriangle, Bell, Sliders,
} from "lucide-react";
import { cn } from "@/lib/utils";

const SUBNAV = [
  { href: "/admin/compliance/kyc",     label: "KYC",      icon: UserCheck     },
  { href: "/admin/compliance/kyb",     label: "KYB",      icon: Building2     },
  { href: "/admin/compliance/kyt",     label: "KYT",      icon: Activity      },
  { href: "/admin/compliance/risk",    label: "Riesgo",   icon: AlertTriangle },
  { href: "/admin/compliance/alerts",  label: "Alertas",  icon: Bell          },
  { href: "/admin/compliance/limits",  label: "Límites",  icon: Sliders       },
];

export default function ComplianceLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="flex gap-6" data-testid="compliance-layout">
      <aside className="w-56 shrink-0">
        <div className="prosper-card p-1.5 sticky top-4">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em]
                          text-fg-subtle px-3 py-2">Compliance</div>
          <nav className="space-y-0.5">
            {SUBNAV.map(({ href, label, icon: Icon }) => {
              const active = pathname === href || pathname.startsWith(href + "/");
              return (
                <Link key={href} href={href}
                  data-testid={`compl-nav-${href.split("/").pop()}`}
                  className={cn(
                    "flex items-center gap-2 px-3 py-2 rounded text-xs transition-colors",
                    active
                      ? "bg-primary text-white"
                      : "text-fg-muted hover:text-fg hover:bg-surface-hover",
                  )}>
                  <Icon size={14} /> {label}
                </Link>
              );
            })}
          </nav>
        </div>
      </aside>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}
