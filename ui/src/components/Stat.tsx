import type { ReactNode } from "react";

// Meaning colours for inline styles on bars. They read the theme's CSS variables (index.css), so bars
// follow light and dark like everything else.
const c = (name: string) => `rgb(var(--c-${name}))`;
export const CLASS_COLORS: Record<string, string> = { EXACT: c("cls-exact"), EQUIVALENT: c("cls-equivalent"), POTENTIAL: c("cls-potential"), MISMATCH: c("cls-mismatch"), MISSING: c("cls-missing") };
export const SEV_COLORS: Record<string, string> = { BLOCKER: c("sev-blocker"), MAJOR: c("sev-major"), MINOR: c("sev-minor"), INFO: c("sev-info") };
export const BRAND_COLOR = c("brand-600");
export const BAD_COLOR = c("bad");

export function Stat({ label, value, sub, tone = "neutral", icon, className = "", size = "md" }: { label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: "neutral" | "good" | "warn" | "bad" | "brand"; icon?: ReactNode; className?: string; size?: "md" | "lg" }) {
  const tones = { neutral: "text-ink", good: "text-ok-strong", warn: "text-warn-strong", bad: "text-bad-strong", brand: "text-brand-700" };
  return (
    <div className={`card stat-card ${className}`}>
      <div className="stat-label flex items-center gap-1.5 text-xs font-medium text-ink-2">
        {icon && <span className="text-ink-3">{icon}</span>}
        {label}
      </div>
      <div className={`stat-value num font-semibold tracking-tight leading-none mt-1.5 ${size === "lg" ? "text-3xl" : "text-2xl"} ${tones[tone]}`}>{value}</div>
      {sub && <div className="stat-note text-xs text-ink-3 mt-1.5 leading-4">{sub}</div>}
    </div>
  );
}

export interface BarSegment {
  label: string;
  value: number;
  color: string;
}

/** Proportional bar: widths are shares of the total. `animate` fills it once from the left (the authored moment). */
export function Bar({ segments, height = 10, legend = true, animate = false }: { segments: BarSegment[]; height?: number; legend?: boolean; animate?: boolean }) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  return (
    <div>
      <div className="w-full overflow-hidden rounded-full bg-surface-3" style={{ height }} role="img" aria-label={segments.map((s) => `${s.label} ${s.value}`).join(", ")}>
        <div className={`flex h-full w-full ${animate ? "bar-enter" : ""}`}>
          {segments
            .filter((s) => s.value > 0)
            .map((s) => (
              <div key={s.label} title={`${s.label}: ${s.value}`} style={{ width: `${(100 * s.value) / total}%`, background: s.color }} />
            ))}
        </div>
      </div>
      {legend && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-ink-2">
          {segments.map((s) => (
            <span key={s.label} className="inline-flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded-full" style={{ background: s.color }} />
              {s.label} <span className="num font-semibold text-ink">{s.value}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** Single horizontal bar for dense tables (value / max). */
export function MiniBar({ value, max, color = BRAND_COLOR, width = 88 }: { value: number; max: number; color?: string; width?: number }) {
  const w = max > 0 ? Math.min(100, (100 * value) / max) : 0;
  return (
    <span className="inline-block align-middle bg-surface-3 h-1.5 rounded-full overflow-hidden" style={{ width }} aria-hidden>
      <span className="block h-full rounded-full transition-[width] duration-300 ease-out" style={{ width: `${w}%`, background: color }} />
    </span>
  );
}
