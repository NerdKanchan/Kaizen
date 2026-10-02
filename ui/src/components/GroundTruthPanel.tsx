import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { VERDICTS, type AttributeLabel, type GroundTruthBody, type LearningOption, type Verdict } from "../learning";
import { useReviewer } from "../lib/reviewer";
import { useAsync } from "../lib/useAsync";
import { enc } from "../lib/format";
import { CLASSIFICATIONS, type Classification, type RowDetail } from "../types";
import { ErrorBox } from "./Feedback";
import { Button, Card, CardHead, Field } from "./ui";

const DISCREPANCIES = ["QTY_MISMATCH", "DESC_MISMATCH", "MISSING_IN_LABEL", "MISSING_IN_BOM", "MISSING_IN_DRAWING", "EXTRA_ON_DRAWING", "AMBIGUOUS_MATCH", "LOW_EXTRACTION_CONFIDENCE"];
const blankAttributes = (): AttributeLabel => ({component_type: null, dimensions_mm: [], gauge: null, concentration_pct: null, pack_quantity: null});

export function GroundTruthPanel({runId, rowId, detail}: {runId: string; rowId: string; detail: RowDetail}) {
  const state = useAsync(() => api.learning.row(runId, rowId), [runId, rowId, detail.revision]);
  const {session, name} = useReviewer();
  const [verdict, setVerdict] = useState<Verdict>("UNRESOLVED");
  const [classification, setClassification] = useState<Classification>("POTENTIAL");
  const [aIds, setAIds] = useState<string[]>([]);
  const [bIds, setBIds] = useState<string[]>([]);
  const [discrepancies, setDiscrepancies] = useState<string[]>([]);
  const [allocations, setAllocations] = useState<Record<string, number>>({});
  const [attributes, setAttributes] = useState<Record<string, AttributeLabel>>({});
  const [dimensionText, setDimensionText] = useState<Record<string, string>>({});
  const [includeAttributes, setIncludeAttributes] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const annotation = state.data?.annotation;
  useEffect(() => {
    const p = annotation?.payload;
    setVerdict(p?.verdict ?? "UNRESOLVED");
    setClassification(p?.classification ?? detail.result.classification);
    setAIds(p?.expected_a_ids ?? (detail.result.source_a ? [detail.result.source_a.id] : []));
    setBIds(p?.expected_b_ids ?? (detail.result.source_b ? [detail.result.source_b.id] : []));
    setDiscrepancies(p?.discrepancies ?? detail.result.discrepancies.map(d => d.type));
    setAllocations(p?.assembly_quantities ?? {});
    setAttributes(p?.attributes ?? {});
    setDimensionText({});
    setIncludeAttributes(!!p && Object.keys(p.attributes).length > 0);
    setNote(p?.note ?? ""); setError(null);
  }, [rowId, annotation?.version]);
  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (!state.data) return null;
  const canEdit = detail.permission !== "view";
  const selected = [...state.data.a_options, ...state.data.b_options].filter(i => aIds.includes(i.id) || bIds.includes(i.id));
  async function perform(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); state.reload(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function save() {
    return perform(() => {
      const verifiedAttributes = Object.fromEntries(selected.map(i => {
        const value = attributes[i.id] ?? i.suggested_attributes;
        const text = dimensionText[i.id];
        const dimensions = text === undefined ? value.dimensions_mm : text.trim() ? text.split(",").map(Number) : [];
        if (includeAttributes && dimensions.some(n => !Number.isFinite(n) || n <= 0)) throw new Error("Enter positive dimensions in mm, separated by commas.");
        return [i.id, {...value, dimensions_mm: dimensions}];
      }));
      const body: GroundTruthBody = {expected_version: annotation?.version ?? 0, review_revision: detail.revision, verdict, classification, expected_a_ids: aIds, expected_b_ids: bIds, discrepancies,
        assembly_quantities: aIds.length > 1 ? Object.fromEntries(aIds.map(id => [id, allocations[id] ?? 0])) : {},
        attributes: includeAttributes ? verifiedAttributes : {}, note};
      return api.learning.annotate(runId, rowId, body);
    });
  }
  const saved = annotation?.payload;
  const dirty = !!saved && (verdict !== saved.verdict || classification !== saved.classification || note !== saved.note ||
    JSON.stringify(aIds) !== JSON.stringify(saved.expected_a_ids) || JSON.stringify(bIds) !== JSON.stringify(saved.expected_b_ids) ||
    JSON.stringify(discrepancies) !== JSON.stringify(saved.discrepancies) || JSON.stringify(allocations) !== JSON.stringify(saved.assembly_quantities) ||
    JSON.stringify(includeAttributes ? Object.fromEntries(selected.map(i => [i.id, attributes[i.id] ?? i.suggested_attributes])) : {}) !== JSON.stringify(saved.attributes) ||
    (includeAttributes && selected.some(i => dimensionText[i.id] !== undefined && dimensionText[i.id] !== (attributes[i.id] ?? i.suggested_attributes).dimensions_mm.join(", "))));
  function choices(label: string, options: LearningOption[], ids: string[], change: (ids: string[]) => void) {
    return <Field label={label}><select multiple size={5} className="input w-full" value={ids} onChange={e => change(Array.from(e.target.selectedOptions, o => o.value))}>
      {options.map(i => <option key={i.id} value={i.id}>{i.item_number ? `${i.item_number} · ` : ""}{i.description} · qty {i.quantity ?? "?"}</option>)}
    </select><p className="text-xs text-ink-3 mt-1">Cmd/Ctrl-click to select assembly members or deselect an absent counterpart.</p></Field>;
  }
  return <Card>
    <CardHead title="Ground truth" description={state.data.enabled ? `Reserved for ${state.data.split === "evaluation" ? "evaluation" : "training"}${annotation ? ` · v${annotation.version} · ${annotation.status}` : ""}` : "Closed testing is not enabled"} />
    <div className="p-5 space-y-4">
      {!state.data.enabled ? <p className="text-sm">The run owner can enable data collection on the <Link to={`/runs/${enc(runId)}/learning`}>Closed testing</Link> page.</p> : <>
        <p className="text-xs text-ink-3">Identify the true source pairing and outcome from the documents. A different administrator verifies it before it enters a dataset.</p>
        <fieldset disabled={!canEdit || busy} className="space-y-4">
          <Field label="What did you verify?"><select className="input w-full" value={verdict} onChange={e => setVerdict(e.target.value as Verdict)}>{VERDICTS.map(([v, text]) => <option key={v} value={v}>{text}</option>)}</select></Field>
          {choices("Expected source A (keep the reviewed component)", state.data.a_options, aIds, setAIds)}
          {choices("Expected source B", state.data.b_options, bIds, setBIds)}
          {selected.map(i => <p key={i.id} className="text-xs"><Link to={`/runs/${enc(runId)}/documents/${enc(i.doc_id)}?item=${enc(i.id)}${i.page ? `&page=${i.page}` : ""}`}>Inspect {i.item_number || i.description}</Link>{i.page ? ` · page ${i.page}` : ""}</p>)}
          {aIds.length > 1 && <div className="space-y-2"><p className="text-sm font-medium">Assembly quantities per label unit</p>{state.data.a_options.filter(i => aIds.includes(i.id)).map(i => <Field key={i.id} label={i.item_number || i.description}><input type="number" min="0.000001" step="any" className="input w-full" value={allocations[i.id] ?? ""} onChange={e => setAllocations({...allocations, [i.id]: Number(e.target.value)})} /></Field>)}</div>}
          <Field label="Verified classification"><select className="input w-full" value={classification} onChange={e => setClassification(e.target.value as Classification)}>{CLASSIFICATIONS.map(c => <option key={c}>{c}</option>)}</select></Field>
          <Field label="Verified discrepancy types"><select multiple size={4} className="input w-full" value={discrepancies} onChange={e => setDiscrepancies(Array.from(e.target.selectedOptions, o => o.value))}>{Array.from(new Set([...DISCREPANCIES, ...discrepancies])).map(d => <option key={d}>{d}</option>)}</select><p className="text-xs text-ink-3 mt-1">Deselect all for a clear match.</p></Field>
          <details><summary className="text-sm font-medium cursor-pointer">Component attributes</summary>
            <label className="flex gap-2 text-xs my-3"><input type="checkbox" checked={includeAttributes} onChange={e => setIncludeAttributes(e.target.checked)} />I checked these attributes against the sources.</label>
            <p className="text-xs text-ink-3 mb-3">Suggested values need verification. Dimensions use mm; leave unreadable or unspecified fields empty.</p>
            {selected.map(i => {
              const value = attributes[i.id] ?? i.suggested_attributes ?? blankAttributes();
              const update = (key: keyof AttributeLabel, val: AttributeLabel[keyof AttributeLabel]) => setAttributes({...attributes, [i.id]: {...value, [key]: val}});
              return <div key={i.id} className="border-t border-line py-3 space-y-2"><b className="text-xs">{i.description}</b>
                <Field label="Component type"><input className="input w-full" value={value.component_type ?? ""} onChange={e => update("component_type", e.target.value || null)} /></Field>
                <Field label="Dimensions in mm (comma separated)"><input className="input w-full" value={dimensionText[i.id] ?? value.dimensions_mm.join(", ")} onChange={e => setDimensionText({...dimensionText, [i.id]: e.target.value})} /></Field>
                {(["gauge", "concentration_pct", "pack_quantity"] as const).map(key => <Field key={key} label={key === "concentration_pct" ? "Concentration (%)" : key === "pack_quantity" ? "Pack quantity" : "Gauge"}><input type="number" step={key === "pack_quantity" ? "1" : "any"} className="input w-full" value={value[key] ?? ""} onChange={e => update(key, e.target.value ? Number(e.target.value) : null)} /></Field>)}
              </div>;
            })}
          </details>
          <Field label="Evidence and reason"><textarea className="input w-full" rows={3} value={note} onChange={e => setNote(e.target.value)} placeholder="Explain the corrected pairing, discrepancy or missing evidence." /></Field>
          {canEdit && <Button variant="primary" loading={busy} disabled={!note.trim()} onClick={save}>Save annotation</Button>}
        </fieldset>
        {annotation && <p className="text-xs text-ink-3">Annotated by {annotation.annotated_by}{annotation.approved_by ? ` · verified by ${annotation.approved_by}` : ""}. Changing a review decision requires fresh ground-truth verification.</p>}
        {session?.is_admin && canEdit && annotation?.status === "pending" && annotation.annotated_by !== name && <div className="flex flex-wrap gap-2">
          <Button loading={busy} disabled={dirty || annotation.payload.verdict === "UNRESOLVED"} onClick={() => perform(() => api.learning.approve(runId, rowId, annotation.version, true))}>Verify saved annotation</Button>
          <Button loading={busy} disabled={dirty} onClick={() => perform(() => api.learning.approve(runId, rowId, annotation.version, false))}>Reject annotation</Button>
        </div>}
        {dirty && session?.is_admin && <p className="text-xs text-ink-3">Save your edits before verifying an annotation.</p>}
        {annotation?.annotated_by === name && annotation.status === "pending" && <p className="text-xs text-ink-3">Another administrator must verify your annotation.</p>}
      </>}
      {error && <ErrorBox error={error} />}
    </div>
  </Card>;
}
