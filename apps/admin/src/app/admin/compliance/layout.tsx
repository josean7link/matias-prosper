"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  UserCheck, Building2, Activity, AlertTriangle, Bell, Sliders, ShieldX,
} from "lucide-react";
import { cn } from "@/lib/utils";

const SUBNAV = [
  { href: "/admin/compliance/kyc",       i18nKey: "subnav_kyc",       icon: UserCheck     },
  { href: "/admin/compliance/kyb",       i18nKey: "subnav_kyb",       icon: Building2     },
  { href: "/admin/compliance/sanctions", i18nKey: "subnav_sanctions", icon: ShieldX       },
  { href: "/admin/compliance/kyt",       i18nKey: "subnav_kyt",       icon: Activity      },
  { href: "/admin/compliance/risk",      i18nKey: "subnav_risk",      icon: AlertTriangle },
  { href: "/admin/compliance/alerts",    i18nKey: "subnav_alerts",    icon: Bell          },
  { href: "/admin/compliance/limits",    i18nKey: "subnav_limits",    icon: Sliders       },
];

export default function ComplianceLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const t = useTranslations("admin.compliance");
  return (
    <div className="flex gap-6" data-testid="compliance-layout">
      <aside className="w-56 shrink-0">
        <div className="prosper-card p-1.5 sticky top-4">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em]
                          text-fg-subtle px-3 py-2">{t("section_label")}</div>
          <nav className="space-y-0.5">
            {SUBNAV.map(({ href, i18nKey, icon: Icon }) => {
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
                  <Icon size={14} /> {t(i18nKey as any)}
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
