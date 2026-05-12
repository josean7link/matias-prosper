"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Home, Briefcase, ChartBar, ShieldCheck, Users, LayoutDashboard,
  ArrowDownUp, TrendingUp, Coins, User, Sparkles,
  ChevronLeft, ChevronRight, Bell, LogOut, Moon, Sun,
} from "lucide-react";
import { ProsperLogo } from "./ProsperLogo";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

type NavItem = { href: string; label: string; icon: React.ComponentType<React.SVGProps<SVGSVGElement> & { size?: number | string }>; soon?: boolean };

const ADMIN_NAV: NavItem[] = [
  { href: "/admin",            label: "Home",        icon: Home },
  { href: "/admin/operations", label: "Operaciones", icon: Briefcase, soon: true },
  { href: "/admin/business",   label: "Negocio",     icon: ChartBar, soon: true },
  { href: "/admin/compliance", label: "Compliance",  icon: ShieldCheck, soon: true },
  { href: "/admin/clients",    label: "Clientes",    icon: Users, soon: true },
];

const CLIENT_NAV: NavItem[] = [
  { href: "/client",            label: "Dashboard",         icon: LayoutDashboard },
  { href: "/client/deposit",    label: "Cargar / Retirar",  icon: ArrowDownUp, soon: true },
  { href: "/client/investments",label: "Inversiones",       icon: Coins, soon: true },
  { href: "/client/yield",      label: "Rendimientos",      icon: TrendingUp, soon: true },
  { href: "/client/profile",    label: "Perfil",            icon: User, soon: true },
  { href: "/client/services",   label: "Servicios futuros", icon: Sparkles, soon: true },
];

export function AppShell({
  surface,
  children,
}: {
  surface: "admin" | "client";
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [env, setEnv] = useState<"sandbox" | "production">("production");
  const [email, setEmail] = useState<string>("");
  const [theme, setTheme] = useState<"light" | "dark">("light");

  const nav = surface === "admin" ? ADMIN_NAV : CLIENT_NAV;

  useEffect(() => {
    api<{ email: string }>("/v1/auth/me").then((d) => setEmail(d.email)).catch(() => {});
    setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    document.cookie = `prosper_theme=${next}; path=/; max-age=${365*24*3600}; samesite=lax`;
    setTheme(next);
  };

  const logout = async () => {
    try { await api("/v1/auth/logout", { method: "POST" }); } catch {}
    toast.success("Signed out");
    window.location.href = "/login";
  };

  return (
    <div className="min-h-screen bg-bg text-fg flex">
      {/* Sidebar */}
      <aside
        className={cn(
          "shrink-0 border-r border-border bg-surface transition-all duration-200 flex flex-col",
          collapsed ? "w-[64px]" : "w-[240px]",
        )}
        data-testid="sidebar"
      >
        <div className={cn("h-16 flex items-center border-b border-border", collapsed ? "justify-center" : "px-5")}>
          {collapsed ? (
            <div className="w-7 h-7 rounded bg-primary flex items-center justify-center">
              <span className="font-display font-black text-white text-base">P</span>
            </div>
          ) : (
            <ProsperLogo />
          )}
        </div>

        <nav className="flex-1 px-2 py-4 space-y-0.5">
          {nav.map(({ href, label, icon: Icon, soon }) => {
            const active = pathname === href || (href !== `/${surface}` && pathname.startsWith(href + "/"));
            return (
              <Link
                key={href}
                href={href}
                className="sidebar-link"
                data-active={active}
                data-testid={`nav-${label.toLowerCase().replace(/[^a-z]/g, "-")}`}
              >
                <Icon size={16} />
                {!collapsed && (
                  <>
                    <span className="flex-1 truncate">{label}</span>
                    {soon && (
                      <span className="text-[9px] uppercase tracking-wider font-mono text-fg-subtle bg-bg px-1.5 py-0.5 rounded">
                        Soon
                      </span>
                    )}
                  </>
                )}
              </Link>
            );
          })}
        </nav>

        <button
          onClick={() => setCollapsed(!collapsed)}
          className="m-2 h-8 rounded border border-border hover:bg-surface-hover flex items-center justify-center text-fg-muted"
          aria-label="Toggle sidebar"
          data-testid="sidebar-toggle"
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </aside>

      {/* Main column */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Topbar */}
        <header className="h-16 border-b border-border bg-bg flex items-center justify-between px-6">
          <div className="flex items-center gap-4">
            {surface === "admin" && (
              <div className="flex items-center bg-surface border border-border rounded p-0.5" data-testid="env-switcher">
                {(["sandbox", "production"] as const).map((e) => (
                  <button
                    key={e}
                    onClick={() => setEnv(e)}
                    className={cn(
                      "px-3 py-1 text-[11px] font-mono uppercase tracking-wider rounded transition-colors",
                      env === e ? "bg-primary text-white" : "text-fg-muted hover:text-fg",
                    )}
                    data-testid={`env-${e}`}
                  >
                    {e}
                  </button>
                ))}
              </div>
            )}
            <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle hidden sm:inline">
              {surface === "admin" ? "Admin · Portal" : "Client · Portal"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              className="prosper-btn-ghost h-9 w-9 p-0 relative"
              aria-label="Notifications"
              data-testid="alerts-bell"
            >
              <Bell size={16} />
              <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-primary rounded-full" />
            </button>
            <button
              onClick={toggleTheme}
              className="prosper-btn-ghost h-9 w-9 p-0"
              aria-label="Toggle theme"
              data-testid="topbar-theme-toggle"
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <div className="h-7 w-px bg-border mx-1" />
            <div className="flex items-center gap-3 pl-2" data-testid="user-menu">
              <div className="text-right hidden sm:block">
                <div className="text-xs text-fg truncate max-w-[160px]" data-testid="user-email">{email || "…"}</div>
                <div className="text-[10px] uppercase tracking-wider text-fg-subtle font-mono">
                  {surface === "admin" ? "Internal" : "Partner"}
                </div>
              </div>
              <div className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center font-display font-bold text-sm">
                {email ? email[0].toUpperCase() : "?"}
              </div>
              <button onClick={logout} className="prosper-btn-ghost h-9 w-9 p-0" aria-label="Sign out" data-testid="logout-btn">
                <LogOut size={15} />
              </button>
            </div>
          </div>
        </header>

        {/* Main */}
        <main className="flex-1 overflow-auto">
          <div className="mx-auto max-w-[1440px] px-6 py-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
