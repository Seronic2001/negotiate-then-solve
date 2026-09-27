import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type Theme = "light" | "dark";
const ThemeContext = createContext<{ theme: Theme; toggle: () => void }>({ theme: "light", toggle: () => {} });

function initial(): Theme {
  try {
    const saved = localStorage.getItem("nts.theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* ignore */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function apply(theme: Theme): Theme {
  // Set before React renders, so components reading colours (charts) see the new theme.
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#161513" : "#f5f3ee");
  return theme;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => apply(initial()));
  useEffect(() => {
    try {
      localStorage.setItem("nts.theme", theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  return (
    <ThemeContext.Provider value={{ theme, toggle: () => setTheme(apply(theme === "dark" ? "light" : "dark")) }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);

const TOKENS = ["bg", "panel", "panel-2", "line", "ink", "ink-2", "ink-3", "brand", "ok", "warn", "bad", "info"] as const;
export type Tokens = Record<(typeof TOKENS)[number], string>;

/** The theme's colours as values, for SVG charts that cannot use CSS variables. */
export function useTokens(): Tokens {
  const { theme } = useTheme();
  return useMemo(() => {
    const css = getComputedStyle(document.documentElement);
    return Object.fromEntries(TOKENS.map((t) => [t, css.getPropertyValue(`--${t}`).trim()])) as Tokens;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);
}
