// Action items: the findings a reviewer raised, tracked until a later run clears them.
import { ArrowsClockwise, Check, ClipboardText, X } from "@phosphor-icons/react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { SeverityBadge, StatusBadge } from "../components/Badges";
import { ErrorBox } from "../components/Feedback";
import { Button, Card, CardHead, EmptyState, Field, PageHeader, TableSkeleton } from "../components/ui";
import { enc, fmtDate } from "../lib/format";
import { useReviewer } from "../lib/reviewer";
import { useToast } from "../lib/toast";
import { errorMessage, useAsync } from "../lib/useAsync";
import { ACTION_STATUSES, type ActionItem, type ActionStatus } from "../types";

const STATUS_LABEL: Record<ActionStatus, string> = { OPEN: "Open", IN_PROGRESS: "In progress", RESOLVED: "Resolved", CLOSED: "Closed", REJECTED: "Rejected" };
const CHECK_LABEL: Record<string, string> = { BOM_LABEL: "BOM to label", BOM_DRAWING: "BOM to drawing", LABEL_DRAWING: "Label to drawing", PCO_BOM: "PCO to BOM", LABEL_REVISION: "Label revision" };

export default function ActionItemsPage() {
  const [sp, setSp] = useSearchParams();
  const status = sp.get("status") ?? "";
  const runFilter = sp.get("run_id") ?? "";
  const highlight = sp.get("id");
  const list = useAsync(() => api.listActionItems({ status: status || undefined, run_id: runFilter || undefined }), [status, runFilter]);
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
    if (v) n.set(k, v);
    else n.delete(k);
    setSp(n, { replace: true });
  };
  const filtered = Boolean(status || runFilter);
  const clearFilters = () => {
    const n = new URLSearchParams(sp);
    n.delete("status");
    n.delete("run_id");
    setSp(n, { replace: true });
  };

  return (
    <div>
      <PageHeader
        title="Action items"
        description="Findings raised from confirmed discrepancies. Each one carries an owner and a status, and Verify and close on a later run's dashboard resolves the ones whose discrepancy is gone."
        actions={
          <Button variant="ghost" onClick={list.reload} icon={<ArrowsClockwise size={16} />}>
            Refresh
          </Button>
        }
      />

      <div className="space-y-5 stagger">
        {list.error && <ErrorBox error={list.error} onRetry={list.reload} />}

        <Card>
          <CardHead title="Findings" count={list.data ? `${list.data.length} item${list.data.length === 1 ? "" : "s"}${filtered ? " matching" : ""}` : undefined} description="Change a status or an owner here; the change is recorded against your reviewer name." />

          <div className="flex flex-wrap items-end gap-3 px-4 py-3 border-b border-line bg-surface-2/60">
            <Field label="Status" htmlFor="ai-status">
              <select id="ai-status" className="input w-44" value={status} onChange={(e) => set("status", e.target.value)}>
                <option value="">Every status</option>
                {ACTION_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {STATUS_LABEL[s]}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Run" htmlFor="ai-run">
              <input id="ai-run" className="input mono w-56" placeholder="Run id" value={runFilter} onChange={(e) => set("run_id", e.target.value)} />
            </Field>
            {filtered && (
              <Button variant="ghost" onClick={clearFilters} icon={<X size={16} />}>
                Clear filters
              </Button>
            )}
            {highlight && (
              <div className="flex items-center gap-1.5">
                <span className="chip">
                  Highlighting <span className="mono">{highlight}</span>
                </span>
                <Button size="sm" variant="ghost" onClick={() => set("id", "")}>
                  Clear highlight
                </Button>
              </div>
            )}
          </div>

          {list.loading && !list.data && <TableSkeleton rows={6} cols={7} />}

          {list.data &&
            (list.data.length === 0 ? (
              <EmptyState
                icon={<ClipboardText size={36} />}
                title={filtered ? "No action items match these filters" : "No action items yet"}
                description={
                  filtered
                    ? "Nothing in this workspace matches the status and run you chose. Clear the filters to see every action item."
                    : "Action items are created from a row's evidence view: open a comparison, confirm the discrepancy, then raise the action item. It appears here with an owner and a status until a later run clears it."
                }
                action={
                  filtered ? (
                    <Button onClick={clearFilters} icon={<X size={16} />}>
                      Clear filters
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th>Status</th>
                      <th>Severity</th>
                      <th>SKU</th>
                      <th>Discrepancy</th>
                      <th>Recommended action</th>
                      <th>Owner</th>
                      <th>Row</th>
                      <th>Resolved in</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.data.map((a) => (
                      <Row key={a.id} a={a} highlighted={a.id === highlight} onChanged={(n) => list.setData(list.data!.map((x) => (x.id === n.id ? n : x)))} />
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
        </Card>
      </div>
    </div>
  );
}

function Row({ a, highlighted, onChanged }: { a: ActionItem; highlighted: boolean; onChanged: (a: ActionItem) => void }) {
  const { name } = useReviewer();
  const toast = useToast();
  const [owner, setOwner] = useState(a.owner);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const patch = async (body: { status?: ActionStatus; owner?: string }, done: string) => {
    setBusy(true);
    setErr(null);
    try {
      onChanged(await api.patchActionItem(a.id, { ...body, by: name || "reviewer" }));
      toast({ tone: "ok", title: "Action item updated", description: `${a.id} · ${done}` });
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <tr className={highlighted ? "selected" : ""}>
      <td className="whitespace-nowrap">
        <div className="mono font-medium text-ink">{a.id}</div>
        <div className="text-xs text-ink-3 mt-0.5">raised by {a.reviewer || "—"}</div>
        <div className="text-xs text-ink-3">updated {fmtDate(a.updated_at)}</div>
      </td>
      <td className="min-w-[9rem]">
        <StatusBadge value={a.status} />
        <select
          className="input input-sm w-full mt-1.5"
          value={a.status}
          disabled={busy}
          aria-label={`Status for ${a.id}`}
          onChange={(e) => {
            const next = e.target.value as ActionStatus;
            void patch({ status: next }, `status set to ${STATUS_LABEL[next].toLowerCase()}`);
          }}
        >
          {ACTION_STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </select>
        {err && <div className="text-xs text-bad-strong mt-1">{err}</div>}
      </td>
      <td>
        <SeverityBadge value={a.severity} />
      </td>
      <td className="mono whitespace-nowrap">{a.sku}</td>
      <td className="min-w-[13rem]">
        <div className="text-ink">{a.detail}</div>
        <div className="text-xs text-ink-3 mt-0.5">
          {CHECK_LABEL[a.check_type] ?? a.check_type} · <span className="mono">{a.discrepancy_type}</span>
        </div>
      </td>
      <td className="min-w-[11rem] text-ink-2">{a.recommended_action || "—"}</td>
      <td>
        <div className="flex items-center gap-1.5">
          <input className="input input-sm w-28" value={owner} disabled={busy} placeholder="Unassigned" aria-label={`Owner for ${a.id}`} onChange={(e) => setOwner(e.target.value)} />
          <Button size="sm" disabled={busy || owner === a.owner} onClick={() => void patch({ owner }, owner ? `owner set to ${owner}` : "owner cleared")} icon={<Check size={16} />}>
            Save
          </Button>
        </div>
      </td>
      <td className="whitespace-nowrap">
        <Link className="mono" to={`/runs/${enc(a.run_id)}/rows/${enc(a.row_id)}?nv=0`}>
          {a.row_id}
        </Link>
        <div className="text-xs mt-0.5">
          <Link className="mono text-ink-3" to={`/runs/${enc(a.run_id)}`}>
            {a.run_id}
          </Link>
        </div>
      </td>
      <td className="whitespace-nowrap">
        {a.resolved_in_run ? (
          <>
            <Link className="mono text-ok-strong" to={`/runs/${enc(a.resolved_in_run)}`}>
              {a.resolved_in_run}
            </Link>
            <div className="text-xs text-ink-3 mt-0.5">{fmtDate(a.resolved_at)}</div>
          </>
        ) : (
          <span className="text-ink-4">—</span>
        )}
      </td>
    </tr>
  );
}
