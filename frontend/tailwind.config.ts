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
        "headline-sm": ["20px", { lineHeight: "1.3", letterSpacing: "-0.015em", fontWeight: "600" }],
        "headline-md": ["24px", { lineHeight: "1.3", letterSpacing: "-0.02em", fontWeight: "500" }],
        "body-sm": ["13px", { lineHeight: "1.5", fontWeight: "400" }],
        "body-md": ["14px", { lineHeight: "1.5", fontWeight: "400" }],
        "body-lg": ["16px", { lineHeight: "1.6", fontWeight: "400" }],
        "label-sm": ["12px", { lineHeight: "1.4", fontWeight: "500", letterSpacing: "0.02em" }],
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
        "card": "0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)",
        "card-hover": "0 4px 12px rgba(0,0,0,0.4), 0 2px 4px rgba(0,0,0,0.3)",
        "card-active": "0 1px 2px rgba(0,0,0,0.3)",
      },
      keyframes: {
        "ping-slow": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.5" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(12px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.96)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        "skeleton-pulse": {
          "0%, 100%": { opacity: "0.4" },
          "50%": { opacity: "0.2" },
        },
      },
      animation: {
        "ping-slow": "ping-slow 2s cubic-bezier(0, 0, 0.2, 1) infinite",
        "fade-in": "fade-in 0.3s ease-out",
        "slide-up": "slide-up 0.35s cubic-bezier(0.16, 1, 0.3, 1)",
        "scale-in": "scale-in 0.25s cubic-bezier(0.16, 1, 0.3, 1)",
        "skeleton-pulse": "skeleton-pulse 1.8s ease-in-out infinite",
      },
      scale: {
        "102": "1.02",
      },
    },
  },
  plugins: [],
};

export default config;
