import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../lib/useAsync";
import { enc } from "../lib/format";
import type { RunSummary } from "../types";
import { AnchorButton, Button, Card, Field } from "./ui";
import { ErrorBox } from "./Feedback";

export function RunSharing({ run, onChanged }: {run: RunSummary; onChanged: () => void}) {
  const nav = useNavigate();
  const owner = run.permission === "owner";
  const [open, setOpen] = useState(false);
  const profiles = useAsync(() => open && owner ? api.profiles() : Promise.resolve([]), [open, owner]);
  const shares = useAsync(() => open && owner ? api.shares(run.run_id) : Promise.resolve([]), [open, owner, run.run_id]);
  const [email, setEmail] = useState("");
  const [permission, setPermission] = useState<"view" | "edit">("view");
  const [name, setName] = useState(run.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function action(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); shares.reload(); onChanged(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <Card className="p-4 mb-5 space-y-3">
    <div className="flex flex-wrap items-center gap-3">
      <span className="text-sm flex-1">{owner ? "You own this run" : run.owner ? `Shared by ${run.owner}` : "Run access"} · <b>{run.permission === "view" ? "View only" : run.permission === "edit" ? "Can edit and approve" : owner ? "Full access" : "Access details unavailable"}</b></span>
      {owner && <Button onClick={() => setOpen(!open)}>{open ? "Close sharing" : "Share and rename"}</Button>}
      {run.permission !== "view" && <>
        <Button loading={busy} onClick={() => action(async () => { const copy = await api.copyRun(run.run_id); nav(`/runs/${enc(copy.run_id)}`); })}>Make a copy</Button>
        <AnchorButton href={api.downloadUrl(run.run_id)} download>Download independent copy</AnchorButton>
      </>}
    </div>
    {run.copied_from && <p className="text-xs text-ink-3">This copy has its own changes and approvals.</p>}
    {run.permission === "view" && <p className="text-xs text-ink-3">Ask the owner for edit access to save decisions, approve results or copy this run.</p>}
    {(error || shares.error || profiles.error) && <ErrorBox error={error || shares.error || profiles.error || ""} />}
    {open && owner && <div className="border-t border-line pt-4 space-y-4">
      <div className="flex flex-wrap items-end gap-2"><Field label="Run name" className="flex-1 min-w-0 basis-44"><input aria-label="Run name" className="input w-full" value={name} maxLength={120} onChange={e => setName(e.target.value)} /></Field><Button disabled={busy || !name.trim()} onClick={() => action(() => api.renameRun(run.run_id, name))}>Save name</Button></div>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Share with" className="flex-1 min-w-0 basis-56"><select aria-label="Share with an approved user" className="input w-full" value={email} onChange={e => setEmail(e.target.value)}><option value="">Choose an approved user</option>{profiles.data?.filter(p => p.email !== run.owner).map(p => <option key={p.email}>{p.email}</option>)}</select></Field>
        <Field label="Access"><select aria-label="Access" className="input" value={permission} onChange={e => setPermission(e.target.value as "view" | "edit")}><option value="view">Can view</option><option value="edit">Can edit and approve</option></select></Field>
        <Button disabled={busy || !email} onClick={() => action(() => api.share(run.run_id, email, permission))}>Share run</Button>
      </div>
      {shares.data?.map(s => <div className="flex flex-wrap items-center gap-3 text-sm" key={s.email}><span className="flex-1 min-w-0 break-all basis-48">{s.email}</span><select aria-label={`Access for ${s.email}`} className="input input-sm" value={s.permission} disabled={busy} onChange={e => action(() => api.share(run.run_id, s.email, e.target.value as "view" | "edit"))}><option value="view">Can view</option><option value="edit">Can edit and approve</option></select><Button disabled={busy} onClick={() => action(() => api.share(run.run_id, s.email, null))}>Remove</Button></div>)}
    </div>}
  </Card>;
}
