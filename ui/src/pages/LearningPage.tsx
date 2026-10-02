import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { ClassificationBadge } from "../components/Badges";
import { ErrorBox, Loading } from "../components/Feedback";
import { Stat } from "../components/Stat";
import { AnchorButton, Button, Card, CardHead, Field, LinkButton, PageHeader } from "../components/ui";
import type { DrawingBody, LearningGroup, LearningMetrics } from "../learning";
import { useDataRefresh } from "../lib/dataRefresh";
import { enc, fmtDate } from "../lib/format";
import { useReviewer } from "../lib/reviewer";
import { useAsync } from "../lib/useAsync";

const percent = (n: number | null) => n === null ? "Not measured" : `${(n * 100).toFixed(1)}%`;

function DrawingReview({runId, group, canEdit, isAdmin, name, reload}: {runId: string; group: LearningGroup; canEdit: boolean; isAdmin: boolean; name: string; reload: () => void}) {
  const saved = group.drawing;
  const initial: DrawingBody = {expected_version: saved?.version ?? 0, doc_id: saved?.payload.doc_id ?? group.drawing_options[0]?.id ?? "", applicability: saved?.payload.applicability ?? "UNCONFIRMED", released_revision: saved?.payload.released_revision ?? "", release_reference: saved?.payload.release_reference ?? "", note: saved?.payload.note ?? ""};
  const [body, setBody] = useState<DrawingBody>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = JSON.stringify(body) !== JSON.stringify(initial);
  async function perform(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); reload(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <details className="border-t border-line pt-3 mt-3">
    <summary className="text-sm font-medium cursor-pointer">Drawing applicability · {saved ? `${saved.payload.applicability.toLowerCase().replace(/_/g, " ")} · ${saved.status}` : "Needs confirmation"}</summary>
    {!group.drawing_options.length ? <p className="text-sm my-3">Upload the correct released drawing with this SKU before evaluating drawing matches.</p> : <div className="space-y-3 py-4">
      <fieldset disabled={!canEdit || busy} className="space-y-3">
        <Field label="Supplied drawing"><select className="input w-full" value={body.doc_id} onChange={e => setBody({...body, doc_id: e.target.value})}>{group.drawing_options.map(d => <option key={d.id} value={d.id}>{d.number || d.file_name}{d.revision ? ` · extracted revision ${d.revision}` : ""}</option>)}</select></Field>
        <Link className="text-xs" to={`/runs/${enc(runId)}/documents/${enc(body.doc_id)}`}>Inspect drawing and title block</Link>
        <Field label="Applicability"><select className="input w-full" value={body.applicability} onChange={e => setBody({...body, applicability: e.target.value as DrawingBody["applicability"]})}><option value="UNCONFIRMED">Not yet confirmed</option><option value="CONFIRMED_RELEASED">Correct released drawing for this SKU</option><option value="NOT_APPLICABLE">This drawing does not apply</option></select></Field>
        <Field label="Verified released revision"><input className="input w-full" value={body.released_revision} onChange={e => setBody({...body, released_revision: e.target.value})} /></Field>
        <Field label="Release record reference"><input className="input w-full" value={body.release_reference} onChange={e => setBody({...body, release_reference: e.target.value})} placeholder="Approved release record / controlled document reference" /></Field>
        <Field label="Evidence and note"><textarea className="input w-full" rows={2} value={body.note} onChange={e => setBody({...body, note: e.target.value})} /></Field>
        {canEdit && <Button loading={busy} disabled={!body.note.trim() || !dirty} onClick={() => perform(() => api.learning.drawing(runId, group.sku, body))}>Save applicability</Button>}
      </fieldset>
      {saved && <p className="text-xs text-ink-3">Recorded by {saved.annotated_by}. Another administrator verifies the released revision and applicability.</p>}
      {isAdmin && canEdit && saved?.status === "pending" && saved.annotated_by !== name && <div className="flex flex-wrap gap-2">
        <Button loading={busy} disabled={dirty || saved.payload.applicability === "UNCONFIRMED"} onClick={() => perform(() => api.learning.approveDrawing(runId, group.sku, saved.version, true))}>Verify saved applicability</Button>
        <Button loading={busy} disabled={dirty} onClick={() => perform(() => api.learning.approveDrawing(runId, group.sku, saved.version, false))}>Reject</Button>
      </div>}
      {error && <ErrorBox error={error} />}
    </div>}
  </details>;
}

export default function LearningPage() {
  const {runId = ""} = useParams();
  const {session, name} = useReviewer();
  const summary = useAsync(() => api.learning.summary(runId), [runId]);
  const run = useAsync(() => api.getRun(runId), [runId]);
  useDataRefresh(summary.reload, runId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function perform(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); summary.reload(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  if (summary.error || run.error) return <ErrorBox error={summary.error || run.error || ""} onRetry={() => {summary.reload(); run.reload();}} />;
  if (!summary.data || !run.data) return <Loading label="Loading closed testing" />;
  const data = summary.data;
  const canEdit = run.data.permission !== "view";
  const isAdmin = !!session?.is_admin;
  const report = data.latest_evaluation;
  const metrics: [string, keyof LearningMetrics][] = [["Pairing accuracy", "pairing_accuracy"], ["Classification accuracy", "classification_accuracy"], ["Discrepancy precision", "discrepancy_precision"], ["Discrepancy recall", "discrepancy_recall"], ["False-clear rate", "false_clear_rate"]];
  return <div className="space-y-5">
    <PageHeader title="Closed testing" description="Turn source-backed reviewer corrections into verified examples, then measure candidate improvements alongside testing." back={{to: `/runs/${enc(runId)}`, label: "Overview"}} actions={<LinkButton to={`/runs/${enc(runId)}/mining`}>Terminology worklist</LinkButton>} />
    {error && <ErrorBox error={error} />}
    {!data.enabled ? <Card><CardHead title="Enable feedback collection" /><div className="p-5 space-y-4 text-sm">
      <p>Review decisions and timing are already recorded. Enabling closed testing adds pairing corrections, verified attributes, assembly allocations and drawing applicability. Data stays in this workspace.</p>
      <p>The first delivery with multiple SKUs reserves about 20% of whole SKUs for evaluation. Reuploads and copies keep their split. Reserved examples cannot be promoted through the terminology worklist.</p>
      {run.data.permission === "owner" ? <Button variant="primary" loading={busy} onClick={() => perform(() => api.learning.enable(runId))}>Enable closed testing</Button> : <p>The run owner enables collection.</p>}
    </div></Card> : <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Recorded review events" value={data.review_events} sub="Decisions and approvals" />
        <Stat label="Pending verification" value={data.counts.pending} sub="Independent administrator review" />
        <Stat label="Verified training examples" value={data.counts.verified_train} sub="Eligible for local rule learning" />
        <Stat label="Verified evaluation examples" value={data.counts.verified_evaluation} sub="Kept out of training" />
      </div>
      <Card><CardHead title="Tester workflow" /><div className="p-5 text-sm space-y-3">
        <ol className="list-decimal pl-5 space-y-2"><li>Open a comparison and inspect both source documents. Save the normal review decision.</li><li>Use Ground truth to identify correct or incorrect pairings, real discrepancies, or unresolved evidence. For an assembly, select its BOM members and allocate quantities per label unit.</li><li>Verify component type, dimensions, gauge, concentration and pack quantity when the source specifies them.</li><li>Have another administrator verify the annotation. Each verification rebuilds and evaluates a local candidate in the background.</li></ol>
        <p className="text-ink-3">Review both flagged and auto-cleared examples across all SKUs. An accept click or bulk accept alone does not become ground truth.</p>
      </div></Card>
      <div className="grid gap-4 lg:grid-cols-2">{data.groups.map(g => <Card key={g.sku}><CardHead title={`SKU ${g.sku}`} description={g.split === "evaluation" ? "Evaluation only · excluded from training" : "Training"} /><div className="p-5 text-sm">
        <p>{g.reviewed_rows} / {g.total_rows} reviewed · {g.annotated_rows} annotated · {g.verified_rows} eligible verified examples</p>
        <DrawingReview key={`${g.sku}:${g.drawing?.version ?? 0}:${g.drawing?.status ?? "none"}`} runId={runId} group={g} canEdit={canEdit} isAdmin={isAdmin} name={name} reload={summary.reload} />
      </div></Card>)}</div>
      <Card><CardHead title="Candidate evaluation" description="Verified training examples build a candidate; only held-out examples measure accuracy." actions={isAdmin && canEdit ? <Button loading={busy} disabled={["running", "queued"].includes(data.automatic_learning?.state ?? "")} onClick={() => perform(() => api.learning.shadow(runId))}>Rebuild and evaluate</Button> : undefined} /><div className="p-5 space-y-4">
        {["running", "queued"].includes(data.automatic_learning?.state ?? "") && <p className="text-sm">Rebuilding the candidate from the latest verified examples…</p>}
        {data.automatic_learning?.error && <ErrorBox error={data.automatic_learning.error} />}
        {report ? <>
          <p className="text-sm">{report.baseline.scored_samples} held-out samples · {report.training_samples} training samples · {fmtDate(report.created_at)}</p>
          {report.stale && <p className="text-sm text-warn-strong">The verified dataset or approved terminology has changed since this report. Rebuild to refresh the comparison.</p>}
          <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left border-b border-line"><th className="py-2">Measure</th><th>Saved baseline</th><th>Candidate</th></tr></thead><tbody>{metrics.map(([label, key]) => <tr key={key} className="border-b border-line"><td className="py-2">{label}</td><td>{percent(report.baseline[key] as number | null)}</td><td>{percent(report.candidate[key] as number | null)}</td></tr>)}<tr><td className="py-2">False clears</td><td>{report.baseline.false_clears}</td><td>{report.candidate.false_clears}</td></tr></tbody></table></div>
          <p className="text-sm font-medium">{report.gate_passed ? "Sample evaluation gate passed" : "Candidate needs more evidence or improvement"}</p>
          {!!report.gate_reasons.length && <ul className="list-disc pl-5 text-sm space-y-1">{report.gate_reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>}
          <p className="text-xs text-ink-3">{report.scope_note}</p>
        </> : <p className="text-sm">Accuracy is not measured yet. Independently verify examples to start automatic candidate evaluation.</p>}
        {isAdmin && canEdit && <div className="flex flex-wrap gap-2"><AnchorButton href={api.learning.exportUrl(runId, "train")}>Training dataset</AnchorButton><AnchorButton href={api.learning.exportUrl(runId, "evaluation")}>Evaluation dataset</AnchorButton><AnchorButton href={api.learning.observationsUrl(runId)}>Raw observations</AnchorButton></div>}
      </div></Card>
      <Card><CardHead title="Annotations to verify" count={data.labels.filter(a => !a.eligible).length} /><div className="p-5 space-y-3 text-sm">
        {data.labels.filter(a => !a.eligible).map(a => <div key={a.row_id} className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3"><div><Link to={`/runs/${enc(runId)}/rows/${enc(a.row_id)}`}>{a.payload.sku} · {a.payload.engine.check} · {a.payload.verdict.toLowerCase().replace(/_/g, " ")}</Link><p className="text-xs text-ink-3">{a.annotated_by} · {a.eligibility_note}</p></div><LinkButton size="sm" to={`/runs/${enc(runId)}/rows/${enc(a.row_id)}`}>Inspect annotation</LinkButton></div>)}
        {!data.labels.some(a => !a.eligible) && <p className="text-ink-3">No annotations awaiting verification.</p>}
      </div></Card>
      <Card><CardHead title="Next examples to verify" description="A balanced sample across SKUs, checks, flagged rows and auto-cleared rows." count={data.tasks.length} /><div className="p-5 space-y-3 text-sm">
        {data.tasks.map(t => <div key={t.row_id} className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3"><div className="min-w-0"><Link to={`/runs/${enc(runId)}/rows/${enc(t.row_id)}`}>{t.description}</Link><p className="text-xs text-ink-3">{t.sku} · {t.check} · {t.auto_cleared ? "Audit auto-cleared result" : "Review flagged result"}</p></div><ClassificationBadge value={t.classification} /></div>)}
        {!data.tasks.length && <p>Every available component row has an annotation.</p>}
      </div></Card>
    </>}
  </div>;
}
