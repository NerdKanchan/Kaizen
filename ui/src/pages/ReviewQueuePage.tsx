import { CaretLeft, CaretRight, CheckSquare, EyeSlash, ListChecks, MagnifyingGlass, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Badge, ClassificationBadge, RoleTag, SeverityBadge, StateBadge } from "../components/Badges";
import { ConfirmDialog, ErrorBox, Loading } from "../components/Feedback";
import { HotkeyHelp, HotkeyHint } from "../components/HotkeyHelp";
import { ImportDecisions } from "../components/ImportDecisions";
import { Button, Card, EmptyState, PageHeader, TableSkeleton } from "../components/ui";
import { displayName, enc, fmtQty, issueLabel } from "../lib/format";
import { useHotkeys } from "../lib/hotkeys";
import { PAGE_SIZE, queueParams, queueQueryFromParams } from "../lib/queue";
import { useReviewer } from "../lib/reviewer";
import { useToast } from "../lib/toast";
import { errorMessage, useAsync } from "../lib/useAsync";
import { useDataRefresh } from "../lib/dataRefresh";
import { CHECK_TYPES, CLASSIFICATIONS, DISCREPANCY_TYPES, REVIEW_STATES, ROLES, SEVERITIES, type ResultRow, type SideSummary } from "../types";

const CHECK_LABEL: Record<string, string> = { BOM_LABEL: "BOM to label", BOM_DRAWING: "BOM to drawing", LABEL_DRAWING: "Label to drawing", PCO_BOM: "PCO to BOM", LABEL_REVISION: "Label revision" };
const STATE_LABEL: Record<string, string> = { REVIEWED: "Reviewed", ENGINE_RECOMMENDED: "Not reviewed", REVIEWER_1_COMPLETE: "Reviewer 1 done", REVIEWER_2_COMPLETE: "Reviewer 2 done", AGREED: "Agreed", DISAGREEMENT: "Disagreement", FINALIZED: "Approved" };
const title = (s: string) => s.charAt(0) + s.slice(1).toLowerCase();

export default function ReviewQueuePage() {
  const { runId = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const toast = useToast();
  const { viewerParams, name } = useReviewer();
  const run = useAsync(() => api.getRun(runId), [runId]);
  const query = queueQueryFromParams(sp, viewerParams);
  const page = useAsync(() => api.getResults(runId, query), [runId, sp.toString(), viewerParams.viewer, viewerParams.blind]);
  useDataRefresh(() => { run.reload(); page.reload(); }, runId);

  const [search, setSearch] = useState(sp.get("q") ?? "");
  useEffect(() => setSearch(sp.get("q") ?? ""), [sp]);

  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
    if (v) n.set(k, v);
    else n.delete(k);
    if (k !== "offset") n.delete("offset");
    setSp(n, { replace: true });
  };
  const clear = () => setSp(new URLSearchParams(), { replace: true });
  const open = (rowId: string) => nav(`/runs/${enc(runId)}/rows/${enc(rowId)}?${queueParams(sp).toString()}`);
  const activeFilters = ["sku", "check", "discrepancy", "severity", "classification", "engine_classification", "unresolved", "state", "role", "q"].filter((k) => sp.get(k)).length + (sp.get("nv") === "0" ? 1 : 0);

  // ---- keyboard: j/k highlight a row, Enter opens it, ? help (no animation on keyboard moves)
  const rows = page.data?.rows ?? [];
  const [hi, setHi] = useState<number | null>(null);
  const [help, setHelp] = useState(false);
  useEffect(() => setHi(null), [page.data]);
  useEffect(() => {
    document.querySelector('[data-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [hi]);
  useHotkeys(
    {
      j: () => rows.length && setHi((cur) => (cur === null ? 0 : Math.min(cur + 1, rows.length - 1))),
      k: () => rows.length && setHi((cur) => (cur === null ? 0 : Math.max(cur - 1, 0))),
      Enter: () => {
        if (hi === null) return;
        const r = rows[hi];
        if (r) open(r.row_id);
      },
      "?": () => setHelp((v) => !v),
      Escape: () => setHelp(false),
    },
    [rows, hi, runId, sp.toString()],
  );

  // ---- bulk accept
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkCount, setBulkCount] = useState<number | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkErr, setBulkErr] = useState<string | null>(null);
  const openBulk = async () => {
    setBulkOpen(true);
    setBulkCount(null);
    setBulkErr(null);
    try {
      const result = await api.getResults(runId, { needs_validation: false, state: "ENGINE_RECOMMENDED", limit: 1 });
      setBulkCount(result.total);
    } catch (e) {
      setBulkErr(errorMessage(e));
    }
  };
  const doBulk = async () => {
    setBulkBusy(true);
    setBulkErr(null);
    try {
      const res = await api.bulkAccept(runId);
      toast({ tone: "ok", title: `Accepted ${res.accepted} clean row${res.accepted === 1 ? "" : "s"} as ${name}`, description: "Each carries the comment “bulk accept: exact/equivalent with no discrepancy”." });
      setBulkOpen(false);
      page.reload();
      run.reload();
    } catch (e) {
      setBulkErr(errorMessage(e));
    } finally {
      setBulkBusy(false);
    }
  };

  const offset = query.offset ?? 0;
  const total = page.data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);
  const nvOn = sp.get("nv") !== "0";

  const sel = (k: string, label: string, options: readonly string[], render?: (v: string) => string) => (
    <label className="flex flex-col gap-1 text-xs text-ink-2">
      {label}
      <select className="input input-sm min-w-[8.5rem]" value={sp.get(k) ?? ""} onChange={(e) => set(k, e.target.value)}>
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {render ? render(o) : o}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div>
      <HotkeyHelp open={help} onClose={() => setHelp(false)} />
      <PageHeader
        back={{ to: `/runs/${enc(runId)}`, label: "Overview" }}
        title="Review queue"
        description="Open a comparison to review the documents and save a decision."
        meta={<HotkeyHint />}
        actions={
          <>
            {run.data?.permission !== "view" && <ImportDecisions
              runId={runId}
              onApplied={() => {
                page.reload();
                run.reload();
              }}
            />}
            <Button onClick={openBulk} disabled={!name || run.data?.permission === "view"} icon={<CheckSquare size={16} />} title={name ? "" : "Sign in first"}>
              Accept all clean rows
            </Button>
          </>
        }
      />

      <div className="space-y-4">
        <Card className="px-4 py-3">
          <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
            {sel("sku", "SKU", (run.data?.groups ?? []).map((g) => g.sku))}
            {sel("check", "Check", CHECK_TYPES, (c) => CHECK_LABEL[c] ?? c)}
            {sel("state", "Review status", REVIEW_STATES, (s) => STATE_LABEL[s] ?? s)}
            <form
              className="flex items-end gap-1.5 max-w-full"
              onSubmit={(e) => {
                e.preventDefault();
                set("q", search.trim());
              }}
            >
              <label className="flex flex-col gap-1 text-xs text-ink-2">
                Search
                <span className="relative">
                  <MagnifyingGlass size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
                  <input className="input input-sm pl-8 w-full" placeholder="Item, description, explanation" value={search} onChange={(e) => setSearch(e.target.value)} />
                </span>
              </label>
              <Button size="sm" type="submit">
                Search
              </Button>
            </form>
            <label className="flex items-center gap-2 text-sm h-8 select-none" title="Show rows awaiting review, approval or more information.">
              <input type="checkbox" className="accent-accent-500 w-4 h-4" checked={nvOn} onChange={(e) => set("nv", e.target.checked ? "" : "0")} />
              Pending only
            </label>
            {activeFilters > 0 && (
              <Button size="sm" variant="ghost" onClick={clear} icon={<X size={14} />}>
                Clear {activeFilters} filter{activeFilters === 1 ? "" : "s"}
              </Button>
            )}
            {sp.get("engine_classification") && <Button size="sm" variant="ghost" onClick={() => set("engine_classification", "")} icon={<X size={14} />}>Engine: {sp.get("engine_classification")}</Button>}
            {sp.get("unresolved") === "1" && <Button size="sm" variant="ghost" onClick={() => set("unresolved", "")} icon={<X size={14} />}>Unresolved findings</Button>}
            {viewerParams.blind && (
              <Badge tone="info" dot={false} className="ml-auto">
                <EyeSlash size={14} /> Blind: reviewer 1 decisions hidden until you decide
              </Badge>
            )}
          </div>
          <details className="queue-more-filters" open={["discrepancy", "severity", "classification", "role"].some(k => sp.get(k)) || undefined}>
            <summary>More filters{["discrepancy", "severity", "classification", "role"].some(k => sp.get(k)) ? " · active" : ""}</summary>
            <div className="flex flex-wrap gap-3 pt-3">            {sel("discrepancy", "Discrepancy", DISCREPANCY_TYPES, issueLabel)}
            {sel("severity", "Severity", SEVERITIES, title)}
            {sel("classification", "Classification", CLASSIFICATIONS, title)}
            {sel("role", "Role", ROLES, title)}
</div>
          </details>
        </Card>

        {page.error && <ErrorBox error={page.error} onRetry={page.reload} />}

        <Card>
          <div className="flex items-center gap-3 px-4 py-2.5 border-b border-line text-sm">
            <span className="text-ink-2">
              {page.data ? (
                <>
                  Showing <b className="num">{from}–{to}</b> of <b className="num">{total}</b> comparison{total === 1 ? "" : "s"}
                </>
              ) : (
                "Loading queue"
              )}
              {page.loading && page.data && <span className="text-ink-3"> · refreshing</span>}
            </span>
            <div className="ml-auto flex items-center gap-1">
              <Button size="sm" variant="ghost" iconOnly aria-label={`Previous ${PAGE_SIZE}`} disabled={offset === 0} onClick={() => set("offset", String(Math.max(0, offset - PAGE_SIZE)))} icon={<CaretLeft size={16} />} />
              <Button size="sm" variant="ghost" iconOnly aria-label={`Next ${PAGE_SIZE}`} disabled={to >= total} onClick={() => set("offset", String(offset + PAGE_SIZE))} icon={<CaretRight size={16} />} />
            </div>
          </div>
          {page.loading && !page.data && <TableSkeleton rows={8} cols={7} />}
          {page.data && page.data.rows.length === 0 && (
            <EmptyState icon={<ListChecks size={36} />} title="No rows match these filters" description={nvOn ? "No pending reviews match these filters. Turn off “Pending only” to see approved and automatically cleared rows." : "Try fewer filters."} action={activeFilters > 0 ? <Button onClick={clear}>Clear filters</Button> : undefined} />
          )}
          {page.data && page.data.rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>SKU · check</th>
                    <th>Side A</th>
                    <th>Side B</th>
                    <th>Result</th>
                    <th>Discrepancies</th>
                    <th>Review</th>
                  </tr>
                </thead>
                <tbody>
                  {page.data.rows.map((row, i) => (
                    <tr key={row.row_id} className="clickable" data-selected={hi === i ? "true" : undefined} onClick={() => open(row.row_id)}>
                      <td>
                        <SeverityBadge value={row.current_severity} />
                      </td>
                      <td className="whitespace-nowrap">
                        <Link className="mono font-medium underline" to={`/runs/${enc(runId)}/rows/${enc(row.row_id)}?${queueParams(sp).toString()}`} onClick={e => e.stopPropagation()} aria-label={`Review ${row.sku} ${CHECK_LABEL[row.check] ?? row.check} comparison ${offset + i + 1}`}>{row.sku}</Link>
                        <div className="text-xs text-ink-3 mt-0.5 flex items-center gap-1.5">
                          {CHECK_LABEL[row.check] ?? row.check} <RoleTag value={row.role} />
                        </div>
                      </td>
                      <td className="min-w-[12rem]">
                        <Side s={row.a} />
                      </td>
                      <td className="min-w-[12rem]">
                        <Side s={row.b} />
                      </td>
                      <td className="whitespace-nowrap">
                        <ClassificationBadge value={row.effective_classification} title="Current review classification" />
                        {row.effective_classification !== row.engine.classification && (
                          <div className="text-xs text-ink-3 mt-1 flex items-center gap-1">
                            engine <ClassificationBadge value={row.engine.classification} />
                          </div>
                        )}
                        {row.engine.relationship_id && <div className="text-xs text-ink-3 mono mt-1">{row.engine.relationship_id}</div>}
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-1 max-w-[12rem]">
                          {row.current_discrepancies.map(({ type: t }) => (
                            <span key={t} className="chip">
                              {issueLabel(t)}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="whitespace-nowrap">
                        <StateBadge value={row.state} />
                        <div className="text-xs mt-1.5">
                          <Decisions row={row} blind={viewerParams.blind} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {bulkOpen && (
        <ConfirmDialog title="Accept all clean rows" confirmLabel={bulkCount ? `Accept ${bulkCount} rows` : "Accept"} onConfirm={doBulk} onCancel={() => setBulkOpen(false)} busy={bulkBusy || bulkCount === null}>
          <p>
            Records an <b>Accept</b> decision as <b title={name}>{displayName(name)}</b> on every row that has no discrepancy and does not need validation. Rows you already decided are skipped.
          </p>
          {bulkCount === null && !bulkErr && <Loading lines={2} />}
          {bulkCount !== null && (
            <p className="text-md">
              <b className="num">{bulkCount}</b> row{bulkCount === 1 ? "" : "s"} will be accepted.
            </p>
          )}
          {bulkErr && <ErrorBox error={bulkErr} />}
          <p className="text-ink-3 text-xs">
            Nothing is hidden by this: accepted rows stay in the run and the workbook with the engine recommendation and your decision side by side.{" "}
            <Link to={`/runs/${enc(runId)}/review?nv=0&classification=EXACT`}>Inspect the clean rows first</Link>.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}

function Side({ s }: { s: SideSummary | null }) {
  if (!s) return <span className="text-ink-4">No counterpart</span>;
  return (
    <div>
      <div className="text-sm">
        {s.item_number && <span className="mono text-ink-2 mr-1.5">{s.item_number}</span>}
        <span className="text-ink">{s.description}</span>
        {s.quantity !== null && <span className="text-ink-3 num"> × {fmtQty(s.quantity)}</span>}
      </div>
      <div className="text-xs text-ink-3 mt-0.5">
        {s.file_name}
        {s.locator ? ` · ${s.locator}` : ""}
      </div>
    </div>
  );
}

function Decisions({ row, blind }: { row: ResultRow; blind: boolean }) {
  const d1 = row.decisions["1"];
  const d2 = row.decisions["2"];
  const fmt = (d: typeof d1) => (d ? `${d.decision.replace(/_/g, " ").toLowerCase()}${d.override_classification ? ` → ${d.override_classification.toLowerCase()}` : ""} · ${d.reviewer}` : "—");
  if (!d1 && !d2 && !row.final && !blind) return null;
  return (
    <div className="space-y-0.5 text-ink-2">
      <div>
        <span className="text-ink-3 inline-block w-8">Review</span>
        {blind && !d2 && !d1 ? <span className="text-brand-600">hidden (blind)</span> : fmt(d1)}
      </div>
      {d2 && <div>
        <span className="text-ink-3 inline-block w-8">Earlier</span>
        {fmt(d2)}
      </div>}
      {row.final && (
        <div>
          <span className="text-ink-3 mr-2">{row.final.self_approved ? "Self-approved" : "Approved"}</span>
          {row.final.final_decision.replace(/_/g, " ").toLowerCase()} · {row.final.finalized_by}
        </div>
      )}
    </div>
  );
}
