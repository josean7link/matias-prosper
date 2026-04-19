import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import "@/index.css";
import "@/App.css";
import { Toaster } from "@/components/ui/sonner";
import { AppProvider } from "@/contexts/AppContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import AuthCallback from "@/components/AuthCallback";
import AppShell from "@/components/layout/AppShell";

import Login from "@/pages/Login";

// Backoffice
import Dashboard from "@/pages/backoffice/Dashboard";
import Clients from "@/pages/backoffice/Clients";
import ClientDetail from "@/pages/backoffice/ClientDetail";
import Onboarding from "@/pages/backoffice/Onboarding";
import Compliance from "@/pages/backoffice/Compliance";
import Funds from "@/pages/backoffice/Funds";
import Products from "@/pages/backoffice/Products";
import Positions from "@/pages/backoffice/Positions";
import Treasury from "@/pages/backoffice/Treasury";
import Transactions from "@/pages/backoffice/Transactions";
import Reconciliation from "@/pages/backoffice/Reconciliation";
import Integrations from "@/pages/backoffice/Integrations";
import ApiKeys from "@/pages/backoffice/ApiKeys";
import Webhooks from "@/pages/backoffice/Webhooks";
import Alerts from "@/pages/backoffice/Alerts";
import Reports from "@/pages/backoffice/Reports";
import UsersAdmin from "@/pages/backoffice/UsersAdmin";
import AuditLog from "@/pages/backoffice/AuditLog";

// Portal
import PortalOverview from "@/pages/portal/Overview";
import PortalOrganization from "@/pages/portal/Organization";
import PortalBalances from "@/pages/portal/Balances";
import PortalTransactions from "@/pages/portal/PortalTransactions";
import YieldPage from "@/pages/portal/Yield";
import EndCustomers from "@/pages/portal/EndCustomers";
import PortalSettings from "@/pages/portal/Settings";
import { PortalApiKeys, PortalWebhooks, PortalIntegrations, PortalReports, PortalCompliance, PortalUsers } from "@/pages/portal/Shared";

function InnerRouter() {
  const location = useLocation();

  // Catch OAuth callback if session_id is in the URL fragment
  if (typeof window !== "undefined" && window.location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Login />} />

      {/* Backoffice */}
      <Route path="/app" element={<ProtectedRoute><AppShell surface="backoffice"><Dashboard /></AppShell></ProtectedRoute>} />
      <Route path="/app/clients" element={<ProtectedRoute><AppShell surface="backoffice"><Clients /></AppShell></ProtectedRoute>} />
      <Route path="/app/clients/:id" element={<ProtectedRoute><AppShell surface="backoffice"><ClientDetail /></AppShell></ProtectedRoute>} />
      <Route path="/app/onboarding" element={<ProtectedRoute><AppShell surface="backoffice"><Onboarding /></AppShell></ProtectedRoute>} />
      <Route path="/app/compliance" element={<ProtectedRoute><AppShell surface="backoffice"><Compliance /></AppShell></ProtectedRoute>} />
      <Route path="/app/funds" element={<ProtectedRoute><AppShell surface="backoffice"><Funds /></AppShell></ProtectedRoute>} />
      <Route path="/app/products" element={<ProtectedRoute><AppShell surface="backoffice"><Products /></AppShell></ProtectedRoute>} />
      <Route path="/app/positions" element={<ProtectedRoute><AppShell surface="backoffice"><Positions /></AppShell></ProtectedRoute>} />
      <Route path="/app/treasury" element={<ProtectedRoute><AppShell surface="backoffice"><Treasury /></AppShell></ProtectedRoute>} />
      <Route path="/app/transactions" element={<ProtectedRoute><AppShell surface="backoffice"><Transactions /></AppShell></ProtectedRoute>} />
      <Route path="/app/reconciliation" element={<ProtectedRoute><AppShell surface="backoffice"><Reconciliation /></AppShell></ProtectedRoute>} />
      <Route path="/app/integrations" element={<ProtectedRoute><AppShell surface="backoffice"><Integrations /></AppShell></ProtectedRoute>} />
      <Route path="/app/api-keys" element={<ProtectedRoute><AppShell surface="backoffice"><ApiKeys /></AppShell></ProtectedRoute>} />
      <Route path="/app/webhooks" element={<ProtectedRoute><AppShell surface="backoffice"><Webhooks /></AppShell></ProtectedRoute>} />
      <Route path="/app/alerts" element={<ProtectedRoute><AppShell surface="backoffice"><Alerts /></AppShell></ProtectedRoute>} />
      <Route path="/app/reports" element={<ProtectedRoute><AppShell surface="backoffice"><Reports /></AppShell></ProtectedRoute>} />
      <Route path="/app/users" element={<ProtectedRoute><AppShell surface="backoffice"><UsersAdmin /></AppShell></ProtectedRoute>} />
      <Route path="/app/audit" element={<ProtectedRoute><AppShell surface="backoffice"><AuditLog /></AppShell></ProtectedRoute>} />

      {/* Client Portal */}
      <Route path="/portal" element={<ProtectedRoute><AppShell surface="portal"><PortalOverview /></AppShell></ProtectedRoute>} />
      <Route path="/portal/organization" element={<ProtectedRoute><AppShell surface="portal"><PortalOrganization /></AppShell></ProtectedRoute>} />
      <Route path="/portal/users" element={<ProtectedRoute><AppShell surface="portal"><PortalUsers /></AppShell></ProtectedRoute>} />
      <Route path="/portal/balances" element={<ProtectedRoute><AppShell surface="portal"><PortalBalances /></AppShell></ProtectedRoute>} />
      <Route path="/portal/transactions" element={<ProtectedRoute><AppShell surface="portal"><PortalTransactions /></AppShell></ProtectedRoute>} />
      <Route path="/portal/yield" element={<ProtectedRoute><AppShell surface="portal"><YieldPage /></AppShell></ProtectedRoute>} />
      <Route path="/portal/end-customers" element={<ProtectedRoute><AppShell surface="portal"><EndCustomers /></AppShell></ProtectedRoute>} />
      <Route path="/portal/integrations" element={<ProtectedRoute><AppShell surface="portal"><PortalIntegrations /></AppShell></ProtectedRoute>} />
      <Route path="/portal/api-keys" element={<ProtectedRoute><AppShell surface="portal"><PortalApiKeys /></AppShell></ProtectedRoute>} />
      <Route path="/portal/webhooks" element={<ProtectedRoute><AppShell surface="portal"><PortalWebhooks /></AppShell></ProtectedRoute>} />
      <Route path="/portal/reports" element={<ProtectedRoute><AppShell surface="portal"><PortalReports /></AppShell></ProtectedRoute>} />
      <Route path="/portal/compliance" element={<ProtectedRoute><AppShell surface="portal"><PortalCompliance /></AppShell></ProtectedRoute>} />
      <Route path="/portal/settings" element={<ProtectedRoute><AppShell surface="portal"><PortalSettings /></AppShell></ProtectedRoute>} />

      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <InnerRouter />
        <Toaster position="top-right" toastOptions={{ style: { background: "var(--surface)", border: "1px solid var(--border)", color: "var(--fg)", fontFamily: "IBM Plex Sans" } }} />
      </BrowserRouter>
    </AppProvider>
  );
}

export default App;
