import { useApp } from "@/contexts/AppContext";
import { PageHeader, EnvPill } from "@/components/common";

export default function PortalSettings() {
  const { user, env } = useApp();
  return (
    <div data-testid="portal-settings">
      <PageHeader title="Settings" subtitle="Personal & organization preferences" />
      <div className="prosper-card p-6 max-w-xl">
        <div className="text-[10px] uppercase tracking-wider text-[#888] mb-2">Signed in as</div>
        <div className="flex items-center gap-3 mb-6">
          {user?.picture && <img src={user.picture} alt="" className="w-12 h-12 rounded-full border border-[#222]" />}
          <div>
            <div className="font-semibold">{user?.name}</div>
            <div className="font-mono text-xs text-[#888]">{user?.email}</div>
          </div>
        </div>
        <div className="space-y-2 text-sm">
          <Row label="Role" value={<span className="uppercase font-mono text-xs">{user?.platform_role}</span>} />
          <Row label="Environment" value={<EnvPill env={env} />} />
          <Row label="Internal staff" value={user?.is_internal ? "yes" : "no"} />
          <Row label="MFA" value={user?.mfa_enabled ? "enabled" : "disabled"} />
        </div>
      </div>
    </div>
  );
}
const Row = ({ label, value }) => (
  <div className="flex justify-between py-2 border-b border-[#1a1a1a] last:border-0">
    <span className="text-[#888] text-xs uppercase tracking-wider">{label}</span>
    <span>{value}</span>
  </div>
);
