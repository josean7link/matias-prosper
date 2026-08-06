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
        // Prosper official palette
        primary: {
          DEFAULT: "#2563FF",
          50:  "#F2F6FF",
          100: "#E0EAFF",
          200: "#C2D6FF",
          300: "#8DB4FF",
          400: "#5B8DFF",
          500: "#2563FF",
          600: "#1E4FDB",
          700: "#173EAD",
          800: "#102C7C",
          900: "#0B0F19",
        },
        dark:    { DEFAULT: "#0B0F19" },
        light:   { DEFAULT: "#F2F6FF" },
        grey:    { DEFAULT: "#6B7280" },
        success: { DEFAULT: "#22C55E" },
        warning: { DEFAULT: "#E07B00" },
        danger:  { DEFAULT: "#DC2626" },

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
        card: "0 2px 8px rgba(11,15,25,0.06)",
        "card-hover": "0 4px 16px rgba(11,15,25,0.10)",
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
