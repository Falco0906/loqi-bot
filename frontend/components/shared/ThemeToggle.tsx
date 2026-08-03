"use client";

import { useTheme, type Theme } from "../../hooks/useTheme";

const options: { value: Theme; label: string; icon: string }[] = [
  { value: "light", label: "Light", icon: "light_mode" },
  { value: "dark", label: "Dark", icon: "dark_mode" },
];

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="flex rounded-full border border-outline-variant/10 bg-surface-container p-1 gap-1">
      {options.map((opt) => {
        const active = theme === opt.value;
        return (
          <button
            key={opt.value}
            onClick={() => setTheme(opt.value)}
            className={`flex items-center gap-1.5 rounded-full px-4 py-1.5 font-label-xs text-label-xs transition-colors ${
              active ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-on-surface"
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">{opt.icon}</span>
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
