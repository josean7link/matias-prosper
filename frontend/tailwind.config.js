/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    "../packages/ui/src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Prosper palette (from fase_00_bootstrap.md)
        primary: {
          DEFAULT: "#2B6BFF",
          50:  "#EBF1FB",
          100: "#D6E2F7",
          200: "#A8C1ED",
          300: "#7A9FE2",
          400: "#5285D6",
          500: "#2B6BFF",
          600: "#1F55D6",
          700: "#1841A6",
          800: "#102D74",
          900: "#0A1F44",
        },
        dark: { DEFAULT: "#0A1F44" },
        light: { DEFAULT: "#EBF1FB" },
        grey: { DEFAULT: "#5B6478" },
        success: { DEFAULT: "#0FA958" },
        warning: { DEFAULT: "#E07B00" },
        danger: { DEFAULT: "#DC2626" },

        // Surfaces (light + dark mode)
        bg: "rgb(var(--bg) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        "surface-hover": "rgb(var(--surface-hover) / <alpha-value>)",
        border: "rgb(var(--border) / <alpha-value>)",
        fg: "rgb(var(--fg) / <alpha-value>)",
        "fg-muted": "rgb(var(--fg-muted) / <alpha-value>)",
        "fg-subtle": "rgb(var(--fg-subtle) / <alpha-value>)",
      },
      fontFamily: {
        sans:    ["var(--font-plex-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-chivo)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono:    ["var(--font-plex-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: {
        DEFAULT: "8px",
        lg: "12px",
      },
      boxShadow: {
        card: "0 2px 8px rgba(10,31,68,0.06)",
        "card-hover": "0 4px 16px rgba(10,31,68,0.10)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in .25s ease-out",
        "slide-up": "slide-up .3s ease-out",
      },
    },
  },
  plugins: [],
};
