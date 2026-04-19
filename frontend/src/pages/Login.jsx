import { useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useApp } from "@/contexts/AppContext";
import Logo from "@/components/Logo";
import { ArrowRight, ArrowUpRight, Sun, Moon } from "@phosphor-icons/react";

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
export default function Login() {
  const { user, theme, toggleTheme } = useApp();
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
    <div className="min-h-screen wave-bg flex flex-col relative overflow-hidden" data-testid="login-page"
         style={{ background: "var(--bg)" }}>
      {/* Header */}
      <header className="relative z-10 px-8 lg:px-16 py-6 flex items-center justify-between">
        <Logo size={34} />
        <nav className="hidden md:flex items-center gap-8 text-sm text-[var(--fg-muted)]">
          <a href="https://www.prosper.foundation" target="_blank" rel="noreferrer" className="hover:text-[var(--fg)] transition-colors">Whitepaper</a>
          <a href="https://www.prosper.foundation" target="_blank" rel="noreferrer" className="hover:text-[var(--fg)] transition-colors">Company</a>
          <a href="https://www.prosper.foundation" target="_blank" rel="noreferrer" className="hover:text-[var(--fg)] transition-colors">Community</a>
          <a href="https://www.prosper.foundation" target="_blank" rel="noreferrer" className="hover:text-[var(--fg)] transition-colors">The Protocol</a>
        </nav>
        <div className="flex items-center gap-3">
          <button
            onClick={toggleTheme}
            className="w-9 h-9 rounded-full border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface-hover)] flex items-center justify-center transition-colors"
            data-testid="theme-toggle"
            aria-label="Toggle theme"
          >
            {theme === "dark" ? <Sun size={16} weight="bold" /> : <Moon size={16} weight="bold" />}
          </button>
          <button onClick={handleLogin} data-testid="header-launch-button"
                  className="btn-pill btn-primary">
            Launch App
            <span className="arrow-box"><ArrowUpRight size={12} weight="bold" /></span>
          </button>
        </div>
      </header>

      {/* Hero */}
      <main className="relative z-10 flex-1 flex flex-col items-center justify-center text-center px-6 py-16">
        <div className="max-w-4xl">
          <div className="text-xs font-medium tracking-[0.25em] uppercase text-[var(--primary)] mb-8">
            Leading Platform for Real World Assets Tokenized Solutions
          </div>
          <h1 className="font-display font-black text-5xl md:text-6xl lg:text-7xl leading-[0.98] tracking-tight text-[var(--fg)] mb-8">
            Borderless on-chain<br/>
            financial services<br/>
            <span className="text-[var(--fg-muted)]">with social impact.</span>
          </h1>
          <p className="text-[var(--fg-muted)] max-w-xl mx-auto text-base leading-relaxed mb-10">
            The simplest platform for On-Chain Financial Services. Frictionless access to capital
            and investment opportunities with social impact.
          </p>

          {error && (
            <div className="mb-6 mx-auto max-w-md p-3 border border-[var(--danger)]/30 rounded-lg text-sm"
                 style={{ background: "rgba(229,62,62,0.06)", color: "var(--danger)" }}
                 data-testid="login-error">
              Authentication failed. Please try again.
            </div>
          )}

          <div className="flex items-center justify-center gap-3 flex-wrap">
            <button onClick={handleLogin} data-testid="google-login-button"
                    className="btn-pill btn-primary group text-base px-7 py-3.5">
              <svg width="18" height="18" viewBox="0 0 24 24">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#fff"/>
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#fff" opacity=".85"/>
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#fff" opacity=".7"/>
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#fff" opacity=".9"/>
              </svg>
              Sign in with Google
              <ArrowRight size={16} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
            </button>
            <a href="https://www.prosper.foundation" target="_blank" rel="noreferrer"
               className="btn-pill btn-outline text-base px-7 py-3.5" data-testid="contact-link">
              Contact us
              <ArrowUpRight size={14} weight="bold" />
            </a>
          </div>

          <div className="mt-8 text-xs font-mono uppercase tracking-[0.2em] text-[var(--fg-subtle)]">
            Encrypted session · 7 day expiry · CNV Regulated
          </div>
        </div>
      </main>

      {/* Partners strip */}
      <div className="relative z-10 border-t border-[var(--border)] bg-[var(--surface)] py-8 px-6">
        <div className="max-w-5xl mx-auto flex items-center justify-center gap-10 flex-wrap">
          <span className="font-display font-bold text-lg text-[var(--fg)]">Working With:</span>
          <PartnerLogo src="https://www.prosper.foundation/images/stellar.png" alt="Stellar" />
          <PartnerLogo src="https://www.prosper.foundation/images/circle.jpg" alt="Circle" />
          <PartnerLogo src="https://www.prosper.foundation/images/gbbc.jpg" alt="GBBC" />
          <PartnerLogo src="https://www.prosper.foundation/images/aws.jpg" alt="AWS" />
        </div>
      </div>
    </div>
  );
}

const PartnerLogo = ({ src, alt }) => (
  <img src={src} alt={alt} className="h-7 md:h-8 opacity-80 grayscale hover:grayscale-0 hover:opacity-100 transition-all object-contain" />
);
