import { FileArrowUp, FileXls } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "../api";
import { useReviewer } from "../lib/reviewer";
import { useToast } from "../lib/toast";
import { errorMessage } from "../lib/useAsync";
import type { ImportResult, TerminologySource } from "../types";
import { ErrorBox, Notice } from "./Feedback";
import { AnchorButton, Button, Card, CardHead, Field } from "./ui";

export function TerminologyImport({ onImported }: { onImported: () => void }) {
  const { name } = useReviewer();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [sheet, setSheet] = useState("");
  const [headerRow, setHeaderRow] = useState(1);
  const [scope, setScope] = useState("global");
  const [source, setSource] = useState<TerminologySource | null>(null);
  const [mapping, setMapping] = useState<Record<string, string[]>>({});
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = !!source && !source.header_error && source.sheet === sheet && source.header_row === headerRow;

  const inspect = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setSource(null);
    try {
      const data = await api.terminology.inspectFile(file, sheet || undefined, headerRow);
      setSource(data);
      setSheet(data.sheet);
      setMapping(data.column_map);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const importFile = async (dryRun: boolean) => {
    if (!file || !ready) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api.terminology.importFile(file, name || "import", {
        sheet, header_row: headerRow, column_map: mapping, default_scope: scope, dry_run: dryRun,
        expected_version: dryRun ? undefined : result?.source.terminology_version,
      });
      setResult(data);
      if (data.applied) {
        onImported();
        toast({ tone: "ok", title: "Relationships imported", description: `${data.created} created, ${data.updated} updated, ${data.unchanged} unchanged.` });
      }
    } catch (e) {
      setError(errorMessage(e));
      if (!dryRun) setResult(null);
    } finally {
      setBusy(false);
    }
  };

  const mapSingle = (field: string, label = field) => (
    <Field key={field} label={label} htmlFor={`import-map-${field}`}>
      <select id={`import-map-${field}`} className="input" disabled={busy} value={mapping[field]?.[0] ?? ""} onChange={e => {
        setMapping(m => ({ ...m, [field]: e.target.value ? [e.target.value] : [] }));
        setResult(null);
      }}>
        <option value="">{field === "Canonical" ? "Select wording column" : "Not mapped"}</option>
        {source?.columns.map(c => <option key={c} value={c}>{c}</option>)}
      </select>
    </Field>
  );
  const mapMultiple = (field: string, label: string) => (
    <fieldset className="space-y-2" disabled={busy}>
      <legend className="label">{label}</legend>
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        {source?.columns.map(c => <label key={c} className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={(mapping[field] ?? []).includes(c)} onChange={e => {
            setMapping(m => ({ ...m, [field]: e.target.checked ? [...(m[field] ?? []), c] : (m[field] ?? []).filter(v => v !== c) }));
            setResult(null);
          }} />
          {c}
        </label>)}
      </div>
    </fieldset>
  );

  return <Card>
    <CardHead title="Import and export" description="Load a readable relationship export, map its columns, and preview the rules before importing." />
    <div className="p-4 space-y-4">
      <p className="text-sm text-ink-2">For a workbook protected by a sensitivity label, obtain a readable XLSX or CSV export from an authorized user where its document policy permits export.</p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="File to import" htmlFor="terminology-import" className="w-full sm:w-80 max-w-full">
          <input id="terminology-import" type="file" accept=".xlsx,.xlsm,.csv" className="file-input" disabled={busy} onChange={e => {
            setFile(e.target.files?.[0] ?? null); setSheet(""); setHeaderRow(1); setSource(null); setResult(null); setMapping({}); setError(null);
          }} />
        </Field>
        {!!source && source.sheets.length > 1 && <Field label="Worksheet" htmlFor="terminology-sheet">
          <select id="terminology-sheet" className="input" disabled={busy} value={sheet} onChange={e => { setSheet(e.target.value); setResult(null); }}>
            {source.sheets.map(s => <option key={s}>{s}</option>)}
          </select>
        </Field>}
        <Field label="Header row" htmlFor="terminology-header" className="w-28">
          <input id="terminology-header" type="number" min={1} max={1000} className="input" disabled={busy} value={headerRow} onChange={e => { setHeaderRow(Number(e.target.value)); setResult(null); }} />
        </Field>
        <Button loading={busy} disabled={!file || busy} onClick={inspect}>Read columns</Button>
        <AnchorButton href={api.terminology.exportUrl()} download icon={<FileXls size={16} />}>Export .xlsx</AnchorButton>
      </div>
      {error && <ErrorBox error={error} />}
      {source?.header_error && <Notice kind="warn">{source.header_error} Select a worksheet and header row, then read its columns again.</Notice>}
      {ready && source && <>
        <p className="text-sm text-ink-2">{source.row_count} source rows in {source.sheet}. Aliases within a cell use semicolons or new lines. Keep item numbers as text to preserve leading zeros.</p>
        <div className="overflow-x-auto max-h-64">
          <table className="tbl"><caption className="text-left text-sm text-ink-2 mb-2">Source sample</caption><thead><tr><th>Row</th>{source.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{source.sample.map(r => <tr key={r.row}><td>{r.row}</td>{source.columns.map(c => <td key={c}>{r.values[c]}</td>)}</tr>)}</tbody>
          </table>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">{mapSingle("Canonical", "Canonical wording")}
          <Field label="Default scope" htmlFor="import-default-scope" hint="global, family:<prefix> or sku:<code>; used when Scope is blank">
            <input id="import-default-scope" className="input" disabled={busy} value={scope} onChange={e => { setScope(e.target.value); setResult(null); }} />
          </Field>
        </div>
        {mapMultiple("Aliases", "Equivalent wording columns")}
        {mapMultiple("Item Anchors", "BOM item-number columns (optional)")}
        <details><summary className="text-sm cursor-pointer text-brand-600">Additional fields</summary>
          <div className="grid sm:grid-cols-3 gap-4 mt-3">{["ID", "Scope", "Doc Types", "Active", "Notes", "Provenance"].map(f => mapSingle(f))}</div>
        </details>
        <div className="flex flex-wrap gap-3">
          <Button disabled={busy || !mapping.Canonical?.length} loading={busy} onClick={() => importFile(true)}>Preview import</Button>
          {result?.dry_run && !result.errors.length && <Button variant="primary" icon={<FileArrowUp size={16} />} disabled={busy || !(result.created + result.updated)} onClick={() => importFile(false)}>
            Import {result.created + result.updated} approved relationships
          </Button>}
        </div>
      </>}
      {result && <>
        <Notice kind={result.errors.length ? "warn" : result.applied ? "good" : "info"}>
          <div className="font-medium">{result.summary}</div>
          {result.errors.length > 0 && <><p>No changes saved. Correct the listed rows and preview again.</p><ul className="list-disc pl-5 mt-2">{result.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></>}
          {result.applied && <p>These rules apply to the next run. Rerun the dataset to measure the change in coverage.</p>}
        </Notice>
        {!!result.rows.length && <div className="overflow-x-auto max-h-96"><table className="tbl">
          <thead><tr><th>Row</th><th>Change</th><th>Canonical</th><th>Aliases</th><th>Scope</th><th>Item numbers</th><th>Status</th></tr></thead>
          <tbody>{result.rows.map((r, i) => <tr key={i}><td>{r.row}</td><td>{r.action}</td><td>{r.canonical}</td><td>{r.aliases.join("; ")}</td><td>{r.scope}</td><td className="mono">{r.item_anchors.join("; ")}</td><td>{r.active ? "Active" : "Inactive"}</td></tr>)}</tbody>
        </table></div>}
      </>}
    </div>
  </Card>;
}
