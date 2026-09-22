// Optional Excel round-trip. Reviewers who prefer to work offline fill the decision columns in the exported
// workbook and import them here. Preview first (a dry run writes nothing); conflicts are never overwritten
// unless the reviewer ticks "overwrite".
import { FileXls } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "../api";
import { useReviewer } from "../lib/reviewer";
import { useToast } from "../lib/toast";
import { errorMessage } from "../lib/useAsync";
import type { RoundTripResult } from "../types";
import { ErrorBox } from "./Feedback";
import { Button, Dialog } from "./ui";

export function ImportDecisions({ runId, onApplied }: { runId: string; onApplied: () => void }) {
  const { session } = useReviewer();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<RoundTripResult | null>(null);
  const [result, setResult] = useState<RoundTripResult | null>(null);
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const reset = () => {
    setOpen(false);
    setFile(null);
    setPreview(null);
    setResult(null);
    setForce(false);
    setErr(null);
  };

  const run = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(dryRun ? "preview" : "apply");
    setErr(null);
    try {
      const r = await api.importDecisions(runId, file, { dryRun, force });
      if (dryRun) setPreview(r);
      else {
        setResult(r);
        setPreview(null);
        toast({ tone: "ok", title: `${r.applied.length} decision${r.applied.length === 1 ? "" : "s"} applied from Excel`, description: r.summary });
        onApplied();
      }
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const outcome = result ?? preview;
  return (
    <>
      <Button onClick={() => setOpen(true)} icon={<FileXls size={16} />} title="Optional: apply decisions you recorded in the exported workbook">
        Import from Excel
      </Button>
      <Dialog
        open={open}
        onClose={reset}
        title="Import decisions from Excel"
        description={`Optional. Only your own columns (reviewer ${session?.slot ?? 1}) are read; the workbook must belong to this run.`}
        footer={
          <>
            <Button variant="ghost" onClick={reset}>
              Close
            </Button>
            <Button disabled={!file || busy !== null} loading={busy === "preview"} onClick={() => run(true)}>
              Preview (dry run)
            </Button>
            <Button variant="primary" disabled={!file || busy !== null || !preview} loading={busy === "apply"} onClick={() => run(false)} title="Applies what the preview listed">
              Apply
            </Button>
          </>
        }
      >
        <p className="text-ink-2">
          Export the workbook, fill the <b>Reviewer {session?.slot === 2 ? "2 " : ""}Decision</b> and comment columns (an override is written as <span className="mono">OVERRIDE→EQUIVALENT</span>), then choose the file. Values are validated. A decision changed in the tool after the export is a conflict and is not overwritten unless you say so. Every applied decision is audited under your name ({session?.reviewer}).
        </p>
        <input
          type="file"
          accept=".xlsx"
          className="file-input"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setPreview(null);
            setResult(null);
          }}
          aria-label="Workbook"
        />
        {preview && preview.conflicts.length > 0 && (
          <label className="flex items-center gap-2 text-sm text-bad-strong">
            <input type="checkbox" className="accent-accent-500 w-4 h-4" checked={force} onChange={(e) => setForce(e.target.checked)} /> Overwrite the {preview.conflicts.length} conflict{preview.conflicts.length === 1 ? "" : "s"}
          </label>
        )}
        {err && <ErrorBox error={err} />}
        {outcome && <Outcome r={outcome} />}
      </Dialog>
    </>
  );
}

function Outcome({ r }: { r: RoundTripResult }) {
  return (
    <div className="space-y-2 rounded-md bg-surface-2/70 p-3">
      <div className={`font-medium ${r.dry_run ? "text-brand-700" : "text-ok-strong"}`}>{r.summary}</div>
      {r.conflicts.length > 0 && (
        <div>
          <div className="text-xs font-medium text-ink-2 mb-1">Conflicts: the tool changed these after the workbook was exported</div>
          <ul className="list-disc pl-5 space-y-0.5 text-xs">
            {r.conflicts.map((c) => (
              <li key={c.row_id}>
                <span className="mono">{c.row_id}</span>: workbook says <b>{c.workbook}</b>, tool has <b>{c.database}</b> by {c.database_reviewer} at {c.database_decided_at}
              </li>
            ))}
          </ul>
        </div>
      )}
      {r.invalid.length > 0 && (
        <div>
          <div className="text-xs font-medium text-ink-2 mb-1">Invalid values, not applied</div>
          <ul className="list-disc pl-5 space-y-0.5 text-xs">
            {r.invalid.map((i) => (
              <li key={i.row_id}>
                <span className="mono">{i.row_id}</span> ({i.sheet}): {i.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      {r.unknown_rows.length > 0 && (
        <div className="text-xs text-ink-3">
          Unknown row ids ignored: <span className="mono">{r.unknown_rows.join(", ")}</span>
        </div>
      )}
    </div>
  );
}
