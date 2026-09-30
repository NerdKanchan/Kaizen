// Colour is meaning, and meaning is always also a word. Palettes: docs/design/DESIGN.md.
import type { ReactNode } from "react";
import type { Classification, DecisionKind, ReviewState, Severity } from "../types";

type Tone = "exact" | "equivalent" | "potential" | "mismatch" | "missing" | "ok" | "warn" | "bad" | "info" | "neutral" | "ink";

const TONE: Record<Tone, string> = {
  exact: "bg-ok-soft text-ok-strong",
  equivalent: "bg-cls-equivalent-soft text-cls-equivalent-strong",
  potential: "bg-warn-soft text-warn-strong",
  mismatch: "bg-bad-soft text-bad-strong",
  missing: "bg-cls-missing-soft text-cls-missing-strong",
  ok: "bg-ok-soft text-ok-strong",
  warn: "bg-warn-soft text-warn-strong",
  bad: "bg-bad-soft text-bad-strong",
  info: "bg-brand-100 text-brand-700",
  neutral: "bg-surface-2 text-ink-2",
  ink: "bg-ink text-ink-contrast",
};
const DOT: Record<Tone, string> = {
  exact: "bg-cls-exact",
  equivalent: "bg-cls-equivalent",
  potential: "bg-cls-potential",
  mismatch: "bg-cls-mismatch",
  missing: "bg-cls-missing",
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  info: "bg-brand-600",
  neutral: "bg-ink-3",
  ink: "bg-ink-contrast",
};

export function Badge({ tone = "neutral", dot = true, size = "sm", title, children, className = "" }: { tone?: Tone; dot?: boolean; size?: "sm" | "md"; title?: string; children: ReactNode; className?: string }) {
  const sz = size === "md" ? "h-7 px-2.5 text-sm" : "h-[22px] px-2 text-xs";
  return (
    <span title={title} className={`inline-flex items-center gap-1.5 rounded-full font-medium whitespace-nowrap ${sz} ${TONE[tone]} ${className}`}>
      {dot && <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${DOT[tone]}`} aria-hidden />}
      {children}
    </span>
  );
}

const CLS_TONE: Record<Classification, Tone> = { EXACT: "exact", EQUIVALENT: "equivalent", POTENTIAL: "potential", MISMATCH: "mismatch", MISSING: "missing" };
const CLS_LABEL: Record<Classification, string> = { EXACT: "Exact", EQUIVALENT: "Equivalent", POTENTIAL: "Potential", MISMATCH: "Mismatch", MISSING: "Missing" };

export function ClassificationBadge({ value, title, size = "sm" }: { value: string | null | undefined; title?: string; size?: "sm" | "lg" | "md" }) {
  if (!value) return <span className="text-ink-4">—</span>;
  const tone = CLS_TONE[value as Classification] ?? "neutral";
  return (
    <Badge tone={tone} size={size === "sm" ? "sm" : "md"} title={title}>
      {CLS_LABEL[value as Classification] ?? value}
    </Badge>
  );
}

const SEV: Record<Severity, string> = {
  BLOCKER: "bg-bad-soft text-bad-strong",
  MAJOR: "bg-warn-soft text-warn-strong",
  MINOR: "bg-warn-soft text-warn-strong",
  INFO: "bg-surface-2 text-ink-2",
};
const SEV_LABEL: Record<Severity, string> = { BLOCKER: "Blocker", MAJOR: "Major", MINOR: "Minor", INFO: "Info" };

export function SeverityBadge({ value, size = "sm" }: { value: string | null | undefined; size?: "sm" | "md" }) {
  if (!value) return <span className="text-ink-4">—</span>;
  const cls = SEV[value as Severity] ?? "bg-surface-3 text-ink";
  const sz = size === "md" ? "h-7 px-2.5 text-sm" : "h-[22px] px-2 text-xs";
  return <span className={`inline-flex items-center rounded-md font-medium whitespace-nowrap ${sz} ${cls}`}>{SEV_LABEL[value as Severity] ?? value}</span>;
}

const STATE_TONE: Record<ReviewState, Tone> = {
  REVIEWED: "info",
  ENGINE_RECOMMENDED: "neutral",
  REVIEWER_1_COMPLETE: "info",
  REVIEWER_2_COMPLETE: "info",
  AGREED: "ok",
  DISAGREEMENT: "bad",
  FINALIZED: "ink",
};
const STATE_LABEL: Record<ReviewState, string> = {
  REVIEWED: "Reviewed",
  ENGINE_RECOMMENDED: "Not reviewed",
  REVIEWER_1_COMPLETE: "Reviewer 1 done",
  REVIEWER_2_COMPLETE: "Reviewer 2 done",
  AGREED: "Agreed",
  DISAGREEMENT: "Disagreement",
  FINALIZED: "Approved",
};

export function StateBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-ink-4">—</span>;
  return (
    <Badge tone={STATE_TONE[value as ReviewState] ?? "neutral"} dot={value !== "ENGINE_RECOMMENDED"}>
      {STATE_LABEL[value as ReviewState] ?? value.replace(/_/g, " ")}
    </Badge>
  );
}

const DEC_TONE: Record<DecisionKind, Tone> = { ACCEPT: "ok", OVERRIDE: "warn", CONFIRM_DISCREPANCY: "bad", NEEDS_MORE_INFORMATION: "info" };
const DEC_LABEL: Record<DecisionKind, string> = { ACCEPT: "Accept", OVERRIDE: "Override", CONFIRM_DISCREPANCY: "Confirm discrepancy", NEEDS_MORE_INFORMATION: "Needs more information" };

export function DecisionBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-ink-4">—</span>;
  return <Badge tone={DEC_TONE[value as DecisionKind] ?? "neutral"}>{DEC_LABEL[value as DecisionKind] ?? value.replace(/_/g, " ")}</Badge>;
}

export function DocTypeBadge({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  return <span className="inline-flex items-center h-[22px] px-2 rounded-md bg-brand-fill text-brand-fill-ink text-2xs font-semibold tracking-wider">{value}</span>;
}

export function RoleTag({ value }: { value: string }) {
  if (value === "item") return null;
  return (
    <span className="chip" title="Row role: not an item comparison">
      {value}
    </span>
  );
}

export function StatusBadge({ value }: { value: string }) {
  const map: Record<string, Tone> = { OPEN: "bad", IN_PROGRESS: "warn", RESOLVED: "ok", CLOSED: "ink", REJECTED: "neutral" };
  return <Badge tone={map[value] ?? "neutral"}>{value.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}</Badge>;
}
