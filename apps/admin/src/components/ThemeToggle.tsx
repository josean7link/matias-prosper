"use client";
import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

function setThemeCookie(theme: "light" | "dark") {
  // 1 year, root path, lax
  document.cookie = `prosper_theme=${theme}; path=/; max-age=${365 * 24 * 3600}; samesite=lax`;
}

function currentTheme(): "light" | "dark" {
  if (typeof document === "undefined") return "light";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function ThemeToggleStandalone() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  useEffect(() => { setTheme(currentTheme()); }, []);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    setThemeCookie(next);
    setTheme(next);
  };

  return (
    <button
      onClick={toggle}
      className="w-9 h-9 rounded border border-border bg-surface hover:bg-surface-hover flex items-center justify-center transition-colors"
      aria-label="Toggle theme"
      data-testid="theme-toggle"
    >
      {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}
