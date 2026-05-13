"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Home, Briefcase, ChartBar, ShieldCheck, Users, LayoutDashboard,
  ArrowDownUp, TrendingUp, Coins, User, Sparkles,
  ChevronLeft, ChevronRight, LogOut, Moon, Sun,
} from "lucide-react";
import { ProsperLogo } from "./ProsperLogo";
import { SandboxBanner } from "./SandboxBanner";
import AlertsBell from "./AlertsBell";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { useEnvOptional, type Env } from "@/contexts/EnvContext";

type NavItem = { href: string; label: string; icon: React.ComponentType<React.SVGProps<SVGSVGElement> & { size?: number | string }>; soon?: boolean };

const ADMIN_NAV: NavItem[] = [
  { href: "/admin",            label: "Home",        icon: Home },
  { href: "/admin/operations", label: "Operaciones", icon: Briefcase },
  { href: "/admin/business",   label: "Negocio",     icon: ChartBar },
  { href: "/admin/compliance", label: "Compliance",  icon: ShieldCheck },
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
  const envCtx = useEnvOptional();
  const env: Env = envCtx?.env ?? "production";
  const setEnv = envCtx?.setEnv;
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

        {/* Env indicator (admin only, where env switching is exposed) */}
        {surface === "admin" && (
          <SidebarEnvIndicator env={env} collapsed={collapsed} />
        )}

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
            {surface === "admin" && setEnv && (
              <div className="flex items-center bg-surface border border-border rounded p-0.5" data-testid="env-switcher">
                {(["sandbox", "production"] as const).map((e) => {
                  const active = env === e;
                  const tone = e === "sandbox" ? "bg-warning" : "bg-success";
                  return (
                    <button
                      key={e}
                      onClick={() => setEnv(e)}
                      className={cn(
                        "px-3 py-1 text-[11px] font-mono uppercase tracking-wider rounded transition-colors inline-flex items-center gap-1.5",
                        active ? "bg-primary text-white" : "text-fg-muted hover:text-fg",
                      )}
                      data-testid={`env-${e}`}
                    >
                      <span className={cn("w-1.5 h-1.5 rounded-full", tone, active && "ring-2 ring-white/40")} />
                      {e}
                    </button>
                  );
                })}
              </div>
            )}
            <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle hidden sm:inline">
              {surface === "admin" ? "Admin · Portal" : "Client · Portal"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <AlertsBell />
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

        {/* Sandbox banner — only renders when env === "sandbox". Stays right
            between the topbar and the page content, full width of the main
            column, persistent across navigation. */}
        <SandboxBanner />

        {/* Main */}
        <main className="flex-1 overflow-auto">
          <div className="mx-auto max-w-[1440px] px-6 py-8">{children}</div>
        </main>
      </div>
    </div>
  );
}


function SidebarEnvIndicator({
  env,
  collapsed,
}: {
  env: Env;
  collapsed: boolean;
}) {
  const sandbox = env === "sandbox";
  const tone = sandbox
    ? { dot: "#E07B00", bg: "color-mix(in srgb, #E07B00 14%, transparent)", text: "#E07B00", label: "Sandbox" }
    : { dot: "#0FA958", bg: "color-mix(in srgb, #0FA958 14%, transparent)", text: "#0FA958", label: "Production" };

  if (collapsed) {
    return (
      <div className="px-3 pt-3 flex justify-center" data-testid={`sidebar-env-${env}`}>
        <span
          title={`Environment: ${tone.label}`}
          className="w-2.5 h-2.5 rounded-full"
          style={{ background: tone.dot, boxShadow: `0 0 0 3px ${tone.bg}` }}
        />
      </div>
    );
  }

  return (
    <div
      className="mx-3 mt-3 rounded border flex items-center gap-2 px-3 py-2"
      style={{ background: tone.bg, borderColor: `${tone.dot}40` }}
      data-testid={`sidebar-env-${env}`}
    >
      <span
        className={sandbox ? "w-2 h-2 rounded-full animate-pulse" : "w-2 h-2 rounded-full"}
        style={{ background: tone.dot }}
      />
      <div className="flex-1 min-w-0">
        <div className="text-[9px] font-mono uppercase tracking-[0.15em] text-fg-subtle leading-none">
          Environment
        </div>
        <div
          className="text-xs font-mono uppercase tracking-wider font-semibold mt-0.5 leading-none"
          style={{ color: tone.text }}
        >
          {tone.label}
        </div>
      </div>
    </div>
  );
}
