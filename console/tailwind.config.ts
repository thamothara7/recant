import type { Config } from "tailwindcss";

// Tokens are the single source of truth in src/index.css (CSS variables).
// They are mirrored here only so utilities like `bg-ink` / `text-uv` exist.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "var(--ink)",
        panel: "var(--panel)",
        "panel-2": "var(--panel-2)",
        bond: "var(--bond)",
        "bond-dim": "var(--bond-dim)",
        hairline: "var(--hairline)",
        "hairline-strong": "var(--hairline-strong)",
        uv: "var(--uv)",
        "uv-dim": "var(--uv-dim)",
        attested: "var(--attested)",
        suspect: "var(--suspect)",
        quarantined: "var(--quarantined)",
        retracted: "var(--retracted)",
      },
      fontFamily: {
        display: ["'Source Serif 4'", "Georgia", "serif"],
        ui: ["'IBM Plex Sans'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
      borderRadius: {
        panel: "6px",
        tag: "2px",
      },
      boxShadow: {
        drawer: "-24px 0 48px -24px rgba(0,0,0,0.6)",
        lift: "0 1px 0 rgba(255,255,255,0.03), 0 8px 24px -16px rgba(0,0,0,0.7)",
      },
    },
  },
  plugins: [],
} satisfies Config;
