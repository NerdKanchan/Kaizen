// Light and dark are two compositions of the same tokens (docs/design/DESIGN.md, "Dark theme"). This
// module owns the choice: what is stored, how the system preference is honoured, and how the root is
// stamped so the CSS variables switch. Collaborators are passed in so the rules are testable without a
// browser; index.html runs the same rule inline before first paint so there is no flash of the wrong theme.

export type Theme = "light" | "dark";
export type ThemeChoice = Theme | "system";

export const THEME_KEY = "kaizen.theme";

/** Browser chrome colour (meta theme-color): the navigation rail's colour in each theme. */
export const THEME_COLOR: Record<Theme, string> = { light: "#030620", dark: "#02040E" };

export interface ThemeStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}
export interface ThemeRoot {
  dataset: Record<string, string | undefined>;
  style: { colorScheme: string };
}
export interface ThemeDocument {
  querySelector(selector: string): { content: string } | null;
}

/** The stored choice, or "system" when nothing usable is stored or storage is unavailable. */
export function readChoice(storage: ThemeStorage): ThemeChoice {
  try {
    const v = storage.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function resolveTheme(choice: ThemeChoice, systemDark: boolean): Theme {
  if (choice === "system") return systemDark ? "dark" : "light";
  return choice;
}

/** Stamp the theme on the root (the CSS variables key off data-theme) and on the browser chrome. */
export function applyTheme(theme: Theme, root: ThemeRoot, doc?: ThemeDocument): void {
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  const meta = doc?.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = THEME_COLOR[theme];
}

/** Switch to the other theme, remember it, and apply it. Storage failures never block the switch. */
export function toggleTheme(current: Theme, storage: ThemeStorage, root: ThemeRoot, doc?: ThemeDocument): Theme {
  const next: Theme = current === "dark" ? "light" : "dark";
  try {
    storage.setItem(THEME_KEY, next);
  } catch {
    /* private mode or blocked storage: the switch still happens for this page */
  }
  applyTheme(next, root, doc);
  return next;
}

/** The theme currently stamped on the root (set by the boot script in index.html). */
export function currentTheme(root: ThemeRoot): Theme {
  return root.dataset.theme === "dark" ? "dark" : "light";
}
