// Run-to-run diff: after corrected documents come back, show only what moved.
import { ArrowRight, CheckCircle, GitDiff } from "@phosphor-icons/react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ClassificationBadge } from "../components/Badges";
import { ErrorBox, Notice } from "../components/Feedback";
import { Stat } from "../components/Stat";
import { Card, CardHead, EmptyState, Field, LinkButton, PageHeader, TableSkeleton } from "../components/ui";
import { enc, shortSha } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import type { DiffStatus, RunDiffRow } from "../types";

const STATUS_LABEL: Record<DiffStatus, string> = {
  resolved: "Resolved",
  new: "New",
  still_open: "Still open",
  changed: "Changed",
  unchanged: "Unchanged",
  gone: "Gone",
  not_covered: "Not covered",
};
/** Colour is meaning, so every status says its meaning in words as well. */
const STATUS_MEANING: Record<DiffStatus, string> = {
  resolved: "The discrepancy is no longer reported.",
  new: "Not present in the earlier run.",
  still_open: "The same discrepancy is still reported.",
  changed: "The classification or the discrepancies differ.",
  unchanged: "Identical in both runs.",
  gone: "The comparison itself disappeared, which is not the same as fixed.",
  not_covered: "Only one of the two runs has this comparison.",
};
const STATUS_TONE: Record<DiffStatus, "good" | "bad" | "warn" | "neutral"> = {
  resolved: "good",
  new: "bad",
  still_open: "bad",
  changed: "neutral",
  unchanged: "neutral",
  gone: "warn",
  not_covered: "neutral",
};
const LISTED: DiffStatus[] = ["resolved", "new", "still_open", "gone", "changed"];
const CHECK_LABEL: Record<string, string> = { BOM_LABEL: "BOM to label", BOM_DRAWING: "BOM to drawing", LABEL_DRAWING: "Label to drawing", PCO_BOM: "PCO to BOM", LABEL_REVISION: "Label revision" };

export default function DiffPage() {
  const { runId = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const against = sp.get("against") ?? "";
  const runs = useAsync(() => api.listRuns(), []);
  const diff = useAsync(() => (against ? api.getDiff(runId, against) : Promise.resolve(null)), [runId, against]);
  const others = (runs.data ?? []).filter((r) => r.run_id !== runId);
  const dd = diff.data;
  const listedRows = dd ? dd.rows.filter((r) => LISTED.includes(r.status)).length : 0;

  return (
    <div>
      <PageHeader
        back={{ to: `/runs/${enc(runId)}`, label: "Dashboard" }}
        title="Compare runs"
        description="After corrected documents come back, this shows only what moved. Rows are matched by their comparison key, so a row that was renumbered still lines up."
        meta={
          <>
            <span>
              This run <span className="mono">{runId}</span>
            </span>
            {against && (
              <span>
                against <span className="mono">{against}</span>
              </span>
            )}
          </>
        }
        actions={
          <Field label="Earlier run" htmlFor="diff-against" className="w-[24rem] max-w-full">
            <select
              id="diff-against"
              className="input mono w-full"
              value={against}
              disabled={others.length === 0}
              onChange={(e) => {
                const n = new URLSearchParams(sp);
                if (e.target.value) n.set("against", e.target.value);
                else n.delete("against");
                setSp(n, { replace: true });
              }}
            >
              <option value="">Choose an earlier run</option>
              {others.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id} · {r.created_at.slice(0, 16)} · {r.summary.skus} SKUs
                </option>
              ))}
            </select>
          </Field>
        }
      />

      <div className="space-y-5 stagger">
        <Notice>
          Rows are matched across runs by their comparison key (check, SKU and item), not by row id. <b>Resolved</b> means the discrepancy is no longer reported; <b>gone</b> means the comparison itself disappeared, which is not the same as
          fixed. Action items close through "Verify and close" on the dashboard; this page only shows the change.
        </Notice>

        {runs.error && <ErrorBox error={runs.error} onRetry={runs.reload} />}
        {diff.error && <ErrorBox error={diff.error} onRetry={diff.reload} />}

        {!against && (
          <Card>
            {others.length === 0 && runs.data ? (
              <EmptyState
                icon={<GitDiff size={36} />}
                title="There is no other run to compare against"
                description="This workspace holds one run. Run the corrected documents, then come back and pick the earlier run."
                action={
                  <LinkButton to="/" iconRight={<ArrowRight size={16} />}>
                    Go to runs
                  </LinkButton>
                }
              />
            ) : (
              <EmptyState icon={<GitDiff size={36} />} title="Choose an earlier run" description="Pick the run recorded before the corrected documents arrived. Only the comparisons that moved are listed." />
            )}
          </Card>
        )}

        {against && diff.loading && !dd && (
          <Card>
            <TableSkeleton rows={6} cols={6} />
          </Card>
        )}

        {dd && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
              {(Object.keys(STATUS_LABEL) as DiffStatus[]).map((k) => (
                <Stat key={k} label={STATUS_LABEL[k]} value={dd.counts[k]} tone={STATUS_TONE[k]} sub={STATUS_MEANING[k]} />
              ))}
            </div>

            <Card>
              <CardHead title="What the two runs hold" description="The SKUs and the documents behind the comparison." />
              <div className="grid md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-line text-sm">
                <div className="p-4">
                  <div className="label">SKUs</div>
                  <p className="text-ink-2">
                    <span className="num font-medium text-ink">{dd.skus.common.length}</span> in both runs
                    {dd.skus.added.length > 0 && <> · added {dd.skus.added.join(", ")}</>}
                    {dd.skus.removed.length > 0 && <> · removed {dd.skus.removed.join(", ")}</>}
                  </p>
                </div>
                <div className="p-4">
                  <div className="label">Documents</div>
                  {dd.documents.changed.length === 0 ? (
                    <p className="text-ink-2">No document changed content between the runs.</p>
                  ) : (
                    <>
                      <p className="text-ink-2">
                        <span className="num font-medium text-ink">{dd.documents.changed.length}</span> document{dd.documents.changed.length === 1 ? "" : "s"} changed content:
                      </p>
                      <ul className="mt-1 space-y-0.5">
                        {dd.documents.changed.map((x) => (
                          <li key={x.path} className="mono text-xs text-ink-2 break-all" title={`${shortSha(x.before_sha256)} → ${shortSha(x.after_sha256)}`}>
                            {x.path}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {(dd.documents.added.length > 0 || dd.documents.removed.length > 0) && (
                    <p className="text-ink-3 mt-1">
                      {dd.documents.added.length} added · {dd.documents.removed.length} removed
                    </p>
                  )}
                </div>
              </div>
            </Card>

            {LISTED.map((status) => {
              const rows = dd.rows.filter((r) => r.status === status);
              if (rows.length === 0) return null;
              return <DiffGroup key={status} status={status} rows={rows} afterRun={runId} beforeRun={against} />;
            })}

            {listedRows === 0 && (
              <Card>
                <EmptyState
                  icon={<CheckCircle size={36} />}
                  title="Nothing moved between these runs"
                  description="Every comparison the two runs share carries the same classification and the same discrepancies. Nothing was resolved and nothing is new."
                />
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function DiffGroup({ status, rows, afterRun, beforeRun }: { status: DiffStatus; rows: RunDiffRow[]; afterRun: string; beforeRun: string }) {
  return (
    <Card>
      <CardHead title={STATUS_LABEL[status]} count={`${rows.length} row${rows.length === 1 ? "" : "s"}`} description={STATUS_MEANING[status]} />
      <div className="overflow-x-auto">
        <table className="tbl">
          <thead>
            <tr>
              <th>SKU</th>
              <th>Check</th>
              <th>Item</th>
              <th>Before</th>
              <th>After</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td className="mono whitespace-nowrap">{r.sku}</td>
                <td className="whitespace-nowrap text-ink-2" title={r.check}>
                  {CHECK_LABEL[r.check] ?? r.check}
                </td>
                <td className="min-w-[14rem]">{(r.after ?? r.before)?.a?.[1] ?? (r.after ?? r.before)?.b?.[0] ?? <span className="mono text-ink-3">{r.key}</span>}</td>
                <td>
                  <Side b={r.before} run={beforeRun} label="Open in the earlier run" />
                </td>
                <td>
                  <Side b={r.after} run={afterRun} label="Open in this run" />
                </td>
                <td className="text-ink-2 min-w-[16rem]">{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Side({ b, run, label }: { b: RunDiffRow["before"]; run: string; label: string }) {
  if (!b) return <span className="text-ink-4">—</span>;
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <ClassificationBadge value={b.classification} />
        <Link className="text-xs whitespace-nowrap" to={`/runs/${enc(run)}/rows/${enc(b.row_id)}`} title={label}>
          Open row
        </Link>
      </div>
      {b.discrepancies.length > 0 && <div className="mono text-xs text-ink-2">{b.discrepancies.join(", ")}</div>}
    </div>
  );
}
