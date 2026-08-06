import { NavLink, useNavigate } from "react-router-dom";
import { useApp } from "@/contexts/AppContext";
import { cn } from "@/lib/utils";
import Logo from "@/components/Logo";
import CommandPalette from "@/components/CommandPalette";
import AlertsBell from "@/components/AlertsBell";
import {
  ChartBar, Buildings, UserCheck, ShieldCheck, Coins, Stack, Wallet,
  ArrowsLeftRight, Equals, Plugs, Key, LightningSlash, Bell, FileText,
  UsersThree, NotePencil, Gear, SignOut, ArrowsDownUp, House, User,
  CurrencyDollar, Sun, Moon, ArrowSquareOut, ShieldCheckered,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import api from "@/lib/api";

const backofficeNav = [
  { to: "/app", label: "Dashboard", icon: ChartBar, end: true },
  { to: "/app/clients", label: "Clients", icon: Buildings },
  { to: "/app/onboarding", label: "Onboarding", icon: UserCheck },
  { to: "/app/compliance", label: "Compliance", icon: ShieldCheck },
  { to: "/app/approvals", label: "Operations Queue", icon: ShieldCheckered, badge: "approvals" },
  { to: "/app/funds", label: "Funds", icon: Coins },
  { to: "/app/products", label: "Products", icon: Stack },
  { to: "/app/positions", label: "Positions", icon: NotePencil },
  { to: "/app/treasury", label: "Treasury", icon: Wallet },
  { to: "/app/transactions", label: "Transactions", icon: ArrowsLeftRight },
  { to: "/app/reconciliation", label: "Reconciliation", icon: Equals },
  { to: "/app/integrations", label: "Integrations", icon: Plugs },
  { to: "/app/api-keys", label: "API Keys", icon: Key },
  { to: "/app/webhooks", label: "Webhooks", icon: LightningSlash },
  { to: "/app/alerts", label: "Alerts", icon: Bell },
  { to: "/app/reports", label: "Reports", icon: FileText },
  { to: "/app/users", label: "Users & Roles", icon: UsersThree },
  { to: "/app/audit", label: "Audit Log", icon: NotePencil },
];

const portalNav = [
  { to: "/portal", label: "Overview", icon: House, end: true },
  { to: "/portal/organization", label: "Organization", icon: Buildings },
  { to: "/portal/users", label: "Users", icon: UsersThree },
  { to: "/portal/balances", label: "Balances", icon: Wallet },
  { to: "/portal/transactions", label: "Transactions", icon: ArrowsDownUp },
  { to: "/portal/yield", label: "Yield & Performance", icon: CurrencyDollar },
  { to: "/portal/end-customers", label: "End Customers", icon: User },
  { to: "/portal/integrations", label: "Integrations", icon: Plugs },
  { to: "/portal/api-keys", label: "API Keys", icon: Key },
  { to: "/portal/webhooks", label: "Webhooks", icon: LightningSlash },
  { to: "/portal/reports", label: "Reports", icon: FileText },
  { to: "/portal/compliance", label: "Compliance", icon: ShieldCheck },
  { to: "/portal/settings", label: "Settings", icon: Gear },
];

export default function AppShell({ children, surface = "backoffice" }) {
  const { user, env, switchEnv, theme, toggleTheme, logout } = useApp();
  const navigate = useNavigate();
  const items = surface === "portal" ? portalNav : backofficeNav;
  const otherSurface = surface === "portal" ? "backoffice" : "portal";

  // Pending approvals badge (internal staff only)
  const [pendingApprovals, setPendingApprovals] = useState(0);
  useEffect(() => {
    if (surface !== "backoffice" || !user?.is_internal) return;
    const load = () => api.get("/approvals/pending/count")
      .then(({ data }) => setPendingApprovals(data.count || 0))
      .catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [surface, user?.is_internal]);

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg)" }}>
      {/* Demo banner */}
      <div className="demo-banner px-6 py-2 flex items-center gap-3 text-xs font-mono" data-testid="demo-banner">
        <span className="env-pill" data-env="sandbox">DEMO</span>
        <span>This environment is populated with demo data for exploration. All records are tagged is_demo=true.</span>
      </div>

      {/* Top bar */}
      <header className="h-16 border-b border-[var(--border)] bg-[var(--surface)] flex items-center justify-between px-6 z-30">
        <div className="flex items-center gap-6">
          <Logo size={26} testId="brand-mark" />
          <span className="text-[var(--fg-subtle)] text-lg font-light">/</span>
          <span className="text-[var(--fg-muted)] text-sm uppercase tracking-[0.15em] font-medium">
            {surface === "portal" ? "Client Portal" : "Backoffice"}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Command Palette trigger (visual only - shortcut handled globally) */}
          <button
            onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))}
            className="hidden md:flex items-center gap-2 h-9 px-3 rounded-full border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface-hover)] text-xs text-[var(--fg-muted)] transition-colors"
            data-testid="topbar-search"
            aria-label="Open command palette"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>
            </svg>
            <span>Search…</span>
            <kbd className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-[var(--border)]">⌘K</kbd>
          </button>

          {/* Alerts bell (backoffice internal only) */}
          {surface === "backoffice" && user?.is_internal && <AlertsBell />}

          {/* Pending approvals pill */}
          {surface === "backoffice" && user?.is_internal && pendingApprovals > 0 && (
            <button onClick={() => navigate("/app/approvals")}
                    className="flex items-center gap-1.5 px-3 h-9 rounded-full text-xs font-semibold"
                    style={{ background: "var(--warning)", color: "#fff" }}
                    data-testid="topbar-approvals-badge">
              <ShieldCheckered size={14} weight="fill" />
              {pendingApprovals} pending
            </button>
          )}

          {/* Env switcher */}
          <div className="flex items-center p-1 rounded-full border border-[var(--border)] bg-[var(--surface-2)]" data-testid="env-switcher">
            <button
              className={cn("px-3 py-1 rounded-full text-[11px] font-mono uppercase tracking-wider transition-colors",
                env === "sandbox"
                  ? "bg-[var(--warning)]/15 text-[var(--warning)]"
                  : "text-[var(--fg-subtle)] hover:text-[var(--fg)]")}
              onClick={() => switchEnv("sandbox")}
              data-testid="env-switch-sandbox"
            >Sandbox</button>
            <button
              className={cn("px-3 py-1 rounded-full text-[11px] font-mono uppercase tracking-wider transition-colors",
                env === "production"
                  ? "bg-[var(--success)]/15 text-[var(--success)]"
                  : "text-[var(--fg-subtle)] hover:text-[var(--fg)]")}
              onClick={() => switchEnv("production")}
              data-testid="env-switch-production"
            >Production</button>
          </div>

          {/* Surface switcher */}
          <button
            onClick={() => navigate(`/${otherSurface === "backoffice" ? "app" : "portal"}`)}
            className="btn-pill btn-ghost text-xs h-9 px-4"
            data-testid="switch-surface"
          >
            <ArrowSquareOut size={13} weight="bold" />
            {otherSurface === "backoffice" ? "Backoffice" : "Portal"}
          </button>

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            className="w-9 h-9 rounded-full border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface-hover)] flex items-center justify-center transition-colors"
            data-testid="theme-toggle"
            aria-label="Toggle theme"
          >
            {theme === "dark" ? <Sun size={15} weight="bold" /> : <Moon size={15} weight="bold" />}
          </button>

          {/* User */}
          <div className="flex items-center gap-3 pl-3 border-l border-[var(--border)]">
            {user?.picture && (
              <img src={user.picture} alt={user.name} className="w-8 h-8 rounded-full border border-[var(--border)]" />
            )}
            <div className="text-xs leading-tight">
              <div className="text-[var(--fg)] font-semibold" data-testid="current-user-name">{user?.name}</div>
              <div className="text-[var(--fg-subtle)] font-mono uppercase text-[10px] tracking-wider" data-testid="current-user-role">{user?.platform_role}</div>
            </div>
            <button
              onClick={logout}
              className="ml-1 p-2 rounded-full hover:bg-[var(--surface-hover)] text-[var(--fg-muted)] hover:text-[var(--fg)] transition-colors"
              data-testid="logout-button"
              title="Log out"
            >
              <SignOut size={15} />
            </button>
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className="w-60 border-r border-[var(--border)] bg-[var(--surface)] overflow-y-auto" data-testid="sidebar">
          <nav className="py-3">
            {items.map((item) => {
              const Icon = item.icon;
              const slug = item.label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
              const badgeCount = item.badge === "approvals" ? pendingApprovals : 0;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  data-testid={`nav-${slug}`}
                  className="block"
                >
                  {({ isActive }) => (
                    <div data-active={isActive} className="nav-item">
                      <Icon size={17} weight={isActive ? "fill" : "regular"} />
                      <span className="flex-1">{item.label}</span>
                      {badgeCount > 0 && (
                        <span className="ml-auto text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded-full min-w-[18px] text-center"
                              style={{ background: "var(--warning)", color: "#fff" }}
                              data-testid={`badge-${slug}`}>
                          {badgeCount}
                        </span>
                      )}
                    </div>
                  )}
                </NavLink>
              );
            })}
          </nav>
        </aside>

        {/* Main */}
        <main className="flex-1 overflow-y-auto" data-testid="main-content">
          <div className="p-6 md:p-8 max-w-[1600px]">
            {children}
          </div>
        </main>
      </div>

      {/* Global Command Palette */}
      <CommandPalette />
    </div>
  );
}
