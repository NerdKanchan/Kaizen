import { useEffect, useState } from "react";
import { api } from "../api";
import { useHotkeys } from "../lib/hotkeys";
import { useReviewer } from "../lib/reviewer";
import { displayName, fmtDate } from "../lib/format";
import { CLASSIFICATIONS, DECISION_KINDS, DECISION_LABELS, type Classification, type DecisionKind, type RowDetail } from "../types";
import { Button, Card, CardHead, Field } from "./ui";
import { ErrorBox } from "./Feedback";
import { ClassificationBadge, StateBadge } from "./Badges";

export function DecisionPanel({runId, rowId, detail, onChanged}: {runId: string; rowId: string; detail: RowDetail; onChanged: () => void}) {
  const {name} = useReviewer();
  const current = detail.decisions["1"] ?? detail.decisions["2"];
  const canEdit = detail.permission !== "view";
  const selfApproval = current?.reviewer === name || detail.owner === name;
  const [decision, setDecision] = useState<DecisionKind>(current?.decision ?? "ACCEPT");
  const [classification, setClassification] = useState<Classification>(current?.override_classification ?? "EQUIVALENT");
  const [comment, setComment] = useState(current?.comment ?? "");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setDecision(current?.decision ?? "ACCEPT"); setClassification(current?.override_classification ?? "EQUIVALENT"); setComment(current?.comment ?? ""); setConfirm(false); setError(null);
  }, [rowId, detail.revision, current?.decision, current?.override_classification, current?.comment]);
  const changed = !current || decision !== current.decision || comment !== current.comment || (decision === "OVERRIDE" && classification !== current.override_classification);
  async function perform(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); setConfirm(false); onChanged(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const saveDecision = () => perform(() => api.postDecision(runId, {row_id: rowId, decision, comment, override_classification: decision === "OVERRIDE" ? classification : undefined, expected_revision: detail.revision}));
  useHotkeys({
    a: () => canEdit && setDecision("ACCEPT"),
    o: () => canEdit && setDecision("OVERRIDE"),
    c: () => canEdit && setDecision("CONFIRM_DISCREPANCY"),
    n: () => canEdit && setDecision("NEEDS_MORE_INFORMATION"),
    Enter: () => { if (canEdit && changed && !busy) void saveDecision(); },
  }, [canEdit, changed, busy, rowId, decision, comment, classification, detail.revision]);
  return <Card className="decision-panel">
    <CardHead title="Review and approval" description={canEdit ? <span title={name}>Reviewer: {displayName(name)}</span> : "View-only access"} actions={<StateBadge value={detail.state} />} />
    <div className="p-5 grid gap-5">
      <div className="space-y-4">
        <fieldset disabled={!canEdit || busy} className="space-y-3">
          <Field label="Decision"><select className="input w-full" value={decision} onChange={e => {setDecision(e.target.value as DecisionKind); setConfirm(false);}}>{DECISION_KINDS.map(k => <option key={k} value={k}>{DECISION_LABELS[k]}</option>)}</select></Field>
          {decision === "OVERRIDE" && <Field label="Override classification"><select className="input w-full" value={classification} onChange={e => setClassification(e.target.value as Classification)}>{CLASSIFICATIONS.map(c => <option key={c}>{c}</option>)}</select></Field>}
          <Field label="Comment"><textarea className="input w-full" rows={3} value={comment} onChange={e => setComment(e.target.value)} /></Field>
          {canEdit && <Button variant="primary" disabled={!changed} loading={busy} onClick={saveDecision}>Save decision</Button>}
        </fieldset>
        {detail.final && <p className="text-xs text-ink-3">Saving another change clears this approval and keeps it in the history.</p>}
        {current && <p className="text-xs text-ink-3">Last changed by {current.reviewer} · {fmtDate(current.decided_at)}</p>}
        <div className="text-sm">Effective classification: <ClassificationBadge value={detail.effective_classification} /></div>
        {error && <ErrorBox error={error} />}
      </div>
      <div className="space-y-4">
        <h3 className="font-semibold">Approval</h3>
        {detail.final ? <div className="text-sm"><b>{detail.final.self_approved ? "Self-approved" : "Approved"}</b> by {detail.final.finalized_by}<p>{fmtDate(detail.final.finalized_at)} · {DECISION_LABELS[detail.final.final_decision]}</p>{detail.final.note && <p>{detail.final.note}</p>}</div> : canEdit && current ? <>
          <p className="text-sm">Approve <b>{DECISION_LABELS[current.decision]}</b>{current.override_classification ? ` → ${current.override_classification}` : ""}{current.comment ? ` — ${current.comment}` : ""}.</p>
          {changed && <p className="text-xs text-ink-3">Save your changes before approving.</p>}
          {selfApproval && <label className="flex gap-2 text-sm"><input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)} disabled={changed || busy} /><span>I reviewed these changes and confirm approval of my own work. This will be recorded as <b>self-approved</b>.</span></label>}
          <Button disabled={changed || busy || (selfApproval && !confirm)} onClick={() => perform(() => api.finalize(runId, {row_id: rowId, final_decision: current.decision, expected_revision: detail.revision, confirm_self_approval: selfApproval && confirm}))}>{selfApproval ? "Confirm self-approval" : "Approve decision"}</Button>
        </> : <p className="text-sm text-ink-3">{current ? "Awaiting approval" : "Record a decision before approving."}</p>}
        <details className="border-t border-line pt-3"><summary className="text-sm font-medium cursor-pointer">History ({detail.history.length})</summary><ol className="space-y-3 text-xs mt-3">
          {detail.history.map((h, index) => <li key={index}><b>{h.event === "engine" ? "Automated result" : h.final_decision ? h.self_approved ? "Self-approved" : "Approved" : "Decision saved"}</b><div className="text-ink-3">{h.reviewer || h.finalized_by} {h.decided_at || h.finalized_at ? `· ${fmtDate(h.decided_at || h.finalized_at)}` : ""}</div><p>{h.decision ? DECISION_LABELS[h.decision] : h.final_decision ? DECISION_LABELS[h.final_decision] : h.detail}{h.override_classification ? ` → ${h.override_classification}` : ""}{h.comment || h.note ? ` · ${h.comment || h.note}` : ""}</p></li>)}
        </ol></details>
      </div>
    </div>
  </Card>;
}
