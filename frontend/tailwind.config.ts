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
        ink: "#07111f",
        panel: "#0d1626",
        soft: "#162338",
        line: "rgba(148, 163, 184, 0.18)",
        accent: "#7dd3fc",
        mint: "#a7f3d0",
      },
      boxShadow: {
        glow: "0 20px 80px rgba(14, 165, 233, 0.12)",
      },
    },
  },
  plugins: [],
};

export default config;
