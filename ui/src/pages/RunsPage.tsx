import { ArrowRight, CircleNotch, FolderOpen, Play, TerminalWindow } from "@phosphor-icons/react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { ErrorBox } from "../components/Feedback";
import { CLASS_COLORS } from "../components/Stat";
import { Button, Card, CardHead, EmptyState, PageHeader, TableSkeleton } from "../components/ui";
import { enc, fmtDate, shortSha } from "../lib/format";
import { errorMessage, useAsync } from "../lib/useAsync";
import { CLASSIFICATIONS, type RunSummary } from "../types";

// Folder selection: non-standard attributes, spread in to satisfy the React typings.
const DIR_PROPS = { webkitdirectory: "", directory: "" } as Record<string, string>;

export default function RunsPage() {
  const nav = useNavigate();
  const runs = useAsync(() => api.listRuns(), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [path, setPath] = useState("");
  const [fileCount, setFileCount] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);

  const start = async (label: string, fn: () => Promise<RunSummary>) => {
    setBusy(label);
    setErr(null);
    try {
      const s = await fn();
      nav(`/runs/${enc(s.run_id)}`);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  const upload = () => {
    const files = Array.from(fileRef.current?.files ?? []);
    if (files.length === 0) return;
    void start("upload", () => api.uploadRun(files));
  };
  const runPath = () => {
    if (!path.trim()) return;
    void start("path", () => api.runFromPath(path.trim()));
  };

  return (
    <div>
      <PageHeader title="Runs" description="A run is one deterministic pass over a folder of documents. The same inputs, thresholds and terminology version always give the same rows, so a result can be reproduced months later." />

      <div className="space-y-5 stagger">
        <Card>
          <CardHead title="Start a cross-check" description="Documents go in, a reviewable run comes out. Nothing leaves this machine." />
          <div className="grid md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-line">
            <div className="p-5 flex flex-col gap-3">
              <div className="flex items-center gap-2 text-ink">
                <Play size={18} className="text-brand-600" />
                <span className="text-sm font-semibold">Load the demo dataset</span>
              </div>
              <p className="text-sm text-ink-3 flex-1">Ten SKU sets with BOMs, labels, previous labels, drawings and two PCOs, with seeded discrepancies and declared ground truth.</p>
              <Button variant="primary" loading={busy === "demo"} disabled={busy !== null} onClick={() => start("demo", api.loadDemo)} iconRight={<ArrowRight size={16} />}>
                Load demo dataset
              </Button>
            </div>
            <div className="p-5 flex flex-col gap-3">
              <div className="flex items-center gap-2 text-ink">
                <FolderOpen size={18} className="text-brand-600" />
                <span className="text-sm font-semibold">Drop a project folder</span>
              </div>
              <p className="text-sm text-ink-3 flex-1">Choose the folder that holds the SKU sub-folders and PCO spreadsheets. Relative paths are kept, so grouping works as on disk.</p>
              <input ref={fileRef} type="file" multiple {...DIR_PROPS} className="file-input" onChange={(e) => setFileCount(e.target.files?.length ?? 0)} aria-label="Project folder" />
              <Button loading={busy === "upload"} disabled={busy !== null || fileCount === 0} onClick={upload}>
                {fileCount ? `Upload ${fileCount} file${fileCount === 1 ? "" : "s"} and run` : "Upload and run"}
              </Button>
            </div>
            <div className="p-5 flex flex-col gap-3">
              <div className="flex items-center gap-2 text-ink">
                <TerminalWindow size={18} className="text-brand-600" />
                <span className="text-sm font-semibold">Run a local path</span>
              </div>
              <p className="text-sm text-ink-3 flex-1">A folder on this machine, as the API process sees it. Nothing is uploaded.</p>
              <input
                className="input w-full mono"
                placeholder="/path/to/project-folder"
                value={path}
                aria-label="Local folder path"
                onChange={(e) => setPath(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") runPath();
                }}
              />
              <Button loading={busy === "path"} disabled={busy !== null || !path.trim()} onClick={runPath}>
                Run folder
              </Button>
            </div>
          </div>
          {busy && (
            <div className="flex items-center gap-2 px-5 py-3 border-t border-line text-sm text-ink-2 bg-surface-2/60 rounded-b-lg">
              <CircleNotch size={16} className="animate-spin text-brand-600" />
              Parsing every document and running the five checks. About a fifth of a second per SKU.
            </div>
          )}
        </Card>
        {err && <ErrorBox error={err} />}

        <Card>
          <CardHead
            title="Previous runs"
            count={runs.data ? runs.data.length : undefined}
            actions={
              <Button size="sm" variant="ghost" onClick={runs.reload}>
                Refresh
              </Button>
            }
          />
          {runs.loading && !runs.data && <TableSkeleton rows={4} cols={7} />}
          {runs.error && (
            <div className="p-4">
              <ErrorBox error={runs.error} onRetry={runs.reload} />
            </div>
          )}
          {runs.data &&
            (runs.data.length === 0 ? (
              <EmptyState icon={<FolderOpen size={36} />} title="No runs yet" description="Load the demo dataset or drop a project folder above. Every run stays in this workspace with its decisions and audit trail." />
            ) : (
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Input</th>
                      <th className="text-right">SKUs</th>
                      <th className="text-right">Documents</th>
                      <th className="text-right">Comparisons</th>
                      <th className="text-right">Needs review</th>
                      <th className="text-right">Auto-cleared</th>
                      <th>Engine classification</th>
                      <th>Terminology</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.data.map((r) => {
                      const total = CLASSIFICATIONS.reduce((n, c) => n + (r.summary[c] ?? 0), 0) || 1;
                      return (
                        <tr key={r.run_id} className="clickable" onClick={() => nav(`/runs/${enc(r.run_id)}`)}>
                          <td>
                            <div className="mono font-medium text-ink whitespace-nowrap">{r.run_id}</div>
                            <div className="text-xs text-ink-3 mt-0.5 whitespace-nowrap">
                              {fmtDate(r.created_at)} · tool {r.tool_version}
                            </div>
                          </td>
                          <td className="mono text-ink-3 max-w-[18rem] truncate" title={r.input_root}>
                            {r.input_root}
                          </td>
                          <td className="text-right num">{r.summary.skus}</td>
                          <td className="text-right num">{r.summary.documents}</td>
                          <td className="text-right num">{r.summary.rows}</td>
                          <td className="text-right num font-semibold text-bad-strong">{r.summary.needs_validation}</td>
                          <td className="text-right num text-ok-strong">{r.summary.rows - r.summary.needs_validation}</td>
                          <td className="min-w-[10rem]">
                            <div className="flex h-2 w-40 overflow-hidden rounded-full bg-surface-3" title={CLASSIFICATIONS.map((c) => `${c} ${r.summary[c] ?? 0}`).join(" · ")}>
                              {CLASSIFICATIONS.map((c) => (
                                <span key={c} style={{ width: `${(100 * (r.summary[c] ?? 0)) / total}%`, background: CLASS_COLORS[c] }} />
                              ))}
                            </div>
                          </td>
                          <td className="mono text-ink-3" title={r.terminology_version}>
                            {shortSha(r.terminology_version)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ))}
        </Card>
      </div>
    </div>
  );
}
