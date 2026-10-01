import { CaretDown, CaretRight } from "@phosphor-icons/react";
import { useEffect, useId, useState, type ReactNode } from "react";

/** Each section remembers its disclosure state; navigation reveals the active destination. */
export function SidebarSection({ label, storageKey, activePath, icon, children, className = "", defaultOpen = true }: {
  label: string; storageKey: string; activePath?: string; icon?: ReactNode; children: ReactNode; className?: string; defaultOpen?: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(() => {
    if (activePath) return true;
    try { const saved = localStorage.getItem(storageKey); return saved === null ? defaultOpen : saved === "1"; } catch { return defaultOpen; }
  });
  useEffect(() => { if (activePath) setOpen(true); }, [activePath]);
  const toggle = () => {
    const next = !open;
    setOpen(next);
    try { localStorage.setItem(storageKey, next ? "1" : "0"); } catch { /* optional preference */ }
  };
  return <div className={`sidebar-section ${className}`}>
    <button className="sidebar-section-toggle" type="button" aria-expanded={open} aria-controls={id} onClick={toggle} title={label}>
      {icon}<span className="sidebar-section-name">{label}</span>
      {open ? <CaretDown size={13} aria-hidden /> : <CaretRight size={13} aria-hidden />}
    </button>
    <div id={id} hidden={!open}>{children}</div>
  </div>;
}
