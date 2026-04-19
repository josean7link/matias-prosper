import { useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useApp } from "@/contexts/AppContext";
import { ArrowRight, ShieldCheck, Lightning } from "@phosphor-icons/react";

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
export default function Login() {
  const { user } = useApp();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (user) navigate("/app", { replace: true });
  }, [user, navigate]);

  const handleLogin = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + "/app";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  const urlParams = new URLSearchParams(location.search);
  const error = urlParams.get("error");

  return (
    <div className="min-h-screen bg-[#050505] text-white flex relative noise" data-testid="login-page">
      {/* Left: brand/marketing */}
      <div className="hidden lg:flex flex-1 grid-bg relative overflow-hidden">
        <div className="relative z-10 flex flex-col justify-between p-12 w-full">
          <div className="flex items-center gap-3 font-display font-black text-2xl">
            <div className="w-10 h-10 rounded-sm bg-[#0066FF] flex items-center justify-center text-white font-black text-xl">P</div>
            <span>PROSPER</span>
          </div>
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.3em] text-[#0066FF] mb-6">Control Room · v0.1</div>
            <h1 className="font-display font-black text-5xl xl:text-6xl leading-[0.95] tracking-tight max-w-xl">
              Operate tokenized yield<br/>
              <span className="text-[#888]">at institutional scale.</span>
            </h1>
            <p className="text-[#888] mt-6 max-w-md text-sm leading-relaxed">
              Prosper is a regulated tokenized yield infrastructure built on Stellar.
              This platform powers internal operations, compliance, treasury, and the
              partner API ecosystem.
            </p>
            <div className="grid grid-cols-3 gap-0 tight-grid border border-[#1a1a1a] mt-8 max-w-md">
              <div className="p-4 bg-[#0a0a0a]">
                <div className="text-[10px] uppercase tracking-wider text-[#888] mb-1">AUM</div>
                <div className="font-mono text-xl">$42.3M</div>
              </div>
              <div className="p-4 bg-[#0a0a0a]">
                <div className="text-[10px] uppercase tracking-wider text-[#888] mb-1">Investors</div>
                <div className="font-mono text-xl">1,064</div>
              </div>
              <div className="p-4 bg-[#0a0a0a]">
                <div className="text-[10px] uppercase tracking-wider text-[#888] mb-1">Products</div>
                <div className="font-mono text-xl">5</div>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-6 text-[11px] font-mono uppercase tracking-wider text-[#555]">
            <span className="flex items-center gap-1.5"><ShieldCheck size={12} /> CNV Regulated</span>
            <span className="flex items-center gap-1.5"><Lightning size={12} /> Stellar Mainnet</span>
            <span>Moody's Local AA</span>
          </div>
        </div>
      </div>

      {/* Right: login card */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-sm">
          <div className="lg:hidden mb-8 flex items-center gap-3 font-display font-black text-2xl">
            <div className="w-10 h-10 rounded-sm bg-[#0066FF] flex items-center justify-center text-white font-black text-xl">P</div>
            <span>PROSPER</span>
          </div>
          <div className="font-mono text-[10px] uppercase tracking-[0.3em] text-[#888] mb-3">Secure Access</div>
          <h2 className="font-display font-bold text-3xl mb-2">Sign in</h2>
          <p className="text-sm text-[#888] mb-8">
            Access the Prosper control room with your Google identity. Access is restricted
            to approved operators and partner admins.
          </p>

          {error && (
            <div className="mb-4 p-3 border border-[#FF3D00]/30 bg-[#FF3D00]/5 text-[#FF3D00] text-sm rounded-sm" data-testid="login-error">
              Authentication failed. Please try again.
            </div>
          )}

          <button
            onClick={handleLogin}
            data-testid="google-login-button"
            className="w-full bg-white text-black hover:bg-[#f5f5f5] font-medium py-3 px-4 rounded-sm flex items-center justify-center gap-3 transition-colors group"
          >
            <svg width="18" height="18" viewBox="0 0 24 24">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
            </svg>
            Continue with Google
            <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" />
          </button>

          <div className="mt-10 text-[11px] font-mono uppercase tracking-wider text-[#555] flex items-center gap-2">
            <span>Encrypted session · 7 day expiry</span>
          </div>
        </div>
      </div>
    </div>
  );
}
