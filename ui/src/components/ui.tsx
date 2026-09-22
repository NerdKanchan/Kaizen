// Primitives shared by every page. Visual rules: docs/design/DESIGN.md. Keep the vocabulary small and
// consistent: a page should never invent its own button or card.
import { CircleNotch, X } from "@phosphor-icons/react";
import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link, type LinkProps } from "react-router-dom";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

function btnClass(variant: Variant = "secondary", size: Size = "md", icon = false, extra = "") {
  const v = variant === "primary" ? "btn-primary" : variant === "ghost" ? "btn-ghost" : variant === "danger" ? "btn-danger" : "";
  const s = size === "sm" ? "btn-sm" : size === "lg" ? "btn-lg" : "";
  return ["btn", v, s, icon ? "btn-icon" : "", extra].filter(Boolean).join(" ");
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  iconRight?: ReactNode;
  loading?: boolean;
  /** Icon-only button: pass `aria-label` and no children. */
  iconOnly?: boolean;
}

export function Button({ variant, size, icon, iconRight, loading, iconOnly, className = "", children, disabled, type = "button", ...rest }: ButtonProps) {
  return (
    <button type={type} className={btnClass(variant, size, iconOnly, className)} disabled={disabled || loading} {...rest}>
      {loading ? <CircleNotch size={16} className="animate-spin" aria-hidden /> : icon}
      {children}
      {iconRight}
    </button>
  );
}

export function LinkButton({ variant, size, icon, iconRight, iconOnly, className = "", children, ...rest }: LinkProps & { variant?: Variant; size?: Size; icon?: ReactNode; iconRight?: ReactNode; iconOnly?: boolean }) {
  return (
    <Link className={btnClass(variant, size, iconOnly, className)} {...rest}>
      {icon}
      {children}
      {iconRight}
    </Link>
  );
}

export function AnchorButton({ variant, size, icon, iconRight, className = "", children, ...rest }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: Variant; size?: Size; icon?: ReactNode; iconRight?: ReactNode }) {
  return (
    <a className={btnClass(variant, size, false, className)} {...rest}>
      {icon}
      {children}
      {iconRight}
    </a>
  );
}

// ---- surfaces --------------------------------------------------------------------------------

export function Card({ className = "", children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <section className={`card ${className}`} {...rest}>
      {children}
    </section>
  );
}

export function CardHead({ title, description, actions, icon, count, className = "" }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; icon?: ReactNode; count?: ReactNode; className?: string }) {
  return (
    <header className={`card-head flex-wrap gap-y-2 ${className}`}>
      {icon && <span className="text-brand-600 shrink-0">{icon}</span>}
      <div className="card-head-title">
        <h2 className="card-title flex items-baseline gap-2">
          <span className="truncate">{title}</span>
          {count !== undefined && <span className="text-sm font-normal text-ink-3 num">{count}</span>}
        </h2>
        {description && <p className="text-xs text-ink-3 mt-0.5">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-1.5 ml-auto max-w-full">{actions}</div>}
    </header>
  );
}

export function PageHeader({ title, description, actions, meta, back }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; meta?: ReactNode; back?: { to: string; label: string } }) {
  return (
    <div className="flex flex-wrap items-start gap-x-6 gap-y-3 mb-5">
      <div className="head-title">
        {back && (
          <Link to={back.to} className="inline-flex items-center gap-1 text-xs text-ink-3 hover:text-brand-600 no-underline mb-1">
            ← {back.label}
          </Link>
        )}
        <h1 className="flex flex-wrap items-center gap-x-3 gap-y-1">{title}</h1>
        {description && <p className="text-sm text-ink-3 mt-1 max-w-[72ch]">{description}</p>}
        {meta && <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3 mt-2">{meta}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 max-w-full">{actions}</div>}
    </div>
  );
}

export function SectionTitle({ children, count, actions, className = "" }: { children: ReactNode; count?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={`flex items-center gap-2 mb-2 ${className}`}>
      <h2 className="text-sm font-semibold text-ink">{children}</h2>
      {count !== undefined && <span className="text-xs text-ink-3 num">{count}</span>}
      {actions && <div className="ml-auto flex items-center gap-1.5">{actions}</div>}
    </div>
  );
}

// ---- fields ----------------------------------------------------------------------------------

export function Field({ label, hint, error, htmlFor, children, className = "" }: { label: ReactNode; hint?: ReactNode; error?: ReactNode; htmlFor?: string; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <label className="label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {error ? <div className="text-xs text-bad mt-1">{error}</div> : hint ? <div className="hint mt-1">{hint}</div> : null}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}

// ---- loading and empty -----------------------------------------------------------------------

export function Skeleton({ className = "", style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden />;
}

export function TableSkeleton({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="p-3 space-y-2" aria-busy aria-label="Loading">
      <div className="flex gap-3">
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} className="h-3 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} className="h-4 flex-1" style={{ opacity: 1 - r * 0.1 }} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ icon, title, description, action, className = "" }: { icon?: ReactNode; title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col items-center text-center px-6 py-10 ${className}`}>
      {icon && <div className="text-brand-300 mb-3">{icon}</div>}
      <div className="text-md font-semibold text-ink">{title}</div>
      {description && <p className="text-sm text-ink-3 mt-1 max-w-[46ch]">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ---- overlay ---------------------------------------------------------------------------------

export function Dialog({ open, onClose, title, description, children, footer, width = "md", closeLabel = "Close" }: { open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children?: ReactNode; footer?: ReactNode; width?: "sm" | "md" | "lg"; closeLabel?: string }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey, true);
    panel.current?.querySelector<HTMLElement>("button, [href], input, select, textarea")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey, true);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  const w = width === "sm" ? "max-w-md" : width === "lg" ? "max-w-3xl" : "max-w-xl";
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 scrim enter-fade" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={panel} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined} className={`w-full ${w} max-h-[calc(100vh-2rem)] overflow-y-auto card shadow-pop enter-pop`}>
        <div className="flex items-start gap-3 px-5 pt-4 pb-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold">{title}</h2>
            {description && <p className="text-sm text-ink-3 mt-0.5">{description}</p>}
          </div>
          <Button variant="ghost" size="sm" iconOnly aria-label={closeLabel} onClick={onClose} icon={<X size={16} />} />
        </div>
        {children && <div className="px-5 pb-4 text-sm space-y-3">{children}</div>}
        {footer && <div className="flex justify-end gap-2 px-5 py-3 border-t border-line bg-surface-2/60 rounded-b-lg">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Divider({ className = "" }: { className?: string }) {
  return <hr className={`border-line ${className}`} />;
}
