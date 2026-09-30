import { ArrowsClockwise, CheckCircle, Info, Warning, WarningOctagon } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { Button, Dialog, Skeleton } from "./ui";

/** Loading state shaped like content, never a spinner in the middle of the page. */
export function Loading({ label = "Loading", lines = 3 }: { label?: string; lines?: number }) {
  return (
    <div className="space-y-2 py-2" aria-busy aria-label={label}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className="h-4" style={{ width: `${88 - i * 14}%` }} />
      ))}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-bad/30 bg-bad-soft text-bad-strong px-4 py-3 text-sm">
      <WarningOctagon size={18} weight="fill" className="shrink-0 mt-0.5 text-bad" />
      <div className="flex-1 min-w-0 break-words">
        <div className="font-medium">Request failed</div>
        <div className="text-ink-2 mt-0.5">{error}</div>
      </div>
      {onRetry && (
        <Button size="sm" onClick={onRetry} icon={<ArrowsClockwise size={14} />}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function Notice({ kind = "info", children, className = "" }: { kind?: "info" | "good" | "warn" | "bad"; children: ReactNode; className?: string }) {
  const map = {
    info: { cls: "border-line bg-surface-2 text-ink-2", icon: <Info size={18} weight="fill" className="text-ink-3" /> },
    good: { cls: "border-ok/30 bg-ok-soft text-ok-strong", icon: <CheckCircle size={18} weight="fill" className="text-ok" /> },
    warn: { cls: "border-warn/30 bg-warn-soft text-warn-strong", icon: <Warning size={18} weight="fill" className="text-warn" /> },
    bad: { cls: "border-bad/30 bg-bad-soft text-bad-strong", icon: <WarningOctagon size={18} weight="fill" className="text-bad" /> },
  }[kind];
  return (
    <div className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${map.cls} ${className}`}>
      <span className="shrink-0 mt-0.5">{map.icon}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export function ConfirmDialog({ title, description, children, confirmLabel = "Confirm", onConfirm, onCancel, busy = false, tone = "primary" }: { title: string; description?: ReactNode; children?: ReactNode; confirmLabel?: string; onConfirm: () => void; onCancel: () => void; busy?: boolean; tone?: "primary" | "danger" }) {
  return (
    <Dialog
      open
      onClose={onCancel}
      title={title}
      description={description}
      footer={
        <>
          <Button onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant={tone} onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}
