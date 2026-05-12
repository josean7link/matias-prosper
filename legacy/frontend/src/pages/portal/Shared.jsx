/* Lightweight wrappers that reuse the backoffice tables but in the portal navigation context.
   These pages are identical visually to the backoffice ones, but labelled for partners. */
import ApiKeysPage from "@/pages/backoffice/ApiKeys";
import WebhooksPage from "@/pages/backoffice/Webhooks";
import IntegrationsPage from "@/pages/backoffice/Integrations";
import ReportsPage from "@/pages/backoffice/Reports";
import CompliancePage from "@/pages/backoffice/Compliance";
import UsersAdminPage from "@/pages/backoffice/UsersAdmin";

export function PortalApiKeys() { return <ApiKeysPage />; }
export function PortalWebhooks() { return <WebhooksPage />; }
export function PortalIntegrations() { return <IntegrationsPage />; }
export function PortalReports() { return <ReportsPage />; }
export function PortalCompliance() { return <CompliancePage />; }
export function PortalUsers() { return <UsersAdminPage />; }
