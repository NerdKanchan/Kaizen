import { BookmarkSimple, ClipboardText } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { enc, familyOf } from "../lib/format";
import { useReviewer } from "../lib/reviewer";
import { useToast } from "../lib/toast";
import { errorMessage } from "../lib/useAsync";
import type { Relationship, RowDetail } from "../types";
import { StatusBadge } from "./Badges";
import { ErrorBox, Notice } from "./Feedback";
import { Button, Card, CardHead, Field } from "./ui";

/** "Save as relationship": turns a reviewer's judgement about this pair into an explicit, versioned rule. */
export function SaveRelationshipPanel({ runId, detail, onCreated }: { runId: string; detail: RowDetail; onCreated: () => void }) {
  const { name, session } = useReviewer();
  const toast = useToast();
  const a = detail.evidence.a;
  const b = detail.evidence.b;
  const rowId = detail.result.row_id;
  const sku = detail.result.sku;
  const [open, setOpen] = useState(false);
  const [canonical, setCanonical] = useState(b?.description ?? "");
  const [alias, setAlias] = useState(a?.description ?? "");
  const [scope, setScope] = useState("global");
  const [anchor, setAnchor] = useState(Boolean(a?.item_number));
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [created, setCreated] = useState<Relationship | null>(null);

  useEffect(() => {
    setCanonical(b?.description ?? "");
    setAlias(a?.description ?? "");
    setAnchor(Boolean(a?.item_number));
    setScope("global");
    setNotes("");
    setCreated(null);
    setErr(null);
    setOpen(false);
  }, [rowId, a?.description, b?.description, a?.item_number]);

  const existing = detail.result.relationship_id;
  const existingLine = existing && (
    <div className="text-sm text-ink-2">
      This comparison used relationship{" "}
      <Link className="mono" to={`/terminology?id=${enc(existing)}`}>
        {existing}
      </Link>
      .
    </div>
  );
  if (!a || !b || !session?.is_admin || detail.permission === "view") {
    return existing ? (
      <Card>
        <CardHead title="Terminology" icon={<BookmarkSimple size={18} />} />
        <div className="p-5">{existingLine}</div>
      </Card>
    ) : null;
  }

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const rel = await api.relationshipFromRow(runId, {
        row_id: rowId,
        scope,
        anchor,
        canonical: canonical.trim(),
        aliases: [alias.trim()],
        notes: notes.trim() || undefined,
      });
      setCreated(rel);
      toast({ tone: "ok", title: `Relationship ${rel.id} created`, description: "Saved for future runs." });
      onCreated();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHead title="Terminology" icon={<BookmarkSimple size={18} />} description="Save these terms as equivalent for future runs." />
      <div className="p-5 space-y-3">
        {existingLine}
        {created ? (
          <Notice kind="good">
            Created{" "}
            <Link className="mono" to={`/terminology?id=${enc(created.id)}`}>
              {created.id}
            </Link>{" "}
            (version {created.version}, scope <span className="mono">{created.scope}</span>
            {created.item_anchors.length > 0 && (
              <>
                , anchored to <span className="mono">{created.item_anchors.join(", ")}</span>
              </>
            )}
            ). Saved for future runs.
          </Notice>
        ) : !open ? (
          <div className="space-y-2">
            <p className="text-sm text-ink-3">
              Record that “{a.description}” and “{b.description}” mean the same part.
            </p>
            <Button onClick={() => setOpen(true)} icon={<BookmarkSimple size={16} />}>
              Save as relationship
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            <Field label="Canonical (label wording)">
              <input className="input w-full" value={canonical} onChange={(e) => setCanonical(e.target.value)} />
            </Field>
            <Field label="Alias (BOM wording)">
              <input className="input w-full" value={alias} onChange={(e) => setAlias(e.target.value)} />
            </Field>
            <Field label="Scope">
              <select className="input w-full" value={scope} onChange={(e) => setScope(e.target.value)}>
                <option value="global">Global: every SKU</option>
                <option value={`family:${familyOf(sku)}`}>Family {familyOf(sku)}: this product family</option>
                <option value={`sku:${sku}`}>SKU {sku}: this SKU only</option>
              </select>
            </Field>
            <label className={`flex items-center gap-2 text-sm ${a.item_number ? "" : "opacity-50"}`}>
              <input type="checkbox" className="accent-accent-500 w-4 h-4" checked={anchor} disabled={!a.item_number} onChange={(e) => setAnchor(e.target.checked)} />
              Bind to BOM item <span className="mono">{a.item_number ?? "(none on this row)"}</span>
            </label>
            <Field label="Notes" hint={`Defaults to: saved from run ${runId} row ${rowId}`}>
              <textarea className="input w-full" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </Field>
            {!name && <div className="text-sm text-bad">Sign in first: relationships record who created them.</div>}
            <div className="flex gap-2">
              <Button variant="primary" loading={busy} disabled={!name || !canonical.trim() || !alias.trim()} onClick={submit}>
                Save relationship
              </Button>
              <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
                Cancel
              </Button>
            </div>
            {err && <ErrorBox error={err} />}
          </div>
        )}
      </div>
    </Card>
  );
}

export function ActionItemPanel({ runId, detail, onCreated }: { runId: string; detail: RowDetail; onCreated: () => void }) {
  const { name } = useReviewer();
  const toast = useToast();
  const [owner, setOwner] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const rowId = detail.result.row_id;
  useEffect(() => {
    setErr(null);
    setOwner("");
  }, [rowId]);
  const create = async () => {
    setBusy(true);
    setErr(null);
    try {
      const ai = await api.createActionItem(runId, { row_id: rowId, reviewer: name, owner: owner.trim() || undefined });
      toast({ tone: "ok", title: `Action item ${ai.id} created`, description: "Re-run the corrected folder and use Verify and close on the dashboard to resolve it." });
      onCreated();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const hasDisc = detail.result.discrepancies.length > 0;
  return (
    <Card>
      <CardHead title="Action items" icon={<ClipboardText size={18} />} description="Create a follow-up task for this discrepancy." />
      <div className="p-5 space-y-3">
        {detail.action_items.length > 0 ? (
          <ul className="space-y-1.5 text-sm">
            {detail.action_items.map((ai) => (
              <li key={ai.id} className="flex items-center gap-2 flex-wrap">
                <Link className="mono" to={`/action-items?id=${enc(ai.id)}`}>
                  {ai.id}
                </Link>
                <StatusBadge value={ai.status} />
                <span className="text-ink-3">
                  {ai.discrepancy_type.replace(/_/g, " ").toLowerCase()} · owner {ai.owner || "unassigned"}
                </span>
                {ai.resolved_in_run && <span className="text-ok-strong text-xs">resolved in {ai.resolved_in_run}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-sm text-ink-3">None for this row.</div>
        )}
        <div className="flex flex-wrap gap-2 items-center">
          <input className="input flex-1 min-w-0 basis-32" placeholder="Owner (optional)" value={owner} disabled={detail.permission === "view" || busy} onChange={(e) => setOwner(e.target.value)} aria-label="Owner" />
          <Button loading={busy} disabled={!name || !hasDisc || detail.permission === "view"} onClick={create} title={detail.permission === "view" ? "View-only access" : hasDisc ? "" : "This row has no discrepancy to track"}>
            Create action item
          </Button>
        </div>
        {err && <ErrorBox error={err} />}
      </div>
    </Card>
  );
}
