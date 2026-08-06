"use client";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Env = "sandbox" | "production";

interface EnvContextValue {
  env: Env;
  setEnv: (env: Env) => void;
}

const EnvContext = createContext<EnvContextValue | null>(null);

const COOKIE_KEY = "prosper_env";

function readEnvCookie(): Env {
  if (typeof document === "undefined") return "production";
  const m = document.cookie.match(/(?:^|; )prosper_env=([^;]+)/);
  return m && m[1] === "sandbox" ? "sandbox" : "production";
}

function writeEnvCookie(env: Env) {
  document.cookie = `${COOKIE_KEY}=${env}; path=/; max-age=${365 * 24 * 3600}; samesite=lax`;
}

export function EnvProvider({
  initial,
  children,
}: {
  initial?: Env;
  children: ReactNode;
}) {
  const [env, setEnvState] = useState<Env>(initial ?? "production");

  // Reconcile with the cookie on mount (client-only) so the first interactive
  // render matches the persisted user preference.
  useEffect(() => {
    const c = readEnvCookie();
    if (c !== env) setEnvState(c);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setEnv = (next: Env) => {
    writeEnvCookie(next);
    setEnvState(next);
  };

  return (
    <EnvContext.Provider value={{ env, setEnv }}>{children}</EnvContext.Provider>
  );
}

export function useEnv(): EnvContextValue {
  const ctx = useContext(EnvContext);
  if (!ctx) throw new Error("useEnv must be used inside <EnvProvider>");
  return ctx;
}

/**
 * Safe variant — returns null when no <EnvProvider> ancestor exists.
 * Useful in shared components (eg the layout shell) that render in both
 * admin (with EnvProvider) and client (without) surfaces.
 */
export function useEnvOptional(): EnvContextValue | null {
  return useContext(EnvContext);
}

/** Server-side helper for reading the env from request cookies in RSC. */
export function envFromCookieString(cookieHeader: string | undefined): Env {
  if (!cookieHeader) return "production";
  const m = cookieHeader.match(/(?:^|; )prosper_env=([^;]+)/);
  return m && m[1] === "sandbox" ? "sandbox" : "production";
}
