// Worklist and mining: the ranked to-do list of wording pairings, then the engine's raw suggestions.
// Visual rules: docs/design/DESIGN.md. Routes, API calls and behaviour are unchanged.
import { ArrowsClockwise, ArrowsLeftRight, Check, CheckCircle, Eye, Lightbulb, ListChecks, Prohibit } from "@phosphor-icons/react";
import { useId, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge } from "../components/Badges";
import { ErrorBox, Notice } from "../components/Feedback";
import { Bar, CLASS_COLORS, MiniBar } from "../components/Stat";
import { Button, Card, CardHead, Divider, EmptyState, Field, LinkButton, PageHeader, SectionTitle, TableSkeleton } from "../components/ui";
import { enc, familyOf } from "../lib/format";
import { useReviewer } from "../lib/reviewer";
import { useToast } from "../lib/toast";
import { errorMessage, useAsync } from "../lib/useAsync";
import type { MiningSuggestion, Relationship, Worklist, WorklistItem } from "../types";

const CHECK_LABEL: Record<string, string> = { BOM_LABEL: "BOM to label", BOM_DRAWING: "BOM to drawing", LABEL_DRAWING: "Label to drawing", PCO_BOM: "PCO to BOM", LABEL_REVISION: "Label revision" };
/** Which document each side of a pairing came from, when every check in the pair agrees. */
const SIDES: Record<string, [string, string]> = {
  BOM_LABEL: ["BOM", "Label"],
  BOM_DRAWING: ["BOM", "Drawing"],
  LABEL_DRAWING: ["Label", "Drawing"],
  PCO_BOM: ["PCO", "BOM"],
  LABEL_REVISION: ["Label", "Previous label"],
};
function sideLabels(checks: string[]): [string, string] {
  const uniq = [...new Set(checks)];
  const s = uniq.length === 1 ? SIDES[uniq[0]] : undefined;
  return s ? [`${s[0]} wording`, `${s[1]} wording`] : ["First wording", "Second wording"];
}

/** A pressable option. Buttons carry the button vocabulary; the pressed state is announced. */
function Toggle({ on, onClick, children, title, disabled }: { on: boolean; onClick: () => void; children: ReactNode; title?: string; disabled?: boolean }) {
  return (
    <Button size="sm" aria-pressed={on} disabled={disabled} title={title} onClick={onClick} className={on ? "!bg-brand-100 !border-brand-600 !text-brand-700" : ""}>
      {on && <Check size={14} aria-hidden />}
      {children}
    </Button>
  );
}

export default function MiningPage() {
  const { runId = "" } = useParams();
  const [minSkus, setMinSkus] = useState(2);
  const list = useAsync(() => api.getMining(runId, minSkus), [runId, minSkus]);
  const worklist = useAsync(() => api.getWorklist(runId), [runId]);
  const reloadAll = () => {
    list.reload();
    worklist.reload();
  };
  const minId = useId();

  return (
    <div>
      <PageHeader
        back={{ to: `/runs/${enc(runId)}`, label: "Overview" }}
        title="Suggested matches"
        description="Review similar terms found across SKUs and save confirmed matches to terminology."
      />

      <div className="space-y-5 stagger">
        {worklist.error && <ErrorBox error={worklist.error} onRetry={worklist.reload} />}
        {worklist.loading && !worklist.data && (
          <Card>
            <CardHead icon={<ListChecks size={18} />} title="Matches to review" />
            <TableSkeleton rows={5} cols={7} />
          </Card>
        )}
        {worklist.data && <WorklistSection runId={runId} wl={worklist.data} onDone={reloadAll} />}

        <div>
          <SectionTitle
            count={list.data ? `${list.data.length} suggestion${list.data.length === 1 ? "" : "s"}` : undefined}
            actions={
              <label className="flex items-center gap-2 text-xs text-ink-2" htmlFor={minId}>
                <span>Seen in at least</span>
                <input
                  id={minId}
                  type="number"
                  min={1}
                  className="input input-sm w-16 num"
                  value={minSkus}
                  onChange={(e) => setMinSkus(Math.max(1, Number(e.target.value) || 1))}
                  aria-label="Minimum number of SKUs a pairing must appear in"
                />
                <span>SKUs</span>
              </label>
            }
          >
            Repeated matches
          </SectionTitle>

          <div className="space-y-4">
            <Notice>
              Approve a match to save it as terminology for future runs. Rejected pairs won’t be suggested again.
            </Notice>
            {list.error && <ErrorBox error={list.error} onRetry={list.reload} />}
            {list.loading && !list.data && (
              <Card>
                <TableSkeleton rows={4} cols={4} />
              </Card>
            )}
            {list.data && list.data.length === 0 && (
              <Card>
                <EmptyState
                  icon={<Lightbulb size={36} />}
                  title="No suggestions at this threshold"
                  description="Lower the minimum SKU count to see more suggestions."
                />
              </Card>
            )}
            {list.data && list.data.length > 0 && (
              <div className="space-y-4 stagger">
                {list.data.map((s) => (
                  <SuggestionCard key={s.pair_key} runId={runId} s={s} onDone={reloadAll} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** The business-case projection as a to-do list: approve these, in this order, and this many rows clear. */
function WorklistSection({ runId, wl, onDone }: { runId: string; wl: Worklist; onDone: () => void }) {
  const { name, session } = useReviewer();
  const accessRun = useAsync(() => api.getRun(runId), [runId]);
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const items = showAll ? wl.items : wl.items.slice(0, 10);
  const maxClear = wl.items.reduce((m, x) => Math.max(m, x.would_clear), 0);
  const remaining = Math.max(0, wl.needs_validation - wl.top5.rows);

  const approve = async (it: WorklistItem) => {
    setBusy(it.pair_key);
    setErr(null);
    try {
      const rel = await api.approveMining(runId, { a_key: it.a_key, b_key: it.b_key, by: name, scope: "global", anchor: it.item_anchors.length > 0, notes: "Approved from the terminology worklist" });
      toast({ tone: "ok", title: `Relationship ${rel.id} created`, description: `${it.would_clear} row${it.would_clear === 1 ? "" : "s"} clear on the next run.` });
      onDone();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardHead
        icon={<ListChecks size={18} />}
        title="Matches to review"
        count={wl.items.length > 0 ? `${wl.items.length} pairing${wl.items.length === 1 ? "" : "s"}` : undefined}
        description={
          <>
            <span className="num">{wl.needs_validation}</span> comparisons need review in this run; <span className="num">{wl.potential_rows}</span> have suggested terminology matches.
          </>
        }
      />
      {wl.items.length === 0 ? (
        <EmptyState
          icon={<CheckCircle size={36} />}
          title="No matches to approve"
          description="Check the review queue for any remaining discrepancies."
          action={
            <LinkButton variant="primary" to={`/runs/${enc(runId)}/review`}>
              Review comparisons
            </LinkButton>
          }
        />
      ) : (
        <>
          <div className="px-4 py-4 border-b border-line">
            <p className="text-lg text-ink max-w-[70ch]">
              Confirming the top <span className="num font-semibold">{wl.top5.n}</span> matches could clear <span className="num font-semibold">{wl.top5.rows}</span> comparisons in future runs (<span className="num font-semibold">{wl.top5.pct}%</span> of the current review queue).
            </p>
            <p className="text-sm text-ink-3 mt-1.5 max-w-[80ch]">
              The top {wl.top10.n} matches cover {wl.top10.rows} comparisons ({wl.top10.pct}%). Comparisons with discrepancies or ambiguous matches still need review.
            </p>
            <div className="mt-3 max-w-[46rem]">
              <Bar
                height={12}
                segments={[
                  { label: `Clears with the top ${wl.top5.n}`, value: wl.top5.rows, color: CLASS_COLORS.EQUIVALENT },
                  { label: "Still needs review", value: remaining, color: CLASS_COLORS.MISMATCH },
                ]}
              />
            </div>
            {!name && (
              <div className="mt-3">
                <Notice kind="warn">Sign in at the top bar to approve pairings: every relationship records who created it.</Notice>
              </div>
            )}
            {err && (
              <div className="mt-3">
                <ErrorBox error={err} />
              </div>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="text-right">Rank</th>
                  <th>BOM wording</th>
                  <th>Label or drawing wording</th>
                  <th className="text-right">SKUs</th>
                  <th className="text-right">Would clear</th>
                  <th className="text-right">Still review</th>
                  <th className="text-right">Cumulative</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((it, i) => (
                  <tr key={it.pair_key}>
                    <td className="text-right num text-ink-3">{i + 1}</td>
                    <td className="min-w-[12rem] font-medium text-ink">{it.a_text}</td>
                    <td className="min-w-[12rem] font-medium text-ink">{it.b_text}</td>
                    <td className="text-right num">{it.sku_count}</td>
                    <td>
                      <div className="flex items-center justify-end gap-2" title="Rows that clear as an equivalent match once this pairing is approved">
                        <MiniBar value={it.would_clear} max={maxClear} width={64} color={CLASS_COLORS.EQUIVALENT} />
                        <span className="num font-semibold text-ink">{it.would_clear}</span>
                      </div>
                    </td>
                    <td className="text-right num text-ink-2">{it.still_review || <span className="text-ink-4">—</span>}</td>
                    <td className="text-right num whitespace-nowrap">
                      {it.cumulative_clear} <span className="text-ink-3">({it.cumulative_pct}%)</span>
                    </td>
                    <td className="text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-1.5">
                        <LinkButton size="sm" variant="ghost" icon={<Eye size={16} />} to={`/runs/${enc(runId)}/rows/${enc(it.row_ids[0])}`} title="Open the first row with its evidence">
                          Evidence
                        </LinkButton>
                        <Button
                          size="sm"
                         
                          loading={busy === it.pair_key}
                          disabled={busy !== null || !name || !session?.is_admin || accessRun.data?.permission === "view"}
                          onClick={() => approve(it)}
                          title="Creates a global relationship, versioned and attributed to you"
                        >
                          Approve
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {wl.items.length > 10 && (
            <div className="px-4 py-3 border-t border-line">
              <Button size="sm" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Show top 10" : `Show all ${wl.items.length}`}
              </Button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function SuggestionCard({ runId, s, onDone }: { runId: string; s: MiningSuggestion; onDone: () => void }) {
  const { name, session } = useReviewer();
  const accessRun = useAsync(() => api.getRun(runId), [runId]);
  const toast = useToast();
  const uid = useId();
  const families = [...new Set(s.skus.map(familyOf))];
  const [scope, setScope] = useState("global");
  const [anchor, setAnchor] = useState(s.item_anchors.length > 0);
  const [notes, setNotes] = useState("");
  const [rejectNote, setRejectNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [created, setCreated] = useState<Relationship | null>(null);
  const [rejected, setRejected] = useState(false);

  const approve = async () => {
    setBusy("approve");
    setErr(null);
    try {
      const rel = await api.approveMining(runId, { a_key: s.a_key, b_key: s.b_key, by: name, scope, anchor, notes: notes.trim() || undefined });
      setCreated(rel);
      toast({ tone: "ok", title: `Relationship ${rel.id} created`, description: `Scope ${rel.scope}. The next run will use it.` });
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  const reject = async () => {
    setBusy("reject");
    setErr(null);
    try {
      await api.rejectMining(runId, { a_key: s.a_key, b_key: s.b_key, by: name, note: rejectNote.trim() || undefined });
      setRejected(true);
      toast({ tone: "info", title: "Pairing rejected", description: "It will not be suggested again." });
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const contradicted = s.contradicted > 0;
  const [labelA, labelB] = sideLabels(s.check_types);

  return (
    <Card className={rejected ? "opacity-70" : ""}>
      <div className="grid lg:grid-cols-[minmax(0,1fr)_21rem] divide-y lg:divide-y-0 lg:divide-x divide-line">
        <div className="p-4 min-w-0 space-y-3">
          <div className="grid sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2">
            <div className="min-w-0">
              <div className="label">{labelA}</div>
              <div className="text-md font-semibold text-ink break-words">{s.a_text}</div>
            </div>
            <ArrowsLeftRight size={16} className="hidden sm:block text-ink-3 shrink-0 justify-self-center mt-6" aria-hidden />
            <div className="min-w-0">
              <div className="label">{labelB}</div>
              <div className="text-md font-semibold text-ink break-words">{s.b_text}</div>
            </div>
          </div>

          <p className="text-sm text-ink-2">{s.evidence}</p>

          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone="info">
              {s.sku_count} SKU{s.sku_count === 1 ? "" : "s"}
            </Badge>
            <Badge tone={s.confirmed ? "ok" : "neutral"}>{s.confirmed} confirmed</Badge>
            <Badge tone={contradicted ? "bad" : "neutral"}>{s.contradicted} contradicted</Badge>
            {s.check_types.map((c) => (
              <span key={c} className="chip">
                {CHECK_LABEL[c] ?? c}
              </span>
            ))}
            {s.relationship_id && (
              <Link className="no-underline" to={`/terminology?id=${enc(s.relationship_id)}`}>
                <Badge tone="ok">
                  Already covered by <span className="mono">{s.relationship_id}</span>
                </Badge>
              </Link>
            )}
          </div>

          <dl className="kv">
            <dt>SKUs</dt>
            <dd className="mono">{s.skus.join(", ")}</dd>
            {s.item_anchors.length > 0 && (
              <>
                <dt>BOM item numbers</dt>
                <dd className="mono">{s.item_anchors.join(", ")}</dd>
              </>
            )}
            <dt>Rows</dt>
            <dd className="flex flex-wrap gap-x-2 gap-y-1">
              {s.row_ids.slice(0, 8).map((id) => (
                <Link key={id} className="mono" to={`/runs/${enc(runId)}/rows/${enc(id)}?nv=0`}>
                  {id}
                </Link>
              ))}
              {s.row_ids.length > 8 && <span className="text-ink-3">plus {s.row_ids.length - 8} more</span>}
            </dd>
          </dl>
        </div>

        <div className="p-4 space-y-3">
          {created ? (
            <Notice kind="good">
              Approved as{" "}
              <Link className="mono" to={`/terminology?id=${enc(created.id)}`}>
                {created.id}
              </Link>{" "}
              with scope <span className="mono">{created.scope}</span>. The next run will use it.
            </Notice>
          ) : rejected ? (
            <Notice>Rejected. This pair will not be suggested again.</Notice>
          ) : (
            <>
              <div className="space-y-3">
                <Field label="Scope" hint="Where the new rule applies." htmlFor={`${uid}-scope`}>
                  <select id={`${uid}-scope`} className="input w-full" value={scope} onChange={(e) => setScope(e.target.value)}>
                    <option value="global">Global — every SKU</option>
                    {families.map((f) => (
                      <option key={f} value={`family:${f}`}>
                        Family {f}
                      </option>
                    ))}
                    {s.skus.map((k) => (
                      <option key={k} value={`sku:${k}`}>
                        SKU {k}
                      </option>
                    ))}
                  </select>
                </Field>
                <div>
                  <div className="label">Item anchor</div>
                  <Toggle on={anchor} disabled={!s.item_anchors.length} onClick={() => setAnchor((v) => !v)}>
                    Anchor to item number
                  </Toggle>
                  <p className="hint mt-1">
                    {s.item_anchors.length ? `The rule applies only to BOM item ${s.item_anchors.join(", ")}.` : "These rows share no BOM item number, so the rule cannot be anchored."}
                  </p>
                </div>
                <Field label="Notes" hint="Why this pairing is right." htmlFor={`${uid}-notes`}>
                  <input id={`${uid}-notes`} className="input w-full" value={notes} onChange={(e) => setNotes(e.target.value)} />
                </Field>
                <Button variant="primary" className="w-full" icon={<CheckCircle size={16} />} loading={busy === "approve"} disabled={busy !== null || !name || !session?.is_admin || accessRun.data?.permission === "view"} onClick={approve}>
                  Approve pairing
                </Button>
              </div>

              <Divider />

              <div className="space-y-3">
                <Field label="Reject note" hint="Why these two are not the same thing." htmlFor={`${uid}-reject`}>
                  <input id={`${uid}-reject`} className="input w-full" value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} />
                </Field>
                <Button variant="danger" className="w-full" icon={<Prohibit size={16} />} loading={busy === "reject"} disabled={busy !== null || !name || !session?.is_admin || accessRun.data?.permission === "view"} onClick={reject}>
                  Reject pairing
                </Button>
              </div>

              {!name && <Notice kind="warn">Sign in at the top bar to approve or reject.</Notice>}
            </>
          )}
          {err && <ErrorBox error={err} />}
          {(created || rejected) && (
            <Button size="sm" icon={<ArrowsClockwise size={16} />} onClick={onDone}>
              Refresh suggestions
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
