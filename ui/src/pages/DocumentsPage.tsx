import { ArrowsClockwise, Eye, FileArrowDown, Files, MagnifyingGlass } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, DocTypeBadge } from "../components/Badges";
import { ErrorBox } from "../components/Feedback";
import { AnchorButton, Button, Card, CardHead, EmptyState, LinkButton, PageHeader, TableSkeleton } from "../components/ui";
import { enc, shortSha } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { DOC_TYPES, type DocType, type DocumentSummary } from "../types";

/** Number of columns in the table below: the SKU group header spans all of them. */
const SPAN = 8;

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** BOM, label, drawing, PCO: the order a reviewer reads a SKU set in. */
function typeOrder(t: string): number {
  const i = DOC_TYPES.indexOf(t as DocType);
  return i < 0 ? DOC_TYPES.length : i;
}

interface Group {
  sku: string;
  docs: DocumentSummary[];
  items: number;
  warnings: number;
}

export default function DocumentsPage() {
  const { runId = "" } = useParams();
  const nav = useNavigate();
  const docs = useAsync(() => api.getDocuments(runId), [runId]);
  const [filter, setFilter] = useState("");

  // One group per SKU set, in SKU order; files that belong to no SKU set come last.
  const groups = useMemo<Group[]>(() => {
    const needle = filter.trim().toLowerCase();
    const hit = (d: DocumentSummary) => !needle || [d.file_name, d.file, d.sku ?? "", d.doc_type, d.parser].some((s) => s.toLowerCase().includes(needle));
    const by = new Map<string, DocumentSummary[]>();
    for (const d of docs.data ?? []) {
      if (!hit(d)) continue;
      const list = by.get(d.sku ?? "");
      if (list) list.push(d);
      else by.set(d.sku ?? "", [d]);
    }
    return [...by.entries()]
      .sort((a, b) => (a[0] === "" ? 1 : b[0] === "" ? -1 : a[0].localeCompare(b[0])))
      .map(([sku, list]) => {
        const ordered = [...list].sort((a, b) => typeOrder(a.doc_type) - typeOrder(b.doc_type) || a.file_name.localeCompare(b.file_name));
        return { sku, docs: ordered, items: ordered.reduce((n, d) => n + d.items, 0), warnings: ordered.reduce((n, d) => n + d.warnings.length, 0) };
      });
  }, [docs.data, filter]);

  const all = docs.data ?? [];
  const shown = groups.reduce((n, g) => n + g.docs.length, 0);
  const lines = all.reduce((n, d) => n + d.items, 0);
  const warnings = all.reduce((n, d) => n + d.warnings.length, 0);
  const filtering = filter.trim().length > 0;

  return (
    <div>
      <PageHeader
        back={{ to: `/runs/${enc(runId)}`, label: "Dashboard" }}
        title="Documents"
        description="Every file this run parsed, grouped by the SKU set it belongs to. Open a document to check the extraction line by line against the page it came from."
        meta={
          docs.data && (
            <>
              <span>{plural(all.length, "document")}</span>
              <span>{plural(lines, "extracted line")}</span>
              <span className={warnings ? "text-warn-strong" : undefined}>{plural(warnings, "parser warning")}</span>
              <span>{plural(groups.length, "SKU set")}</span>
            </>
          )
        }
        actions={
          <Button variant="ghost" onClick={docs.reload} loading={docs.loading && docs.data !== null} icon={<ArrowsClockwise size={16} />}>
            Refresh
          </Button>
        }
      />

      <div className="space-y-5 stagger">
        <Card>
          <CardHead
            title="Parsed documents"
            description="Parser and version are recorded with every file, so an extraction can be explained months later."
            count={docs.data ? (filtering ? `${shown} of ${all.length}` : all.length) : undefined}
            icon={<Files size={18} />}
            actions={
              <div className="relative">
                <MagnifyingGlass size={16} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3 pointer-events-none" aria-hidden />
                <input className="input input-sm pl-8 w-56" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by file, SKU or parser" aria-label="Filter documents by file name, SKU or parser" />
              </div>
            }
          />

          {docs.loading && !docs.data && <TableSkeleton rows={8} cols={7} />}
          {docs.error && (
            <div className="p-4">
              <ErrorBox error={docs.error} onRetry={docs.reload} />
            </div>
          )}

          {docs.data &&
            (all.length === 0 ? (
              <EmptyState
                icon={<Files size={36} />}
                title="This run parsed no documents"
                description="Nothing in the input folder was recognised as a BOM, label, drawing or PCO. Start a new run from a folder that holds the SKU sub-folders."
                action={
                  <LinkButton to="/" variant="primary">
                    Go to runs
                  </LinkButton>
                }
              />
            ) : shown === 0 ? (
              <EmptyState
                icon={<MagnifyingGlass size={36} />}
                title="No document matches that filter"
                description={`Clear the filter to see all ${plural(all.length, "document")} in this run.`}
                action={<Button onClick={() => setFilter("")}>Clear filter</Button>}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Type</th>
                      <th>File</th>
                      <th>Parser</th>
                      <th className="text-right">Lines</th>
                      <th className="text-right">Pages</th>
                      <th>Warnings</th>
                      <th>SHA-256</th>
                      <th className="text-right">Open</th>
                    </tr>
                  </thead>
                  {groups.map((g) => (
                    <tbody key={g.sku || "unassigned"}>
                      <tr>
                        <td colSpan={SPAN} className="bg-surface-2 py-2 border-b border-line">
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            {g.sku ? (
                              <>
                                <span className="text-xs font-medium text-ink-2">SKU set</span>
                                <span className="mono text-sm font-semibold text-ink">{g.sku}</span>
                              </>
                            ) : (
                              <span className="text-sm font-semibold text-ink">No SKU set</span>
                            )}
                            <span className="text-xs text-ink-3">
                              {plural(g.docs.length, "document")} · {plural(g.items, "line")}
                            </span>
                            {g.warnings > 0 && <Badge tone="warn">{plural(g.warnings, "parser warning")}</Badge>}
                          </div>
                        </td>
                      </tr>
                      {g.docs.map((d) => {
                        const to = `/runs/${enc(runId)}/documents/${enc(d.id)}`;
                        return (
                          <tr key={d.id} className="clickable" onClick={() => nav(to)}>
                            <td>
                              <DocTypeBadge value={d.doc_type} />
                            </td>
                            <td className="min-w-[15rem]">
                              <Link className="mono font-medium" to={to} onClick={(e) => e.stopPropagation()}>
                                {d.file_name}
                              </Link>
                              <div className="mono text-xs text-ink-3 truncate max-w-[24rem]" title={d.file}>
                                {d.file}
                              </div>
                            </td>
                            <td className="whitespace-nowrap text-ink-2">
                              {d.parser} <span className="text-ink-3">v{d.parser_version}</span>
                            </td>
                            <td className="text-right num">{d.items}</td>
                            <td className="text-right num text-ink-2">{d.pages > 0 ? d.pages : <span className="text-xs text-ink-3">Spreadsheet</span>}</td>
                            <td className="max-w-[22rem]">
                              {d.warnings.length === 0 ? (
                                <span className="text-ink-4">—</span>
                              ) : (
                                <>
                                  <Badge tone="warn">{plural(d.warnings.length, "warning")}</Badge>
                                  <div className="text-xs text-warn-strong mt-1">{d.warnings.join("; ")}</div>
                                </>
                              )}
                            </td>
                            <td className="mono text-ink-3" title={d.sha256}>
                              {shortSha(d.sha256)}
                            </td>
                            <td className="whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                              <div className="flex items-center justify-end gap-1.5">
                                <LinkButton size="sm" to={to} icon={<Eye size={16} />}>
                                  Document
                                </LinkButton>
                                {d.doc_type === "BOM" && (
                                  <AnchorButton size="sm" href={api.annotatedBomUrl(runId, d.id)} download icon={<FileArrowDown size={16} />} title="BOM PDF with check marks from the reviewer decisions">
                                    Annotated BOM
                                  </AnchorButton>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  ))}
                </table>
              </div>
            ))}
        </Card>
      </div>
    </div>
  );
}
