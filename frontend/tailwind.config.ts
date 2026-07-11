import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        obsidian: "#09090B",
        charcoal: "#0B0B0F",
        "surface-lowest": "#0e0d16",
        "surface-low": "#1b1b24",
        surface: "#1f1f28",
        "surface-high": "#2a2933",
        "surface-highest": "#35343e",
        "surface-bright": "#393842",
        "on-surface": "#e4e1ee",
        "on-surface-variant": "#c7c4d8",
        outline: "#918fa1",
        "outline-variant": "#464555",
        primary: "#c4c0ff",
        "primary-container": "#8781ff",
        "on-primary": "#2000a4",
        secondary: "#4edea3",
        tertiary: "#ffb95f",
        error: "#ffb4ab",
        "error-container": "#93000a",
      },
      fontFamily: {
        heading: ["Geist", "system-ui", "sans-serif"],
        body: ["Inter", "system-ui", "sans-serif"],
      },
      fontSize: {
        "headline-xl": ["40px", { lineHeight: "1.1", letterSpacing: "-0.04em", fontWeight: "600" }],
        "headline-lg": ["32px", { lineHeight: "1.2", letterSpacing: "-0.03em", fontWeight: "600" }],
        "headline-md": ["24px", { lineHeight: "1.3", letterSpacing: "-0.02em", fontWeight: "500" }],
        "body-lg": ["16px", { lineHeight: "1.6", fontWeight: "400" }],
        "body-md": ["14px", { lineHeight: "1.5", fontWeight: "400" }],
        "label-md": ["12px", { lineHeight: "1", letterSpacing: "0.05em", fontWeight: "500" }],
        "mono-sm": ["12px", { lineHeight: "1.4" }],
      },
      borderRadius: {
        container: "12px",
        button: "8px",
        "ai-panel": "16px",
      },
      boxShadow: {
        "ai-glow": "0 0 24px rgba(135, 129, 255, 0.15)",
        "glass": "0 8px 32px rgba(0, 0, 0, 0.4)",
      },
      keyframes: {
        "ping-slow": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.5" },
        },
      },
      animation: {
        "ping-slow": "ping-slow 2s cubic-bezier(0, 0, 0.2, 1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
