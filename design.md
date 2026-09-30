# Kaizen design system

The canonical system is [docs/design/DESIGN.md](docs/design/DESIGN.md).
Read its September 2026 navigation and appearance revisions together with the semantic
colour and interaction rules. Shared extension tokens are in [tokens.css](tokens.css);
existing RGB semantic tokens stay in `ui/src/index.css` for Tailwind compatibility.

Genre: modern-minimal. App structure: a workbench with grouped navigation, a
context bar, and one primary task per page. Use neutral surfaces, restrained BD orange actions, and the bundled
Geist / Geist Mono typography. No decorative imagery in the review workflow.

## Exports

These mappings cover the shared core roles. The running app uses Tailwind v3 and
its existing RGB semantic variables; the complete theme and status palette stays
in `ui/src/index.css`.

### CSS

The shared CSS aliases, spacing, font and radius values are in [tokens.css](tokens.css),
which is imported by the application stylesheet.

### Tailwind v4

For a future v4 consumer that also loads the runtime RGB variables:

```css
@theme inline {
  --color-paper: rgb(var(--c-canvas));
  --color-paper-2: rgb(var(--c-surface));
  --color-ink: rgb(var(--c-ink));
  --color-ink-2: rgb(var(--c-ink-3));
  --color-rule: rgb(var(--c-line));
  --color-accent: rgb(var(--c-accent-500));
  --color-accent-ink: rgb(var(--c-accent-ink));
  --font-body: 'Geist Variable', sans-serif;
  --font-display: var(--font-body);
  --spacing-xs: .5rem;
  --spacing-sm: .75rem;
  --spacing-md: 1rem;
  --spacing-lg: 1.5rem;
  --spacing-xl: 2rem;
  --spacing-2xl: 3rem;
  --radius-card: 10px;
  --radius-input: 7px;
  --ease-out: cubic-bezier(.16, 1, .3, 1);
}
```

### DTCG JSON

Core colours for a token pipeline; choose the light or dark group for the target theme.
Hex values preserve the app’s integer RGB values exactly.

```json
{
  "light": {
    "paper": {"$type": "color", "$value": "#F8F9FB"},
    "paper-2": {"$type": "color", "$value": "#FFFFFF"},
    "ink": {"$type": "color", "$value": "#1E242E"},
    "ink-2": {"$type": "color", "$value": "#636E7F"},
    "rule": {"$type": "color", "$value": "#E1E5EC"},
    "accent": {"$type": "color", "$value": "#FF6E00"},
    "accent-ink": {"$type": "color", "$value": "#181B21"}
  },
  "dark": {
    "paper": {"$type": "color", "$value": "#14161B"},
    "paper-2": {"$type": "color", "$value": "#1B1E24"},
    "ink": {"$type": "color", "$value": "#EBEEF4"},
    "ink-2": {"$type": "color", "$value": "#A3ACBB"},
    "rule": {"$type": "color", "$value": "#2F333C"},
    "accent": {"$type": "color", "$value": "#F49F62"},
    "accent-ink": {"$type": "color", "$value": "#181B21"}
  }
}
```

### shadcn/ui

OKLCH triples for a consumer configured to use `oklch(var(--background))` and
the equivalent role expressions. Conversion is rounded to six decimal places.

```css
:root {
  --background: 0.981921 0.002863 264.5421;
  --foreground: 0.258911 0.020812 260.5842;
  --card: 1.000000 0.000000 89.8756;
  --card-foreground: 0.258911 0.020812 260.5842;
  --popover: 1.000000 0.000000 89.8756;
  --popover-foreground: 0.258911 0.020812 260.5842;
  --primary: 0.706218 0.198191 46.1095;
  --primary-foreground: 0.221663 0.012598 264.2756;
  --muted-foreground: 0.535124 0.029882 259.0343;
  --border: 0.920875 0.010423 261.7883;
  --input: 0.920875 0.010423 261.7883;
  --ring: 0.706218 0.198191 46.1095;
  --radius: 0.625rem;
}
[data-theme="dark"] {
  --background: 0.200297 0.010493 268.1595;
  --foreground: 0.948555 0.008678 264.5213;
  --card: 0.234544 0.012415 264.3004;
  --card-foreground: 0.948555 0.008678 264.5213;
  --popover: 0.234544 0.012415 264.3004;
  --popover-foreground: 0.948555 0.008678 264.5213;
  --primary: 0.775411 0.127396 55.2558;
  --primary-foreground: 0.221663 0.012598 264.2756;
  --muted-foreground: 0.742068 0.023880 260.7118;
  --border: 0.320885 0.016971 266.4150;
  --input: 0.320885 0.016971 266.4150;
  --ring: 0.775411 0.127396 55.2558;
  --radius: 0.625rem;
}
```
