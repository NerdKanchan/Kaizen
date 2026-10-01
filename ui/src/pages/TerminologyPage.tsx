// Terminology: the versioned rules that let the next run clear a wording it has already
// seen. Visual rules: docs/design/DESIGN.md.
import { ArrowsClockwise, Check, CheckCircle, ClockCounterClockwise, MagnifyingGlass, Plus, Prohibit, TextAa, X } from "@phosphor-icons/react";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type RelationshipCreateBody } from "../api";
import { Badge } from "../components/Badges";
import { ErrorBox, Loading, Notice } from "../components/Feedback";
import { TerminologyImport } from "../components/TerminologyImport";
import { Button, Card, CardHead, Dialog, Divider, EmptyState, Field, PageHeader, TableSkeleton } from "../components/ui";
import { fmtDate } from "../lib/format";
import { useReviewer } from "../lib/reviewer";
import { useToast } from "../lib/toast";
import { errorMessage, useAsync } from "../lib/useAsync";
import { DOC_TYPES, type Relationship } from "../types";

type ScopeFilter = "" | "global" | "family" | "sku";

const SCOPE_FILTERS: { value: ScopeFilter; label: string }[] = [
  { value: "", label: "All scopes" },
  { value: "global", label: "Global" },
  { value: "family", label: "Family" },
  { value: "sku", label: "SKU" },
];

const PROVENANCE_LABEL: Record<string, string> = { manual: "Manual", learned: "Learned", imported: "Imported" };
const SCOPE_KIND_LABEL: Record<string, string> = { family: "Family", sku: "SKU" };

const lines = (s: string) =>
  s
    .split(/\r?\n|,/)
    .map((x) => x.trim())
    .filter(Boolean);

const sentence = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** "family:1295108" reads as "Family 1295108"; the code stays mono because it is an identifier. */
function Scope({ scope }: { scope: string }) {
  const i = scope.indexOf(":");
  if (i < 0) return <span>{scope === "global" ? "Global" : scope}</span>;
  const kind = scope.slice(0, i);
  return (
    <span className="whitespace-nowrap">
      {SCOPE_KIND_LABEL[kind] ?? kind} <span className="mono text-ink">{scope.slice(i + 1)}</span>
    </span>
  );
}

/** A pressable filter or option. Buttons carry the button vocabulary; the pressed state is announced. */
function Toggle({ on, onClick, children, title, disabled }: { on: boolean; onClick: () => void; children: ReactNode; title?: string; disabled?: boolean }) {
  return (
    <Button size="sm" aria-pressed={on} disabled={disabled} title={title} onClick={onClick} className={on ? "!bg-brand-100 !border-brand-600 !text-brand-700" : ""}>
      {on && <Check size={14} aria-hidden />}
      {children}
    </Button>
  );
}

export default function TerminologyPage() {
  const [sp, setSp] = useSearchParams();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [applied, setApplied] = useState("");
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>("");
  const [showInactive, setShowInactive] = useState(true);
  const list = useAsync(() => api.terminology.list({ search: applied || undefined, all: true }), [applied]);
  const selectedId = sp.get("id");
  const [creating, setCreating] = useState(false);

  const visible = useMemo(() => {
    const all = list.data ?? [];
    return showInactive ? all : all.filter((x) => x.active);
  }, [list.data, showInactive]);
  const rows = useMemo(() => {
    if (scopeFilter === "global") return visible.filter((x) => x.scope === "global");
    if (scopeFilter) return visible.filter((x) => x.scope.startsWith(`${scopeFilter}:`));
    return visible;
  }, [visible, scopeFilter]);
  const scopeCount = (f: ScopeFilter) =>
    f === "" ? visible.length : f === "global" ? visible.filter((x) => x.scope === "global").length : visible.filter((x) => x.scope.startsWith(`${f}:`)).length;
  const inactive = (list.data ?? []).filter((x) => !x.active).length;

  const openRel = (id: string | null) => {
    const n = new URLSearchParams(sp);
    if (id) n.set("id", id);
    else n.delete("id");
    setSp(n, { replace: true });
  };

  const empty = rows.length === 0 && !!list.data;
  const noneAtAll = (list.data?.length ?? 0) === 0;

  return (
    <div>
      <PageHeader
        title="Terminology"
        description="Manage terms that should be treated as equivalent in future runs."
        actions={
          <>
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
              New relationship
            </Button>
          </>
        }
      />

      <div className="space-y-5 stagger">
        <Notice>
          Changes apply to future runs. Previous versions are kept in the history.
        </Notice>

        <div className="flex flex-col xl:flex-row gap-5 items-start">
          <Card className="w-full min-w-0 flex-1">
            <CardHead
              title="Relationships"
              count={list.data ? `${rows.length} of ${list.data.length}` : undefined}
              actions={
                <Button size="sm" variant="ghost" icon={<ArrowsClockwise size={16} />} onClick={list.reload}>
                  Refresh
                </Button>
              }
            />
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 border-b border-line bg-surface-2/60">
              <form
                className="terminology-search flex flex-wrap items-center gap-2 max-w-full"
                onSubmit={(e) => {
                  e.preventDefault();
                  setApplied(search.trim());
                }}
              >
                <div className="relative">
                  <MagnifyingGlass size={16} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" aria-hidden />
                  <input
                    className="input w-72 pl-8"
                    placeholder="Search canonical, aliases, notes"
                    aria-label="Search relationships"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                <Button type="submit">Search</Button>
                {applied && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setSearch("");
                      setApplied("");
                    }}
                  >
                    Clear
                  </Button>
                )}
              </form>
              <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Scope filter">
                {SCOPE_FILTERS.map((f) => (
                  <Toggle key={f.value} on={scopeFilter === f.value} onClick={() => setScopeFilter(f.value)}>
                    {f.label}
                    <span className="num text-ink-3">{scopeCount(f.value)}</span>
                  </Toggle>
                ))}
              </div>
              <Toggle on={showInactive} onClick={() => setShowInactive((v) => !v)} title="Deactivated rules are kept for the audit trail; future runs do not use them">
                Show inactive
                <span className="num text-ink-3">{inactive}</span>
              </Toggle>
            </div>

            {list.error && (
              <div className="p-4">
                <ErrorBox error={list.error} onRetry={list.reload} />
              </div>
            )}
            {list.loading && !list.data && <TableSkeleton rows={8} cols={6} />}
            {empty && (
              <EmptyState
                icon={<TextAa size={36} />}
                title={noneAtAll ? "No relationships yet" : "No relationships match"}
                description={
                  noneAtAll
                    ? "Add a confirmed term pair or import a spreadsheet."
                    : "Clear the search or widen the scope filter to see the rest, or create a relationship for the wording you were looking for."
                }
                action={
                  <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
                    New relationship
                  </Button>
                }
              />
            )}
            {list.data && rows.length > 0 && (
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Id</th>
                      <th>Canonical and aliases</th>
                      <th>Scope</th>
                      <th>Applies to</th>
                      <th>Provenance</th>
                      <th>Created</th>
                      <th className="text-right">Version</th>
                      <th>Status</th>
                      <th className="text-right">Used by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className={`clickable ${r.id === selectedId ? "selected" : ""}`} onClick={() => openRel(r.id)}>
                        <td className="mono whitespace-nowrap"><button type="button" className="text-brand-600 underline underline-offset-2" aria-label={`Open relationship ${r.id}: ${r.canonical}`} onClick={e => { e.stopPropagation(); openRel(r.id); }}>{r.id}</button></td>
                        <td className="min-w-[16rem]">
                          <div className={`font-medium ${r.active ? "text-ink" : "text-ink-3"}`}>{r.canonical}</div>
                          {r.aliases.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1">
                              {r.aliases.map((a) => (
                                <span key={a} className="chip">
                                  {a}
                                </span>
                              ))}
                            </div>
                          )}
                        </td>
                        <td className="text-ink-2">
                          <Scope scope={r.scope} />
                        </td>
                        <td>
                          <div className="flex flex-wrap items-center gap-1">
                            {r.doc_types.length === 0 ? (
                              <span className="text-ink-3">All document types</span>
                            ) : (
                              r.doc_types.map((t) => (
                                <span key={t} className="chip">
                                  {t}
                                </span>
                              ))
                            )}
                          </div>
                          {r.item_anchors.length > 0 && (
                            <div className="text-xs text-ink-3 mt-1 whitespace-nowrap">
                              items <span className="mono text-ink-2">{r.item_anchors.join(", ")}</span>
                            </div>
                          )}
                        </td>
                        <td className="text-ink-2">{PROVENANCE_LABEL[r.provenance] ?? sentence(r.provenance)}</td>
                        <td className="whitespace-nowrap text-ink-2">
                          {r.created_by}
                          <div className="text-xs text-ink-3">{fmtDate(r.created_at)}</div>
                        </td>
                        <td className="text-right num">{r.version}</td>
                        <td>
                          <Badge tone={r.active ? "ok" : "neutral"}>{r.active ? "Active" : "Inactive"}</Badge>
                        </td>
                        <td className="text-right whitespace-nowrap">
                          <span className="num font-medium">{r.usage ?? 0}</span>
                          <div className="text-xs text-ink-3">comparison{r.usage === 1 ? "" : "s"}</div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {selectedId && (
            <div className="w-full xl:w-[27rem] shrink-0 xl:sticky xl:top-[4.5rem]">
              <RelationshipPanel id={selectedId} onClose={() => openRel(null)} onChanged={list.reload} />
            </div>
          )}
        </div>

        <TerminologyImport onImported={list.reload} />
      </div>

      {creating && (
        <CreateDialog
          onClose={() => setCreating(false)}
          onCreated={(rel) => {
            setCreating(false);
            list.reload();
            openRel(rel.id);
            toast({ tone: "ok", title: `Relationship ${rel.id} created`, description: "Saved for future runs." });
          }}
        />
      )}
    </div>
  );
}

/** The selected relationship: what it is, an edit that saves a new version, and the version history. */
function RelationshipPanel({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const { name } = useReviewer();
  const toast = useToast();
  const uid = useId();
  const rel = useAsync(() => api.terminology.get(id), [id]);
  const hist = useAsync(() => api.terminology.history(id), [id]);
  const [form, setForm] = useState({ canonical: "", aliases: "", scope: "global", anchors: "", doc_types: [] as string[], notes: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!rel.data) return;
    setForm({ canonical: rel.data.canonical, aliases: rel.data.aliases.join("\n"), scope: rel.data.scope, anchors: rel.data.item_anchors.join(", "), doc_types: rel.data.doc_types, notes: rel.data.notes, note: "" });
    setErr(null);
  }, [rel.data]);

  const act = async (fn: () => Promise<Relationship>, msg: (r: Relationship) => { title: string; description?: string }) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fn();
      rel.setData(r);
      hist.reload();
      onChanged();
      toast({ tone: "ok", ...msg(r) });
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const save = () =>
    act(
      () =>
        api.terminology.update(id, {
          canonical: form.canonical.trim(),
          aliases: lines(form.aliases),
          scope: form.scope.trim(),
          item_anchors: lines(form.anchors),
          doc_types: form.doc_types,
          notes: form.notes,
          by: name,
          note: form.note.trim() || "edited in UI",
        }),
      (r) => ({ title: `Relationship ${id} saved`, description: `Now at version ${r.version}. Past runs keep the version they used.` }),
    );

  const r = rel.data;
  return (
    <Card>
      <CardHead
        title={<span className="mono">{id}</span>}
        count={r ? `version ${r.version}` : undefined}
        actions={
          <>
            {r && <Badge tone={r.active ? "ok" : "neutral"}>{r.active ? "Active" : "Inactive"}</Badge>}
            <Button variant="ghost" size="sm" iconOnly aria-label="Close relationship" onClick={onClose} icon={<X size={16} />} />
          </>
        }
      />
      {rel.error && (
        <div className="p-4">
          <ErrorBox error={rel.error} onRetry={rel.reload} />
        </div>
      )}
      {!r && !rel.error && (
        <div className="p-4">
          <Loading label="Loading relationship" lines={4} />
        </div>
      )}
      {r && (
        <div className="p-4 space-y-4 text-sm">
          <div>
            <div className="label">Why it exists</div>
            <p className={r.notes ? "text-ink-2" : "text-ink-4"}>{r.notes || "No notes recorded."}</p>
            <dl className="kv mt-3">
              <dt>Provenance</dt>
              <dd>{PROVENANCE_LABEL[r.provenance] ?? sentence(r.provenance)}</dd>
              <dt>Created</dt>
              <dd>
                {r.created_by} · {fmtDate(r.created_at)}
              </dd>
              <dt>Updated</dt>
              <dd>{fmtDate(r.updated_at)}</dd>
              <dt>Used by</dt>
              <dd>
                <span className="num">{r.usage ?? 0}</span> comparison{r.usage === 1 ? "" : "s"} across recorded runs
              </dd>
            </dl>
          </div>

          <Divider />

          <div className="space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-ink">Edit</h3>
              <p className="hint mt-0.5">Changes apply to future runs. Previous versions remain in the history.</p>
            </div>
            <Field label="Canonical term" htmlFor={`${uid}-canonical`}>
              <input id={`${uid}-canonical`} className="input w-full" value={form.canonical} onChange={(e) => setForm({ ...form, canonical: e.target.value })} />
            </Field>
            <Field label="Aliases" hint="One per line." htmlFor={`${uid}-aliases`}>
              <textarea id={`${uid}-aliases`} className="input w-full" rows={3} value={form.aliases} onChange={(e) => setForm({ ...form, aliases: e.target.value })} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Scope" hint={"global, family:<prefix> or sku:<code>"} htmlFor={`${uid}-scope`}>
                <input id={`${uid}-scope`} className="input w-full mono" value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })} />
              </Field>
              <Field label="Item anchors" hint="BOM item numbers, comma-separated." htmlFor={`${uid}-anchors`}>
                <input id={`${uid}-anchors`} className="input w-full mono" value={form.anchors} onChange={(e) => setForm({ ...form, anchors: e.target.value })} />
              </Field>
            </div>
            <div role="group" aria-labelledby={`${uid}-doctypes`}>
              <div className="label" id={`${uid}-doctypes`}>
                Document types
              </div>
              <div className="flex flex-wrap gap-1.5">
                {DOC_TYPES.map((t) => (
                  <Toggle
                    key={t}
                    on={form.doc_types.includes(t)}
                    onClick={() => setForm({ ...form, doc_types: form.doc_types.includes(t) ? form.doc_types.filter((x) => x !== t) : [...form.doc_types, t] })}
                  >
                    {t}
                  </Toggle>
                ))}
              </div>
              <p className="hint mt-1">{form.doc_types.length === 0 ? "None selected, so the rule applies to every document type." : "The rule applies only to the types selected."}</p>
            </div>
            <Field label="Notes" hint="Add the source or reason for this relationship." htmlFor={`${uid}-notes`}>
              <textarea id={`${uid}-notes`} className="input w-full" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </Field>
            <Field label="Change note" hint="Describe what changed." htmlFor={`${uid}-note`}>
              <input id={`${uid}-note`} className="input w-full" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
            </Field>
            {!name && <Notice kind="warn">Sign in at the top bar first: every change records who made it.</Notice>}
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" icon={<Check size={16} />} loading={busy} disabled={busy || !name || !form.canonical.trim()} onClick={save}>
                Save new version
              </Button>
              {r.active ? (
                <Button
                  variant="danger"
                  icon={<Prohibit size={16} />}
                  disabled={busy || !name}
                  onClick={() => act(() => api.terminology.deactivate(id, name), () => ({ title: `Relationship ${id} deactivated`, description: "Future runs will not use it. Past runs are unchanged." }))}
                >
                  Deactivate
                </Button>
              ) : (
                <Button
                  icon={<CheckCircle size={16} />}
                  disabled={busy || !name}
                  onClick={() => act(() => api.terminology.activate(id, name), () => ({ title: `Relationship ${id} activated`, description: "The next run will apply it again." }))}
                >
                  Activate
                </Button>
              )}
            </div>
            {err && <ErrorBox error={err} />}
          </div>

          <Divider />

          <div>
            <h3 className="text-sm font-semibold text-ink flex items-center gap-1.5">
              <ClockCounterClockwise size={16} className="text-ink-3" aria-hidden />
              Version history
            </h3>
            {hist.error && (
              <div className="mt-2">
                <ErrorBox error={hist.error} onRetry={hist.reload} />
              </div>
            )}
            {!hist.data && !hist.error && <Loading label="Loading history" lines={3} />}
            {hist.data && (
              <ol className="mt-3">
                {[...hist.data].reverse().map((h, i, arr) => (
                  <li key={h.version} className="flex gap-3">
                    <div className="flex flex-col items-center">
                      <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${i === 0 ? "bg-brand-600" : "bg-line-2"}`} aria-hidden />
                      {i < arr.length - 1 && <span className="w-px flex-1 bg-line my-1" aria-hidden />}
                    </div>
                    <div className={`min-w-0 flex-1 ${i < arr.length - 1 ? "pb-4" : ""}`}>
                      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <span className="font-medium text-ink">
                          Version <span className="num">{h.version}</span>
                        </span>
                        <span className="text-xs text-ink-2">{sentence(h.change_type)}</span>
                        {i === 0 && <span className="chip">Current</span>}
                      </div>
                      <div className="text-xs text-ink-3">
                        {h.changed_by} · {fmtDate(h.changed_at)}
                      </div>
                      {h.change_note && <p className="text-ink-2 mt-1">“{h.change_note}”</p>}
                      <div className="text-xs text-ink-3 mt-1 break-words">
                        <span className="text-ink-2 font-medium">{h.payload.canonical}</span>
                        {h.payload.aliases.length > 0 && <> = {h.payload.aliases.join(" | ")}</>}
                      </div>
                      <div className="text-xs text-ink-3 mt-0.5">
                        <Scope scope={h.payload.scope} />
                        {h.payload.item_anchors.length > 0 && (
                          <>
                            {" · anchors "}
                            <span className="mono">{h.payload.item_anchors.join(", ")}</span>
                          </>
                        )}
                        {h.payload.active ? "" : " · inactive"}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function CreateDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (r: Relationship) => void }) {
  const { name } = useReviewer();
  const uid = useId();
  const [form, setForm] = useState({ canonical: "", aliases: "", scope: "global", anchors: "", doc_types: [] as string[], notes: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body: RelationshipCreateBody = {
        canonical: form.canonical.trim(),
        aliases: lines(form.aliases),
        scope: form.scope.trim() || "global",
        doc_types: form.doc_types,
        item_anchors: lines(form.anchors),
        provenance: "manual",
        by: name,
        notes: form.notes.trim(),
      };
      onCreated(await api.terminology.create(body));
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open
      onClose={onClose}
      title="New relationship"
      description="Enter the preferred term and its equivalent terms."
      width="lg"
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" icon={<Plus size={16} />} loading={busy} disabled={busy || !name || !form.canonical.trim() || lines(form.aliases).length === 0} onClick={submit}>
            Create relationship
          </Button>
        </>
      }
    >
      <Field label="Canonical term" hint="Usually the label wording." htmlFor={`${uid}-canonical`}>
        <input id={`${uid}-canonical`} className="input w-full" value={form.canonical} onChange={(e) => setForm({ ...form, canonical: e.target.value })} autoFocus />
      </Field>
      <Field label="Aliases" hint="One per line: the BOM and drawing wordings that mean the same thing." htmlFor={`${uid}-aliases`}>
        <textarea id={`${uid}-aliases`} className="input w-full" rows={3} value={form.aliases} onChange={(e) => setForm({ ...form, aliases: e.target.value })} />
      </Field>
      <div className="grid sm:grid-cols-2 gap-3">
        <Field label="Scope" hint="Where the rule applies." htmlFor={`${uid}-scope`}>
          <input
            id={`${uid}-scope`}
            className="input w-full mono"
            value={form.scope}
            onChange={(e) => setForm({ ...form, scope: e.target.value })}
            placeholder="global | family:1295108 | sku:1295108NS"
          />
        </Field>
        <Field label="Item anchors" hint="Optional: limit the rule to these BOM item numbers." htmlFor={`${uid}-anchors`}>
          <input id={`${uid}-anchors`} className="input w-full mono" value={form.anchors} onChange={(e) => setForm({ ...form, anchors: e.target.value })} placeholder="4440003, 0703450" />
        </Field>
      </div>
      <div role="group" aria-labelledby={`${uid}-doctypes`}>
        <div className="label" id={`${uid}-doctypes`}>
          Document types
        </div>
        <div className="flex flex-wrap gap-1.5">
          {DOC_TYPES.map((t) => (
            <Toggle
              key={t}
              on={form.doc_types.includes(t)}
              onClick={() => setForm({ ...form, doc_types: form.doc_types.includes(t) ? form.doc_types.filter((x) => x !== t) : [...form.doc_types, t] })}
            >
              {t}
            </Toggle>
          ))}
        </div>
        <p className="hint mt-1">{form.doc_types.length === 0 ? "None selected, so the rule applies to every document type." : "The rule applies only to the types selected."}</p>
      </div>
      <Field label="Notes" hint="Add the source or reason for this relationship." htmlFor={`${uid}-notes`}>
        <textarea id={`${uid}-notes`} className="input w-full" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </Field>
      {!name && <Notice kind="warn">Sign in at the top bar first: every relationship records who created it.</Notice>}
      {err && <ErrorBox error={err} />}
    </Dialog>
  );
}
