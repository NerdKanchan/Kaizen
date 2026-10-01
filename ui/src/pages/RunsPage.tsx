import { ArrowRight, ArrowClockwise, CircleNotch, FolderOpen, MagnifyingGlass, Plus, UploadSimple } from "@phosphor-icons/react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useReviewer } from "../lib/reviewer";
import { api } from "../api";
import { ErrorBox } from "../components/Feedback";
import { Button, Card, Dialog, EmptyState, PageHeader, TableSkeleton } from "../components/ui";
import { enc, fmtDate, displayName } from "../lib/format";
import { errorMessage, useAsync } from "../lib/useAsync";
import { supportedRunFiles, uploadProblem } from "../lib/uploads";
import { useDataRefresh } from "../lib/dataRefresh";
import type { RunSummary } from "../types";

const DIR_PROPS = { webkitdirectory: "", directory: "" } as Record<string, string>;

export default function RunsPage() {
  const nav = useNavigate();
  const { session } = useReviewer();
  const [params, setParams] = useSearchParams();
  const tab = params.get("view") || "all";
  const search = params.get("q") || "";
  const updateFilter = (key: string, value: string) => setParams(previous => { const next = new URLSearchParams(previous); value ? next.set(key, value) : next.delete(key); return next; }, { replace: true });
  const [creating, setCreating] = useState(false);
  const [runName, setRunName] = useState("");
  const health = useAsync(api.health, []);
  const runs = useAsync(() => api.listRuns(), []);
  useDataRefresh(runs.reload);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [path, setPath] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileCount = files.length;
  const problem = fileCount ? uploadProblem(files) : null;
  const selectFiles = (list: FileList | null) => {
    const supported = supportedRunFiles(Array.from(list ?? []));
    setFiles(supported);
    setErr(list?.length && !supported.length ? uploadProblem(supported) : null);
  };
  const start = async (label: string, fn: () => Promise<RunSummary>) => {
    setBusy(label); setErr(null);
    try { const s = await fn(); nav(`/runs/${enc(s.run_id)}`); }
    catch (e) { setErr(errorMessage(e)); }
    finally { setBusy(null); }
  };
  const upload = () => {
    if (files.length) void start("upload", () => api.uploadRun(files, runName));
  };
  const all = runs.data ?? [];
  const visible = all.filter(r => (tab === "all" || (tab === "mine" ? r.permission === "owner" : r.permission !== "owner")) && `${r.name} ${r.run_id} ${r.owner}`.toLowerCase().includes(search.toLowerCase()));
  const openCreate = () => { setErr(null); setFiles([]); setRunName(""); setCreating(true); };

  return <div className="workspace-page">
    <PageHeader title="Cross-checks" description="Open a run or upload documents to start a new check." actions={<Button variant="primary" onClick={openCreate} icon={<Plus size={18} />}>New cross-check</Button>} />
    <div className="workspace-summary" aria-label="Run totals">
      <div><span>Total runs</span><strong>{runs.data ? all.length : "—"}</strong></div>
      <div><span>My runs</span><strong>{runs.data ? all.filter(r => r.permission === "owner").length : "—"}</strong></div>
      <div><span>Shared with me</span><strong>{runs.data ? all.filter(r => r.permission !== "owner").length : "—"}</strong></div>
    </div>
    <section aria-label="Cross-check runs" className="runs-section">
      <div className="runs-heading"><h2>Runs <span className="count-badge">{runs.data ? all.length : "—"}</span></h2><Button size="sm" variant="ghost" onClick={runs.reload} loading={runs.loading} icon={<ArrowClockwise size={16} />}>Refresh</Button></div>
      <div className="runs-toolbar">
        <div className="view-switch" role="group" aria-label="Filter runs by ownership">{[["all", "All runs"], ["mine", "My runs"], ["shared", "Shared with me"]].map(([value, label]) => <button key={value} aria-pressed={tab === value} onClick={() => updateFilter("view", value)}>{label}</button>)}</div>
        <label className="run-search"><MagnifyingGlass size={18} aria-hidden /><input value={search} onChange={e => updateFilter("q", e.target.value)} placeholder="Search runs…" aria-label="Search runs by name, ID or owner" />{search && <button onClick={() => updateFilter("q", "")} aria-label="Clear search">×</button>}</label>
      </div>
      {runs.error && <ErrorBox error={runs.error} onRetry={runs.reload} />}
      <Card className="runs-list">
        {runs.loading && !runs.data && <TableSkeleton rows={4} cols={4} />}
        {runs.data && !visible.length && <EmptyState icon={<FolderOpen size={36} />} title={search ? "No matching runs" : tab === "shared" ? "Nothing shared with you yet" : "No runs yet"} description={search ? "Try another name, run ID or owner, or clear your search." : tab === "shared" ? "When someone shares a run with you, it will appear here." : "Upload a project folder to create a run, or try the demo."} action={search ? <Button onClick={() => updateFilter("q", "")}>Clear search</Button> : <Button onClick={openCreate}>New cross-check</Button>} />}
        {!!visible.length && <><div className="run-list-labels" aria-hidden><span>Project / run</span><span>Documents</span><span>Review status</span><span /></div>{visible.map(r => <article className="run-list-row" key={r.run_id}>
          <div className="run-title-cell"><span className="run-folder"><FolderOpen size={23} /></span><div className="min-w-0"><Link className="run-title" to={`/runs/${enc(r.run_id)}`}>{r.name || r.run_id}</Link><p>{fmtDate(r.created_at)} <span>·</span> {r.permission === "owner" ? "You own this run" : `Shared by ${displayName(r.owner || "Unknown owner")}`}</p><span className="run-access">{r.permission === "owner" ? "Owner" : r.permission === "edit" ? "Can edit" : "View only"}</span></div></div>
          <div className="run-volume"><strong>{r.summary.documents} files</strong><small>{r.summary.skus} SKUs · {r.summary.rows} comparisons</small></div>
          <div className="run-status"><span className={`result-pill ${r.summary.review_progress?.pending || r.summary.review_progress?.unresolved_rows ? "needs-review" : "cleared"}`}>{r.unavailable ? "Saved run unavailable" : r.summary.review_progress?.pending ? `${r.summary.review_progress.pending} awaiting review or approval` : r.summary.review_progress?.unresolved_rows ? `${r.summary.review_progress.unresolved_rows} unresolved findings` : "No pending reviews"}</span><small>{r.summary.review_progress?.approved ?? 0} approved · {r.summary.auto_cleared ?? 0} auto-cleared by engine</small></div>
          <Link className="run-open" to={`/runs/${enc(r.run_id)}`} aria-label={`Open ${r.name || r.run_id}`}><span>Open run</span><ArrowRight size={18} /></Link>
        </article>)}</>}
      </Card>

    </section>
    <Dialog open={creating} onClose={() => { if (!busy) setCreating(false); }} title="New cross-check" description="Choose a folder or files containing your BOMs, labels, drawings and PCOs." footer={<><Button disabled={!!busy} onClick={() => setCreating(false)}>Cancel</Button><Button variant="primary" loading={busy === "upload"} disabled={!!busy || !fileCount || !!problem} onClick={upload} icon={<UploadSimple size={17} />}>{fileCount ? `Check ${fileCount} files` : "Start cross-check"}</Button></>}>
      <label className="label" htmlFor="run-name">Run name <span className="text-ink-3">(optional)</span></label><input id="run-name" className="input w-full" maxLength={120} placeholder="e.g. Orion · September label review" value={runName} onChange={e => setRunName(e.target.value)} />
      <div className="upload-zone"><FolderOpen size={32} /><strong>Choose your project folder</strong><p>Include SKU subfolders with BOMs, labels and drawings, plus any PCO files.</p><input type="file" multiple {...DIR_PROPS} className="file-input" disabled={!!busy} onChange={e => selectFiles(e.target.files)} aria-label="Project folder" /><small>PDF, XLSX, XLSM and CSV · Up to 250 MB · Folder structure is preserved</small><label className="label">Or choose individual files<input type="file" multiple accept=".pdf,.xlsx,.xlsm,.csv" disabled={!!busy} onChange={e => selectFiles(e.target.files)} aria-label="Individual documents" /></label>{!!fileCount && <span role="status">{fileCount} supported files selected</span>}</div>
      <div className="demo-option"><div><strong>Sample documents</strong><p>Use the demo to see how a review works.</p></div><Button disabled={!!busy} loading={busy === "demo"} onClick={() => start("demo", api.loadDemo)}>Try a demo</Button></div>
      {session?.is_admin && health.data && !health.data.hosted && <details className="advanced-options"><summary>Advanced: use a local folder path</summary><div className="space-y-3 pt-3"><p className="text-ink-3">Enter a folder path on the machine running Kaizen.</p><input className="input w-full mono" placeholder="/path/to/project-folder" value={path} aria-label="Local folder path" onChange={e => setPath(e.target.value)} /><Button loading={busy === "path"} disabled={!!busy || !path.trim()} onClick={() => start("path", () => api.runFromPath(path.trim(), runName))}>Run folder</Button></div></details>}
      {busy && <p className="flex gap-2 items-center" role="status"><CircleNotch size={16} className="animate-spin" />Checking documents…</p>}
      {err && <ErrorBox error={err} />}
      {problem && <ErrorBox error={problem} />}
    </Dialog>
  </div>;
}
