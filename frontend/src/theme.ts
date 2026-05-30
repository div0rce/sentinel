import { useEffect, useState } from "react";

/**
 * Dark/light theme state for the design system.
 *
 * The token layer in `styles.css` is theme-agnostic: every surface/text role is a
 * CSS variable that is remapped under `[data-theme="light"]`. Switching theme is
 * therefore a single attribute flip on `<html>` — no component branches on theme.
 *
 * Default is dark. The attribute is also set by a pre-paint inline script in
 * `index.html` so the first paint already matches the persisted choice (no flash);
 * this hook reads that attribute first so its initial state never disagrees with it.
 */

export type Theme = "dark" | "light";

const STORAGE_KEY = "sentinel-theme";

function readInitialTheme(): Theme {
  const attr = document.documentElement.dataset.theme;
  if (attr === "light" || attr === "dark") {
    return attr;
  }
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") {
      return stored;
    }
  } catch {
    /* localStorage may be unavailable (private mode); fall through to the default */
  }
  return "dark";
}

export function useTheme(): { theme: Theme; toggleTheme: () => void } {
  const [theme, setTheme] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* persistence failed; the attribute still applies for this session */
    }
  }, [theme]);

  return {
    theme,
    toggleTheme: () => setTheme((current) => (current === "light" ? "dark" : "light")),
  };
}
