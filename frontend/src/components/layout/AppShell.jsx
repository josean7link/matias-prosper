import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useApp } from "@/contexts/AppContext";
import { cn } from "@/lib/utils";
import { EnvPill, DemoBanner } from "@/components/common";
import {
  ChartBar, Buildings, UserCheck, ShieldCheck, Coins, Stack, Wallet,
  ArrowsLeftRight, Equals, Plugs, Key, LightningSlash, Bell, FileText,
  UsersThree, NotePencil, Gear, SignOut, ArrowsDownUp, House, User, CurrencyDollar
} from "@phosphor-icons/react";

const backofficeNav = [
  { to: "/app", label: "Dashboard", icon: ChartBar, end: true },
  { to: "/app/clients", label: "Clients", icon: Buildings },
  { to: "/app/onboarding", label: "Onboarding", icon: UserCheck },
  { to: "/app/compliance", label: "Compliance", icon: ShieldCheck },
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
  const { user, env, switchEnv, logout } = useApp();
  const location = useLocation();
  const navigate = useNavigate();
  const items = surface === "portal" ? portalNav : backofficeNav;
  const otherSurface = surface === "portal" ? "backoffice" : "portal";

  return (
    <div className="min-h-screen bg-[#050505] text-white flex flex-col">
      <DemoBanner />
      {/* Top bar */}
      <header className="h-14 border-b border-[#1a1a1a] bg-[#080808] flex items-center justify-between px-6 z-30">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 font-display font-black text-lg" data-testid="brand-mark">
            <div className="w-6 h-6 rounded-sm bg-[#0066FF] flex items-center justify-center text-white font-black text-xs">P</div>
            <span>PROSPER</span>
            <span className="text-[#555] font-light mx-2">/</span>
            <span className="text-[#888] font-normal text-sm uppercase tracking-wider">
              {surface === "portal" ? "Client Portal" : "Backoffice"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 border border-[#222] rounded-sm p-0.5" data-testid="env-switcher">
            <button
              className={cn("px-3 py-1 rounded-sm text-xs font-mono uppercase tracking-wider transition-colors",
                env === "sandbox" ? "bg-[#FFAB00]/20 text-[#FFAB00]" : "text-[#888] hover:text-white")}
              onClick={() => switchEnv("sandbox")}
              data-testid="env-switch-sandbox"
            >
              Sandbox
            </button>
            <button
              className={cn("px-3 py-1 rounded-sm text-xs font-mono uppercase tracking-wider transition-colors",
                env === "production" ? "bg-[#00C853]/15 text-[#00C853]" : "text-[#888] hover:text-white")}
              onClick={() => switchEnv("production")}
              data-testid="env-switch-production"
            >
              Production
            </button>
          </div>
          <button
            onClick={() => navigate(`/${otherSurface === "backoffice" ? "app" : "portal"}`)}
            className="text-xs font-mono uppercase tracking-wider text-[#888] hover:text-white border border-[#222] px-3 py-1.5 rounded-sm transition-colors"
            data-testid="switch-surface"
          >
            Go to {otherSurface === "backoffice" ? "Backoffice" : "Portal"}
          </button>
          <div className="flex items-center gap-2 pl-3 border-l border-[#1a1a1a]">
            {user?.picture && (
              <img src={user.picture} alt={user.name} className="w-7 h-7 rounded-full border border-[#222]" />
            )}
            <div className="text-xs leading-tight">
              <div className="text-white font-medium" data-testid="current-user-name">{user?.name}</div>
              <div className="text-[#555] font-mono uppercase text-[10px]" data-testid="current-user-role">{user?.platform_role}</div>
            </div>
            <button
              onClick={logout}
              className="ml-2 p-2 rounded-sm hover:bg-[#111] text-[#888] hover:text-white transition-colors"
              data-testid="logout-button"
              title="Log out"
            >
              <SignOut size={16} />
            </button>
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className="w-56 border-r border-[#1a1a1a] bg-[#080808] overflow-y-auto" data-testid="sidebar">
          <nav className="py-3">
            {items.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn("nav-item flex items-center gap-3 px-4 py-2.5 text-sm text-[#888] hover:bg-[#0f0f0f] hover:text-white border-l-2 border-transparent",
                      isActive && "")
                  }
                  data-testid={`nav-${item.label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`}
                >
                  {({ isActive }) => (
                    <div
                      data-active={isActive}
                      className="nav-item -mx-4 -my-2.5 px-4 py-2.5 flex items-center gap-3 w-[calc(100%+2rem)] border-l-2 border-transparent"
                    >
                      <Icon size={16} weight={isActive ? "fill" : "regular"} />
                      <span className={cn(isActive ? "text-white font-medium" : "")}>{item.label}</span>
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
    </div>
  );
}
