/** @type {import('tailwindcss').Config} */
// Colour tokens are CSS variables holding RGB channels; src/index.css defines the light and the dark
// set, so `bg-surface`, `text-ink-3`, `bg-ok-soft/60` and friends switch with the theme without any
// component knowing. docs/design/DESIGN.md is the contract, including the dark composition.
const v = (name) => `rgb(var(--c-${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Geist Variable", "Geist", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["Geist Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      colors: {
        canvas: v("canvas"),
        // Hyperlinks have their own token so they never drift from the brand scale.
        link: v("link"),
        surface: { DEFAULT: v("surface"), 2: v("surface-2"), 3: v("surface-3") },
        line: { DEFAULT: v("line"), 2: v("line-2") },
        // ink-contrast is the text colour that sits on an ink-filled shape (white in light, canvas in dark).
        ink: { DEFAULT: v("ink"), 2: v("ink-2"), 3: v("ink-3"), 4: v("ink-3"), contrast: v("ink-contrast") },
        // The navigation rail has its own family: BD navy in light, a deeper navy in dark.
        rail: { DEFAULT: v("rail"), ink: v("rail-ink"), muted: v("rail-muted"), dim: v("rail-dim") },
        brand: {
          50: v("brand-50"),
          100: v("brand-100"),
          200: v("brand-200"),
          300: v("brand-300"),
          500: v("brand-500"),
          600: v("brand-600"),
          700: v("brand-700"),
          800: v("brand-800"),
          900: v("brand-900"),
          // A filled brand chip (document type): navy with white text in both themes.
          fill: v("brand-fill"),
          "fill-ink": v("brand-fill-ink"),
        },
        // BD orange is the same in both themes; only its soft surfaces change. accent-ink is the text
        // colour on orange: always ink, never white (DESIGN.md).
        accent: { 50: v("accent-50"), 100: v("accent-100"), 200: v("accent-200"), 400: v("accent-400"), 500: v("accent-500"), 600: v("accent-600"), 700: v("accent-700"), ink: v("accent-ink") },
        ok: { DEFAULT: v("ok"), soft: v("ok-soft"), strong: v("ok-strong") },
        warn: { DEFAULT: v("warn"), soft: v("warn-soft"), strong: v("warn-strong") },
        bad: { DEFAULT: v("bad"), soft: v("bad-soft"), strong: v("bad-strong") },
        // Classification and severity are meaning; never reuse these for decoration.
        cls: {
          exact: v("cls-exact"),
          equivalent: v("cls-equivalent"),
          potential: v("cls-potential"),
          mismatch: v("cls-mismatch"),
          missing: v("cls-missing"),
          "equivalent-soft": v("cls-equivalent-soft"),
          "equivalent-strong": v("cls-equivalent-strong"),
          "missing-soft": v("cls-missing-soft"),
          "missing-strong": v("cls-missing-strong"),
        },
        sev: { blocker: v("sev-blocker"), major: v("sev-major"), minor: v("sev-minor"), info: v("sev-info") },
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1.0625rem" }],
        xs: ["0.75rem", { lineHeight: "1.125rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.375rem" }],
        md: ["1rem", { lineHeight: "1.625rem" }],
        lg: ["1.125rem", { lineHeight: "1.75rem" }],
        xl: ["1.25rem", { lineHeight: "1.75rem" }],
        "2xl": ["1.375rem", { lineHeight: "1.75rem", letterSpacing: "-0.01em" }],
        "3xl": ["1.75rem", { lineHeight: "2.125rem", letterSpacing: "-0.015em" }],
        "4xl": ["2.375rem", { lineHeight: "2.5rem", letterSpacing: "-0.02em" }],
      },
      borderRadius: { sm: "6px", DEFAULT: "8px", md: "10px", lg: "12px", xl: "16px" },
      boxShadow: {
        pop: "var(--shadow-pop)",
        lift: "var(--shadow-lift)",
        ring: "0 0 0 2px rgb(var(--c-surface)), 0 0 0 4px var(--accent-focus)",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.16, 1, 0.3, 1)",
        inout: "cubic-bezier(0.77, 0, 0.175, 1)",
      },
      keyframes: {
        rise: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        pop: { from: { opacity: "0", transform: "scale(0.97)" }, to: { opacity: "1", transform: "scale(1)" } },
        fade: { from: { opacity: "0" }, to: { opacity: "1" } },
        shimmer: { from: { backgroundPosition: "200% 0" }, to: { backgroundPosition: "-200% 0" } },
        fill: { from: { transform: "scaleX(0)" }, to: { transform: "scaleX(1)" } },
      },
      animation: {
        rise: "rise 220ms cubic-bezier(0.16, 1, 0.3, 1) both",
        pop: "pop 180ms cubic-bezier(0.16, 1, 0.3, 1) both",
        fade: "fade 160ms ease-out both",
        shimmer: "shimmer 1.6s linear infinite",
        fill: "fill 600ms cubic-bezier(0.16, 1, 0.3, 1) both",
      },
      maxWidth: { page: "1440px" },
    },
  },
  plugins: [],
};
