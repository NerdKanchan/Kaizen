// One control, two themes. The choice is remembered per browser; until a choice is made the tool
// follows the operating system, including live changes. The switch itself cross-fades every colour
// for 200ms rather than snapping, unless the reviewer prefers reduced motion.
import { Moon, Sun } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { applyTheme, currentTheme, readChoice, resolveTheme, toggleTheme, type Theme, type ThemeStorage } from "../lib/theme";
import { Button } from "./ui";

const doc = { querySelector: (s: string) => document.querySelector<HTMLMetaElement>(s) };

function storage(): ThemeStorage {
  try {
    return window.localStorage;
  } catch {
    return { getItem: () => null, setItem: () => undefined };
  }
}

function crossfade() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const root = document.documentElement;
  root.classList.add("theme-switch");
  window.setTimeout(() => root.classList.remove("theme-switch"), 240);
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => currentTheme(document.documentElement));

  // Keep every theme control in sync, including the profile page and top bar.
  useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => setTheme(currentTheme(root)));
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  // Follow the operating system while no explicit choice is stored.
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (readChoice(storage()) !== "system") return;
      const t = resolveTheme("system", mq.matches);
      applyTheme(t, document.documentElement, doc);
      setTheme(t);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    crossfade();
    setTheme(toggleTheme(currentTheme(document.documentElement), storage(), document.documentElement, doc));
  }, []);

  return [theme, toggle];
}

export function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, toggle] = useTheme();
  const dark = theme === "dark";
  return (
    <Button
      variant="ghost"
      size="sm"
      iconOnly
      className={className}
      onClick={toggle}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
      icon={
        <span key={theme} className="enter-pop grid place-items-center" aria-hidden>
          {dark ? <Sun size={16} /> : <Moon size={16} />}
        </span>
      }
    />
  );
}
