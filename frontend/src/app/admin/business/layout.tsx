"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Users2, DollarSign, TrendingUp, GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";

const SUBNAV = [
  { href: "/admin/business/clients", i18nKey: "subnav_clients", icon: Users2     },
  { href: "/admin/business/revenue", i18nKey: "subnav_revenue", icon: DollarSign },
  { href: "/admin/business/yield",   i18nKey: "subnav_yield",   icon: TrendingUp },
  { href: "/admin/business/cohorts", i18nKey: "subnav_cohorts", icon: GitBranch  },
];

export default function BusinessLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const t = useTranslations("admin.business");
  return (
    <div className="flex gap-6" data-testid="business-layout">
      <aside className="w-56 shrink-0">
        <div className="prosper-card p-1.5 sticky top-4">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em]
                          text-fg-subtle px-3 py-2">{t("section_label")}</div>
          <nav className="space-y-0.5">
            {SUBNAV.map(({ href, i18nKey, icon: Icon }) => {
              const active = pathname === href || pathname.startsWith(href + "/");
              return (
                <Link key={href} href={href}
                  data-testid={`biz-nav-${href.split("/").pop()}`}
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
