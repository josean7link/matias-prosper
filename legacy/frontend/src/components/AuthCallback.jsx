import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";

export default function AuthCallback() {
  const navigate = useNavigate();
  const { setUser } = useApp();
  const hasProcessed = useRef(false);

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const run = async () => {
      const hash = window.location.hash || "";
      const match = hash.match(/session_id=([^&]+)/);
      if (!match) {
        navigate("/login");
        return;
      }
      const sessionId = match[1];
      try {
        const { data } = await api.post("/auth/session", { session_id: sessionId });
        if (data.session_token) {
          localStorage.setItem("prosper_session_token", data.session_token);
        }
        setUser(data.user);
        // Clear hash
        window.history.replaceState(null, "", window.location.pathname);
        navigate("/app", { replace: true, state: { user: data.user } });
      } catch (e) {
        console.error(e);
        navigate("/login?error=session");
      }
    };
    run();
  }, [navigate, setUser]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)] text-[var(--fg)]" data-testid="auth-callback">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-[#0066FF] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <div className="font-mono text-sm uppercase tracking-widest text-[var(--fg-muted)]">Authenticating</div>
      </div>
    </div>
  );
}
