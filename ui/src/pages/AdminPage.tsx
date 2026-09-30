import { useState } from "react";
import { api } from "../api";
import { useReviewer } from "../lib/reviewer";
import { useAsync } from "../lib/useAsync";
import { Button, Card, LinkButton, PageHeader } from "../components/ui";
import { ErrorBox } from "../components/Feedback";
import type { Profile } from "../types";

export default function AdminPage() {
  const { session } = useReviewer();
  const users = useAsync(() => session?.is_admin ? api.users() : Promise.resolve([]), [session?.is_admin]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  async function update(p: Profile, change: Partial<Profile>) {
    setBusy(p.email); setError(null);
    try { await api.updateUser(p.email, change); users.reload(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  }
  if (!session?.is_admin) return <div><PageHeader title="Manage users" /><Card className="p-5 space-y-4"><p className="text-sm text-ink-2">Administrator access is required to manage accounts.</p><LinkButton to="/">Back to runs</LinkButton></Card></div>;
  return <div>
    <PageHeader title="Manage users" description="Approve account requests and manage administrator access." />
    {(error || users.error) && <ErrorBox error={error || users.error || ""} />}
    <Card className="divide-y divide-line">
      {users.loading && <p className="p-5">Loading accounts…</p>}
      {!users.loading && users.data?.length === 0 && <p className="p-5 text-sm text-ink-3">No accounts to review.</p>}
      {users.data?.map(p => <div key={p.email} className="p-5 flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0"><b className="break-all">{p.email}</b><p className="text-sm text-ink-3">{p.status.charAt(0).toUpperCase() + p.status.slice(1)} · {p.is_admin ? "Administrator" : "User"}</p></div>
        <div className="flex flex-wrap gap-2">
          {p.status !== "approved" && <Button loading={busy === p.email} disabled={!!busy} onClick={() => update(p, {status: "approved"})}>Approve account</Button>}
          {p.status === "approved" && <Button disabled={!!busy} onClick={() => {
            if (window.confirm(`${p.is_admin ? "Remove administrator access from" : "Make an administrator:"} ${p.email}?`)) void update(p, {is_admin: !p.is_admin});
          }}>{p.is_admin ? "Remove admin" : "Make admin"}</Button>}
          {p.status !== "rejected" && <Button variant="danger" disabled={!!busy} onClick={() => {
            if (window.confirm(`Revoke app access for ${p.email}? Their active sessions will end.`)) void update(p, {status: "rejected"});
          }}>{p.status === "pending" ? "Reject" : "Revoke access"}</Button>}
        </div>
      </div>)}
    </Card>
  </div>;
}
