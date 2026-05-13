"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Users2, DollarSign, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

const SUBNAV = [
  { href: "/admin/business/clients", label: "Clientes",   icon: Users2     },
  { href: "/admin/business/revenue", label: "Revenue",    icon: DollarSign },
  { href: "/admin/business/yield",   label: "Rendimientos", icon: TrendingUp },
];

export default function BusinessLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="flex gap-6" data-testid="business-layout">
      <aside className="w-56 shrink-0">
        <div className="prosper-card p-1.5 sticky top-4">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em]
                          text-fg-subtle px-3 py-2">Negocio</div>
          <nav className="space-y-0.5">
            {SUBNAV.map(({ href, label, icon: Icon }) => {
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
