"use client";

import { useCallback, useEffect, useState } from "react";

const THEME_KEY = "loqi_theme";
const THEME_CHANGE_EVENT = "loqi:theme-change";

export type Theme = "dark" | "light";

export function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

function getStoredTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    const syncTheme = () => setTheme(getStoredTheme());
    syncTheme();
    window.addEventListener(THEME_CHANGE_EVENT, syncTheme);
    window.addEventListener("storage", syncTheme);
    return () => {
      window.removeEventListener(THEME_CHANGE_EVENT, syncTheme);
      window.removeEventListener("storage", syncTheme);
    };
  }, []);

  const setThemePref = useCallback((next: Theme) => {
    setTheme(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {}
    applyTheme(next);
    window.dispatchEvent(new Event(THEME_CHANGE_EVENT));
  }, []);

  return { theme, setTheme: setThemePref };
}
