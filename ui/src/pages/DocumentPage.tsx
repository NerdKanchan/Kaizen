import { ArrowSquareOut, CaretLeft, CaretRight, CursorClick, FileText, FileXls, MagnifyingGlass, Rows } from "@phosphor-icons/react";
import { useMemo, useState, type ReactNode } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Badge, DocTypeBadge } from "../components/Badges";
import { ErrorBox, Notice } from "../components/Feedback";
import { PageImage } from "../components/PageImage";
import { AnchorButton, Button, Card, CardHead, EmptyState, PageHeader, Skeleton, TableSkeleton } from "../components/ui";
import { enc, fmtQty, isPdf } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import type { DocType, DocumentItem } from "../types";

/** Below this the parser is not sure it read the value correctly; the reviewer checks it against the page. */
const LOW_CONFIDENCE = 0.7;

interface Col {
  h: string;
  cell: (i: DocumentItem) => ReactNode;
  cls?: string;
  head?: string;
}

const str = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const pct = (c: number) => `${(c * 100).toFixed(0)}%`;
/** Terms that stay upper case when a code is read back as words. */
const ACRONYMS = new Set(["sku", "pco", "bom", "uom", "jde", "id", "pdf", "en", "es", "ecn", "eco", "ul"]);
/** Engine codes (PHYSICAL_COMPONENT) read as words on screen; the raw code stays in the title attribute. */
const words = (s: string) =>
  s
    .replace(/_/g, " ")
    .toLowerCase()
    .split(" ")
    .map((w, i) => (ACRONYMS.has(w) ? w.toUpperCase() : i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");

function columns(t: DocType): Col[] {
  switch (t) {
    case "BOM":
      return [
        { h: "Item number", cell: (i) => i.item_number ?? "—", cls: "mono font-medium whitespace-nowrap" },
        { h: "Description", cell: (i) => i.description, cls: "min-w-[14rem]" },
        { h: "Quantity", cell: (i) => `${fmtQty(i.quantity)} ${i.uom ?? ""}`, cls: "num whitespace-nowrap text-right", head: "text-right" },
        { h: "Sequence", cell: (i) => i.oper_seq ?? "—", cls: "num text-right", head: "text-right" },
        {
          h: "Category",
          cell: (i) => (
            <>
              <span className={i.category === "PHYSICAL_COMPONENT" ? "font-medium text-ink" : "text-ink-3"} title={i.category}>
                {words(i.category)}
              </span>
              {i.category_reason && <div className="text-xs text-ink-3">{i.category_reason}</div>}
            </>
          ),
        },
        { h: "Active", cell: (i) => (i.is_active ? "Yes" : <span className="text-ink-4">No</span>) },
        { h: "Locator", cell: (i) => i.locator ?? "—", cls: "mono text-ink-3 whitespace-nowrap" },
      ];
    case "LABEL":
      return [
        { h: "Quantity", cell: (i) => `${fmtQty(i.quantity)} ${i.uom ?? ""}`, cls: "num whitespace-nowrap text-right", head: "text-right" },
        { h: "Description", cell: (i) => i.description, cls: "min-w-[14rem]" },
        { h: "Sub-quantity", cell: (i) => (i.sub_quantity ? `${i.sub_quantity.raw} (${i.sub_quantity.value} ${i.sub_quantity.kind})` : "—"), cls: "text-ink-2" },
        { h: "Category", cell: (i) => <span title={i.category}>{words(i.category)}</span>, cls: "text-ink-2" },
        { h: "Locator", cell: (i) => i.locator ?? "—", cls: "mono text-ink-3 whitespace-nowrap" },
      ];
    case "DRAWING":
      return [
        { h: "Callout", cell: (i) => str(i.attributes.callout_index), cls: "num text-right", head: "text-right" },
        { h: "Sheet", cell: (i) => str(i.attributes.sheet), cls: "num text-right", head: "text-right" },
        { h: "Text (English)", cell: (i) => i.description, cls: "min-w-[14rem]" },
        { h: "Text (Spanish)", cell: (i) => str(i.attributes.es_text), cls: "text-ink-2" },
        { h: "Conditional", cell: (i) => (i.attributes.conditional ? <Badge tone="warn">Conditional</Badge> : <span className="text-ink-4">No</span>) },
        { h: "Placement", cell: (i) => str(i.attributes.placement), cls: "text-ink-2" },
      ];
    case "PCO":
      return [
        {
          h: "Kind",
          cell: (i) => (
            <>
              <span>{words(String(str(i.attributes.kind)))}</span>
              {i.attributes.change_kind ? <span className="chip ml-1.5">{words(String(i.attributes.change_kind))}</span> : null}
            </>
          ),
          cls: "whitespace-nowrap",
        },
        {
          h: "Item, actual to proposed",
          cell: (i) => (i.attributes.kind === "change" ? `${str(i.attributes.item_actual)} → ${str(i.attributes.item_proposed)}` : i.item_number ?? "—"),
          cls: "mono whitespace-nowrap",
        },
        { h: "Description", cell: (i) => i.description, cls: "min-w-[14rem]" },
        { h: "Quantity, actual to proposed", cell: (i) => (i.attributes.kind === "change" ? `${str(i.attributes.qty_actual)} → ${str(i.attributes.qty_proposed)}` : "—"), cls: "num whitespace-nowrap" },
        { h: "Sequence, actual to proposed", cell: (i) => (i.attributes.kind === "change" ? `${str(i.attributes.seq_actual)} → ${str(i.attributes.seq_proposed)}` : "—"), cls: "num whitespace-nowrap" },
        { h: "Locator", cell: (i) => i.locator ?? "—", cls: "mono text-ink-3 whitespace-nowrap" },
      ];
  }
}

export default function DocumentPage() {
  const { runId = "", docId = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const doc = useAsync(() => api.getDocumentItems(runId, docId), [runId, docId]);
  const [filter, setFilter] = useState("");
  const [pageOnly, setPageOnly] = useState(false);
  const page = Math.max(1, Number(sp.get("page") || 1) || 1);
  const selectedId = sp.get("item");
  const selected = useMemo(() => doc.data?.items.find((i) => i.id === selectedId) ?? null, [doc.data, selectedId]);

  const setParam = (k: string, v: string | null) => {
    const n = new URLSearchParams(sp);
    if (v) n.set(k, v);
    else n.delete(k);
    setSp(n, { replace: true });
  };
  const select = (i: DocumentItem) => {
    const n = new URLSearchParams(sp);
    n.set("item", i.id);
    if (i.page) n.set("page", String(i.page));
    setSp(n, { replace: true });
  };

  const back = { to: `/runs/${enc(runId)}/documents`, label: "Documents" };
  if (doc.error)
    return (
      <div>
        <PageHeader title="Document" back={back} />
        <ErrorBox error={doc.error} onRetry={doc.reload} />
      </div>
    );
  if (!doc.data) return <DocumentSkeleton />;

  const d = doc.data;
  const pdf = isPdf(d.file_name) && d.pages > 0;
  const src = pdf ? api.pageImageUrl(runId, docId, page) : null;
  const cols = columns(d.doc_type);
  const lowConf = d.items.filter((i) => i.confidence < LOW_CONFIDENCE).length;
  const header = Object.entries(d.header);
  const needle = filter.trim().toLowerCase();
  const filtering = needle.length > 0 || pageOnly;
  const rows = d.items
    .map((item, n) => ({ item, n: n + 1 }))
    .filter(({ item }) => (!pageOnly || item.page === page) && (!needle || [item.item_number ?? "", item.description, item.locator ?? "", item.raw_text].some((s) => s.toLowerCase().includes(needle))));
  const clearFilters = () => {
    setFilter("");
    setPageOnly(false);
  };
  const selectedElsewhere = selected !== null && selected.page !== null && selected.page !== page;

  return (
    <div>
      <PageHeader
        back={back}
        title={
          <>
            <DocTypeBadge value={d.doc_type} />
            <span className="mono text-xl">{d.file_name}</span>
          </>
        }
        description="Select an extracted line to see its location in the source document."
        meta={
          <>
            <span>{plural(d.items.length, "extracted line")}</span>
            <span>{pdf ? plural(d.pages, "page") : "Spreadsheet source, no page images"}</span>
            {lowConf > 0 && <span className="text-warn-strong">{lowConf} below the confidence threshold</span>}
            {d.warnings.length > 0 && <span className="text-warn-strong">{plural(d.warnings.length, "parser warning")}</span>}
          </>
        }
      />

      <div className="space-y-5 stagger">
        {d.warnings.length > 0 && (
          <Notice kind="warn">
            <div className="font-medium">Extraction warnings for this document</div>
            <ul className="list-disc pl-4 mt-1 space-y-0.5">
              {d.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </Notice>
        )}

        <div className="grid xl:grid-cols-2 gap-5 items-start">
          {/* ---- the evidence: the page as it was filed */}
          <div className="space-y-5">
            <Card>
              <CardHead
                title="Source page"
                description={pdf ? "The selected line is highlighted on the page." : "Page previews are available for PDF files."}
                actions={
                  pdf ? (
                    <>
                      <Button size="sm" iconOnly aria-label="Previous page" title="Previous page" disabled={page <= 1} onClick={() => setParam("page", String(page - 1))} icon={<CaretLeft size={16} />} />
                      <select className="input input-sm" aria-label="Page" value={page} onChange={(e) => setParam("page", e.target.value)}>
                        {Array.from({ length: d.pages }, (_, i) => i + 1).map((n) => (
                          <option key={n} value={n}>
                            Page {n} of {d.pages}
                          </option>
                        ))}
                      </select>
                      <Button size="sm" iconOnly aria-label="Next page" title="Next page" disabled={page >= d.pages} onClick={() => setParam("page", String(page + 1))} icon={<CaretRight size={16} />} />
                      {src && (
                        <AnchorButton size="sm" href={src} target="_blank" rel="noreferrer" icon={<ArrowSquareOut size={16} />}>
                          Open
                        </AnchorButton>
                      )}
                    </>
                  ) : undefined
                }
              />
              {pdf ? (
                <div className="p-3">
                  <PageImage
                    src={src}
                    bbox={selected && selected.page === page ? selected.bbox : null}
                    alt={`${d.file_name} page ${page}`}
                    maxHeight="64vh"
                    fallback={<span className="text-ink-2">The page preview is unavailable. Extracted text is still available.</span>}
                  />
                  {selectedElsewhere && (
                    <div className="flex flex-wrap items-center gap-2 mt-2 text-xs text-ink-3">
                      <span>The selected line was read from page {selected?.page}.</span>
                      <Button size="sm" variant="ghost" onClick={() => setParam("page", String(selected?.page))}>
                        Go to page {selected?.page}
                      </Button>
                    </div>
                  )}
                  {selected && !selectedElsewhere && selected.bbox === null && <p className="hint mt-2">No page highlight is available for this line.</p>}
                </div>
              ) : (
                <EmptyState
                  icon={<FileXls size={36} />}
                  title="No page image for this source"
                  description="Select a line to see its sheet, row and original cell text."
                />
              )}
            </Card>

            <Card>
              <CardHead title="Selected line" description="Text and source location." icon={<CursorClick size={18} />} />
              {selected ? (
                <dl className="kv p-4">
                  <dt>Line</dt>
                  <dd className="mono">{selected.id}</dd>
                  <dt>Locator</dt>
                  <dd>
                    <span className="mono">{selected.locator ?? "—"}</span>
                    {selected.sheet && <span className="text-ink-3"> · sheet {selected.sheet}</span>}
                    {selected.page !== null && <span className="text-ink-3"> · page {selected.page}</span>}
                  </dd>
                  <dt>Item number</dt>
                  <dd className="mono">{selected.item_number ?? "—"}</dd>
                  <dt>Description</dt>
                  <dd className="font-medium">{selected.description}</dd>
                  <dt>Quantity</dt>
                  <dd className="num">
                    {fmtQty(selected.quantity)} {selected.uom ?? ""}
                    {selected.sub_quantity && <span className="text-ink-3"> · sub-quantity {selected.sub_quantity.raw}</span>}
                    {selected.oper_seq && <span className="text-ink-3"> · sequence {selected.oper_seq}</span>}
                  </dd>
                  <dt>Category</dt>
                  <dd>
                    <span title={selected.category}>{words(selected.category)}</span>
                    {selected.category_reason && <span className="text-ink-3"> — {selected.category_reason}</span>}
                  </dd>
                  <dt>Confidence</dt>
                  <dd>{selected.confidence < LOW_CONFIDENCE ? <Badge tone="warn">{pct(selected.confidence)} — verify against the page</Badge> : <span className="num">{pct(selected.confidence)}</span>}</dd>
                  <dt>Raw text</dt>
                  <dd>
                    <pre className="mono text-xs whitespace-pre-wrap bg-surface-2 border border-line rounded p-2">{selected.raw_text}</pre>
                  </dd>
                </dl>
              ) : (
                <EmptyState icon={<CursorClick size={32} />} title="No line selected" description="Select an extracted line to view its details." />
              )}
            </Card>

            {header.length > 0 && (
              <Card>
                <CardHead title="Document header" description="" count={header.length} />
                <dl className="kv p-4">
                  {header.map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt title={k}>{words(k)}</dt>
                      <dd>{Array.isArray(v) ? v.join(", ") : str(v)}</dd>
                    </div>
                  ))}
                </dl>
              </Card>
            )}
          </div>

          {/* ---- the extraction: every line the parser produced */}
          <Card>
            <CardHead
              title="Extracted lines"
              description="Select a line to view its source."
              icon={<Rows size={18} />}
              count={filtering ? `${rows.length} of ${d.items.length}` : d.items.length}
              actions={
                <>
                  {pdf && (
                    <Button size="sm" aria-pressed={pageOnly} className={pageOnly ? "bg-brand-100 border-brand-600 text-brand-700" : ""} onClick={() => setPageOnly(!pageOnly)} icon={<FileText size={16} />} title="Show only the lines read from the page on the left">
                      This page
                    </Button>
                  )}
                  <div className="relative">
                    <MagnifyingGlass size={16} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3 pointer-events-none" aria-hidden />
                    <input className="input input-sm pl-8 w-44" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter lines" aria-label="Filter extracted lines by item number, description, locator or raw text" />
                  </div>
                </>
              }
            />
            {d.items.length === 0 ? (
              <EmptyState icon={<Rows size={36} />} title="Nothing was extracted from this document" description="Check the extraction warnings or open the source file." />
            ) : rows.length === 0 ? (
              <EmptyState icon={<MagnifyingGlass size={36} />} title="No line matches" description={`Clear the filter to see all ${plural(d.items.length, "extracted line")}.`} action={<Button onClick={clearFilters}>Clear filter</Button>} />
            ) : (
              <div className="overflow-auto max-h-[76vh]">
                <div className="overflow-x-auto">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th className="text-right">#</th>
                        {pdf && <th className="text-right">Page</th>}
                        {cols.map((c) => (
                          <th key={c.h} className={c.head}>
                            {c.h}
                          </th>
                        ))}
                        <th className="text-right">Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(({ item, n }) => (
                        <tr key={item.id} className={`clickable ${item.is_active ? "" : "text-ink-4"}`} data-selected={item.id === selectedId ? "true" : undefined} onClick={() => select(item)}>
                          <td className="num text-right"><button type="button" className="text-brand-600 underline underline-offset-2" aria-label={`View extracted line ${n}`} aria-pressed={item.id === selectedId} onClick={e => { e.stopPropagation(); select(item); }}>{n}</button></td>
                          {pdf && <td className={`num text-right ${item.page === page ? "text-ink-2" : "text-ink-4"}`}>{item.page ?? "—"}</td>}
                          {cols.map((c) => (
                            <td key={c.h} className={c.cls}>
                              {c.cell(item)}
                            </td>
                          ))}
                          <td className={`num text-right ${item.confidence < LOW_CONFIDENCE ? "text-warn-strong font-semibold" : "text-ink-3"}`}>{pct(item.confidence)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

/** Loading state shaped like the page: header, source panel, extraction table. */
function DocumentSkeleton() {
  return (
    <div aria-busy aria-label="Loading document">
      <div className="mb-5">
        <Skeleton className="h-3 w-24 mb-2" />
        <Skeleton className="h-7 w-80 mb-2" />
        <Skeleton className="h-3 w-[28rem]" />
      </div>
      <div className="grid xl:grid-cols-2 gap-5 items-start">
        <div className="card p-3">
          <Skeleton className="h-[46vh]" />
        </div>
        <div className="card">
          <TableSkeleton rows={10} cols={6} />
        </div>
      </div>
    </div>
  );
}
