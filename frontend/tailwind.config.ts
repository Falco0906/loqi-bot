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
        obsidian: "rgb(var(--obsidian) / <alpha-value>)",
        charcoal: "rgb(var(--charcoal) / <alpha-value>)",
        background: "rgb(var(--background) / <alpha-value>)",
        "surface-lowest": "rgb(var(--surface-lowest) / <alpha-value>)",
        "surface-low": "rgb(var(--surface-low) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        "surface-high": "rgb(var(--surface-high) / <alpha-value>)",
        "surface-highest": "rgb(var(--surface-highest) / <alpha-value>)",
        "surface-bright": "rgb(var(--surface-bright) / <alpha-value>)",
        "surface-variant": "rgb(var(--surface-variant) / <alpha-value>)",
        "surface-dim": "rgb(var(--surface-dim) / <alpha-value>)",
        "surface-container": "rgb(var(--surface-container) / <alpha-value>)",
        "surface-container-low": "rgb(var(--surface-container-low) / <alpha-value>)",
        "surface-container-high": "rgb(var(--surface-container-high) / <alpha-value>)",
        "on-surface": "rgb(var(--on-surface) / <alpha-value>)",
        "on-surface-variant": "rgb(var(--on-surface-variant) / <alpha-value>)",
        "on-background": "rgb(var(--on-background) / <alpha-value>)",
        outline: "rgb(var(--outline) / <alpha-value>)",
        "outline-variant": "rgb(var(--outline-variant) / <alpha-value>)",
        primary: "rgb(var(--primary) / <alpha-value>)",
        "primary-container": "rgb(var(--primary-container) / <alpha-value>)",
        "on-primary": "rgb(var(--on-primary) / <alpha-value>)",
        "on-primary-container": "rgb(var(--on-primary-container) / <alpha-value>)",
        secondary: "rgb(var(--secondary) / <alpha-value>)",
        "secondary-container": "rgb(var(--secondary-container) / <alpha-value>)",
        "on-secondary-container": "rgb(var(--on-secondary-container) / <alpha-value>)",
        tertiary: "rgb(var(--tertiary) / <alpha-value>)",
        error: "rgb(var(--error) / <alpha-value>)",
        "error-container": "rgb(var(--error-container) / <alpha-value>)",
        "on-error": "rgb(var(--on-error) / <alpha-value>)",
        "on-error-container": "rgb(var(--on-error-container) / <alpha-value>)",
        success: "rgb(var(--success) / <alpha-value>)",
        warning: "rgb(var(--warning) / <alpha-value>)",
      },
      fontFamily: {
        heading: ["Geist", "system-ui", "sans-serif"],
        body: ["Inter", "system-ui", "sans-serif"],
        serif: ["Libre Caslon Text", "Georgia", "serif"],
      },
      fontSize: {
        "display-xl": ["48px", { lineHeight: "1.1", letterSpacing: "-0.02em", fontWeight: "400" }],
        "headline-xl": ["40px", { lineHeight: "1.1", letterSpacing: "-0.03em", fontWeight: "400" }],
        "headline-lg": ["32px", { lineHeight: "1.3", letterSpacing: "-0.02em", fontWeight: "400" }],
        "headline-sm": ["20px", { lineHeight: "1.3", letterSpacing: "-0.015em", fontWeight: "500" }],
        "headline-md": ["24px", { lineHeight: "1.4", letterSpacing: "-0.02em", fontWeight: "400" }],
        "body-sm": ["13px", { lineHeight: "1.5", fontWeight: "400" }],
        "body-md": ["16px", { lineHeight: "1.5", fontWeight: "400" }],
        "body-lg": ["18px", { lineHeight: "1.6", fontWeight: "400" }],
        "label-sm": ["13px", { lineHeight: "1.2", letterSpacing: "0.02em", fontWeight: "500" }],
        "label-md": ["12px", { lineHeight: "1.2", letterSpacing: "0.05em", fontWeight: "500" }],
        "label-xs": ["11px", { lineHeight: "1.2", letterSpacing: "0.05em", fontWeight: "600" }],
        "mono-sm": ["12px", { lineHeight: "1.4" }],
      },
      borderRadius: {
        container: "12px",
        button: "8px",
        "ai-panel": "16px",
      },
      boxShadow: {
        "ai-glow": "var(--shadow-ai-glow)",
        "glass": "var(--shadow-glass)",
        "card": "var(--shadow-card)",
        "card-hover": "var(--shadow-card-hover)",
        "card-active": "var(--shadow-card-active)",
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
