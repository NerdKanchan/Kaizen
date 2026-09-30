// Business case: what this run does to review effort, counted from its own rows.
import { ArrowCounterClockwise, ArrowsClockwise, CheckCircle, ListChecks, SlidersHorizontal, Target, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Badge } from "../components/Badges";
import { ErrorBox } from "../components/Feedback";
import { BAD_COLOR, BRAND_COLOR, MiniBar, Stat } from "../components/Stat";
import { Button, Card, CardHead, Field, PageHeader, SectionTitle, Skeleton } from "../components/ui";
import { enc, fmtMoney, pct } from "../lib/format";
import { useToast } from "../lib/toast";
import { useAsync } from "../lib/useAsync";
import type { BusinessParams } from "../types";

const FIELDS: { key: keyof BusinessParams; label: string; def: number; step?: number }[] = [
  { key: "baseline_minutes_per_sku", label: "Baseline minutes per SKU / reviewer", def: 60 },
  { key: "reviewers", label: "Reviewers per SKU", def: 2 },
  { key: "hourly_rate", label: "Hourly rate ($)", def: 37.5, step: 0.5 },
  { key: "skus_per_project", label: "SKUs per project", def: 100 },
  { key: "projects_per_year", label: "Projects per year", def: 20 },
  { key: "minutes_per_validation_row", label: "Minutes per flagged comparison", def: 1.5, step: 0.1 },
  { key: "minutes_per_cleared_row", label: "Minutes per auto-cleared comparison", def: 0.1, step: 0.05 },
  { key: "target_reduction_pct", label: "Target reduction (%)", def: 50 },
];

/** The API keeps the brief's assumption until this many decisions have been timed (docs/api-contract.md). */
const MIN_TIMED_DECISIONS = 10;
const OVER = BAD_COLOR;
const UNDER = BRAND_COLOR;

function paramsFrom(sp: URLSearchParams): BusinessParams {
  const out: BusinessParams = {};
  for (const f of FIELDS) {
    const v = sp.get(f.key);
    if (v !== null && v !== "" && !Number.isNaN(Number(v))) out[f.key] = Number(v);
  }
  return out;
}

export default function BusinessCasePage() {
  const { runId = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const toast = useToast();
  const params = paramsFrom(sp);
  const bc = useAsync(() => api.businessCase(runId, params), [runId, sp.toString()]);
  const [form, setForm] = useState<Record<string, string>>({});
  useEffect(() => {
    const f: Record<string, string> = {};
    for (const x of FIELDS) f[x.key] = String(params[x.key] ?? x.def);
    setForm(f);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sp.toString()]);

  const recompute = () => {
    const n = new URLSearchParams();
    let changed = 0;
    for (const x of FIELDS) {
      const v = Number(form[x.key]);
      if (!Number.isNaN(v) && v !== x.def) {
        n.set(x.key, String(v));
        changed += 1;
      }
    }
    setSp(n, { replace: true });
    const note = changed === 0 ? "Default values restored." : `${changed} custom value${changed === 1 ? "" : "s"} saved in the page link.`;
    toast({ tone: "ok", title: "Assumptions applied", description: note });
  };

  const reset = () => {
    setSp(new URLSearchParams(), { replace: true });
    toast({ tone: "info", title: "Assumptions reset", description: "Default values restored." });
  };

  const d = bc.data;
  const target = params.target_reduction_pct ?? 50;
  const assumedMinutes = params.minutes_per_validation_row ?? 1.5;
  const measuredBasis = d?.effort_basis === "measured";
  const usedMinutes = d?.minutes_per_validation_row_used ?? assumedMinutes;
  const timed = d?.timed_decisions ?? 0;
  const hasProjection = d?.confirmable_rows !== undefined;

  return (
    <div>
      <PageHeader
        back={{ to: `/runs/${enc(runId)}`, label: "Overview" }}
        title="Business case"
        description="Estimate review time and cost using this run’s results and your assumptions."
        meta={
          <>
            <span>
              Run <span className="mono">{runId}</span>
            </span>
            {d && <span>{d.skus} SKUs in this run</span>}
            <span>Target {target}% reduction</span>
          </>
        }
      />

      <div className="space-y-5 stagger">
        {bc.error && <ErrorBox error={bc.error} onRetry={bc.reload} />}
        {!d && !bc.error && <BusinessSkeleton />}

        {d && (
          <>
            {/* ---- the verdict, said plainly, and the effort figure it rests on */}
            <Card>
              <div className="grid lg:grid-cols-[1fr_20rem] divide-y lg:divide-y-0 lg:divide-x divide-line">
                <div className="p-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={d.meets_target ? "ok" : "bad"} dot={false} size="md">
                      {d.meets_target ? <CheckCircle size={16} weight="fill" /> : <Warning size={16} weight="fill" />}
                      {d.meets_target ? "Meets the target" : "Below the target"}
                    </Badge>
                    <span className="chip">
                      <Target size={14} />
                      {target}% target
                    </span>
                  </div>
                  <p className="text-lg text-ink mt-3 max-w-[62ch]">
                    Estimated review time is <b className="num">{d.estimated_minutes_per_sku} minutes per SKU</b>, compared with the {d.baseline_minutes_per_sku}-minute baseline. This is a <b className="num">{d.reduction_pct}%</b> reduction.
                    {!d.meets_target && ` The estimate is ${(target - d.reduction_pct).toFixed(1)} percentage points below the target.`}
                  </p>
                  <p className="text-sm text-ink-3 mt-2 max-w-[72ch]">
                    {d.needs_validation} of {d.rows} comparisons need review ({pct(d.needs_validation, d.rows)}%). Estimates use the review times shown below.
                  </p>
                </div>
                <div className="p-5">
                  <div className="label">Effort per flagged comparison</div>
                  <div className="flex items-baseline gap-2 mt-1">
                    <span className="num text-3xl font-semibold leading-none">{usedMinutes}</span>
                    <span className="text-sm text-ink-3">minutes</span>
                  </div>
                  <div className="mt-2">
                    <Badge tone={measuredBasis ? "ok" : "neutral"}>{measuredBasis ? "Measured on this run" : "Assumed"}</Badge>
                  </div>
                  <p className="text-sm text-ink-3 mt-2">
                    {measuredBasis ? (
                      <>
                        Uses the median of {timed} timed decisions instead of the {assumedMinutes}-minute assumption.
                      </>
                    ) : (
                      <>
                        Uses the entered assumption until {MIN_TIMED_DECISIONS} decisions have been timed. {timed} recorded so far
                        {d.measured_minutes_per_validation_row ? `, median ${d.measured_minutes_per_validation_row} minutes` : ""}.
                      </>
                    )}
                  </p>
                </div>
              </div>
            </Card>

            {/* ---- measured against projected, side by side and labelled */}
            <div className="grid xl:grid-cols-2 gap-x-6 gap-y-6 items-start">
              <div>
                <SectionTitle>Current estimate</SectionTitle>
                <p className="text-sm text-ink-3 mb-3 max-w-[56ch]">Based on this run’s results and the current assumptions.</p>
                <div className="business-metrics">
                  <Stat label="SKUs" value={d.skus} />
                  <Stat label="Reviewable comparisons" value={d.rows} sub="item and change rows" />
                  <Stat label="Auto-cleared" value={d.auto_cleared} tone="good" />
                  <Stat label="Flagged for review" value={d.needs_validation} tone="bad" />
                  <Stat label="Estimated minutes per SKU" value={d.estimated_minutes_per_sku} sub={`baseline ${d.baseline_minutes_per_sku}`} />
                  <Stat label="Reduction" value={`${d.reduction_pct}%`} tone={d.meets_target ? "good" : "bad"} sub={d.meets_target ? `meets the ${target}% target` : `below the ${target}% target`} />
                  <Stat label="Minutes saved per SKU" value={d.minutes_saved_per_sku} tone={d.minutes_saved_per_sku >= 0 ? "good" : "bad"} />
                  <Stat label="Hours saved per project" value={d.hours_saved_per_project} sub={`${d.skus_per_project} SKUs × ${d.reviewers} reviewers`} />
                  <Stat label="Annual savings" value={fmtMoney(d.annual_savings)} tone={d.annual_savings >= 0 ? "good" : "bad"} sub={`${d.projects_per_year} projects × $${d.hourly_rate} per hour`} />
                </div>
              </div>

              <div>
                <SectionTitle>With confirmed terminology</SectionTitle>
                <p className="text-sm text-ink-3 mb-3 max-w-[56ch]">
                  Estimates for future runs if {d.confirmable_rows ?? 0} suggested matches are confirmed and saved as terminology.
                </p>
                {hasProjection ? (
                  <div className="business-metrics">
                    <Stat label="Suggested matches" value={d.confirmable_rows ?? 0} sub="Match score ≥ 0.95; no discrepancies" />
                    <Stat label="Flagged for review" value={d.needs_validation_after_confirmation ?? "—"} tone="warn" />
                    <Stat label="Minutes per SKU" value={d.estimated_minutes_per_sku_after_confirmation ?? "—"} />
                    <Stat
                      label="Reduction"
                      value={`${d.reduction_pct_after_confirmation ?? "—"}%`}
                      tone={d.meets_target_after_confirmation ? "good" : "bad"}
                      sub={d.meets_target_after_confirmation ? `meets the ${target}% target` : `still below the ${target}% target`}
                    />
                    <Stat label="Hours saved per project" value={d.hours_saved_per_project_after_confirmation ?? "—"} />
                    <Stat label="Annual savings" value={d.annual_savings_after_confirmation !== undefined ? fmtMoney(d.annual_savings_after_confirmation) : "—"} tone="good" />
                  </div>
                ) : (
                  <Card className="p-5 text-sm text-ink-3">No terminology projection is available for this run.</Card>
                )}
              </div>
            </div>

            {/* ---- the assumptions: editable, and then stated as the calculator applied them */}
            <div className="grid xl:grid-cols-2 gap-5 items-start">
              <Card>
                <CardHead icon={<SlidersHorizontal size={16} />} title="Assumptions" description="Adjust the values and recalculate the estimates." />
                <div className="p-4">
                  <div className="grid sm:grid-cols-2 gap-x-4 gap-y-3">
                    {FIELDS.map((f) => (
                      <Field key={f.key} label={f.label} htmlFor={`bc-${f.key}`} hint={`Default ${f.def}`}>
                        <input
                          id={`bc-${f.key}`}
                          type="number"
                          step={f.step ?? 1}
                          className="input num w-full text-right"
                          value={form[f.key] ?? ""}
                          onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") recompute();
                          }}
                        />
                      </Field>
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-2 mt-4">
                    <Button variant="primary" onClick={recompute} icon={<ArrowsClockwise size={16} />}>
                      Recalculate
                    </Button>
                    <Button onClick={reset} icon={<ArrowCounterClockwise size={16} />}>
                      Reset defaults
                    </Button>
                  </div>
                </div>
              </Card>

              <Card>
                <CardHead icon={<ListChecks size={16} />} title="Calculation details" description="Assumptions used in these estimates." />
                <div className="p-4">
                  <ul className="list-disc pl-5 space-y-2 text-sm text-ink-2 marker:text-ink-4 max-w-[68ch]">
                    {d.assumptions.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                </div>
              </Card>
            </div>

            <Card>
              <CardHead title="Per SKU" count={`${Object.keys(d.per_sku).length} SKUs`} description={`Estimated review minutes against a baseline of ${d.baseline_minutes_per_sku} minutes per SKU.`} />
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>SKU</th>
                      <th className="text-right">Rows</th>
                      <th className="text-right">Auto-cleared</th>
                      <th className="text-right">Flagged for review</th>
                      <th className="text-right">Estimated minutes</th>
                      <th>Against baseline</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(d.per_sku).map(([sku, p]) => {
                      const over = p.estimated_minutes > d.baseline_minutes_per_sku;
                      const share = Math.round((100 * p.estimated_minutes) / Math.max(1, d.baseline_minutes_per_sku));
                      return (
                        <tr key={sku}>
                          <td className="mono whitespace-nowrap">{sku}</td>
                          <td className="text-right num">{p.rows}</td>
                          <td className="text-right num text-ok-strong">{p.auto_cleared}</td>
                          <td className="text-right num text-bad-strong">{p.needs_validation}</td>
                          <td className={`text-right num ${over ? "text-bad-strong font-semibold" : ""}`}>{p.estimated_minutes}</td>
                          <td className="whitespace-nowrap">
                            <MiniBar value={p.estimated_minutes} max={d.baseline_minutes_per_sku} color={over ? OVER : UNDER} width={140} />
                            <span className="num text-xs text-ink-3 ml-2">{share}% of baseline</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

function BusinessSkeleton() {
  return (
    <div className="space-y-5" aria-busy aria-label="Loading the business case">
      <div className="card p-5 space-y-3">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-5 w-[32rem] max-w-full" />
        <Skeleton className="h-4 w-[24rem] max-w-full" />
      </div>
      <div className="grid xl:grid-cols-2 gap-6">
        {Array.from({ length: 2 }).map((_, col) => (
          <div key={col}>
            <Skeleton className="h-4 w-48 mb-3" />
            <div className="business-metrics">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="card px-4 py-3">
                  <Skeleton className="h-3 w-20 mb-2" />
                  <Skeleton className="h-7 w-14" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
