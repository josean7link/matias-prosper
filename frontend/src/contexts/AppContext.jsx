import { createContext, useContext, useEffect, useState, useCallback } from "react";
import api from "@/lib/api";

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [env, setEnv] = useState(localStorage.getItem("prosper_env") || "production");

  const checkAuth = useCallback(async () => {
    // If returning from OAuth callback, skip – AuthCallback will handle it
    if (typeof window !== "undefined" && window.location.hash?.includes("session_id=")) {
      setLoading(false);
      return;
    }
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const switchEnv = (next) => {
    setEnv(next);
    localStorage.setItem("prosper_env", next);
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch {}
    localStorage.removeItem("prosper_session_token");
    setUser(null);
    window.location.href = "/login";
  };

  return (
    <AppContext.Provider value={{ user, setUser, loading, env, switchEnv, logout, checkAuth }}>
      {children}
    </AppContext.Provider>
  );
}

export const useApp = () => {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be inside AppProvider");
  return ctx;
};
