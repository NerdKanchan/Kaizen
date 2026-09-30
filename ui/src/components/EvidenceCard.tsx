import { ArrowSquareOut, ArrowsOutSimple, ListMagnifyingGlass } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "../api";
import { enc, fmtQty, isPdf, shortSha } from "../lib/format";
import type { Evidence } from "../types";
import { Badge, DocTypeBadge } from "./Badges";
import { PageImage } from "./PageImage";
import { AnchorButton, Button, Card, CardHead, LinkButton } from "./ui";

interface Props {
  side: "A" | "B";
  runId: string;
  rowId: string;
  ev: Evidence | null;
  /** DocumentItem id (from the full result) so the document view can pre-select the row. */
  itemId?: string | null;
}

/** One side of a comparison: the source page with the value highlighted, and everything extracted from it. */
export function EvidenceCard({ side, runId, rowId, ev, itemId }: Props) {
  const [fit, setFit] = useState(true);
  if (!ev) {
    return (
      <Card>
        <CardHead title={`Source ${side}`} />
        <div className="p-5 text-sm text-ink-3">No matching item in this document.</div>
      </Card>
    );
  }
  const hasPage = ev.page !== null && isPdf(ev.file_name);
  const src = hasPage ? api.pageImageUrl(runId, ev.doc_id, ev.page as number, rowId) : null;
  const docLink = `/runs/${enc(runId)}/documents/${enc(ev.doc_id)}?page=${ev.page ?? 1}${itemId ? `&item=${enc(itemId)}` : ""}`;
  const lowConf = ev.confidence < 0.7;
  const fallback = (
    <div className="space-y-2 text-sm">
      <div className="text-ink-3">Spreadsheet source. Cell location and text:</div>
      <div className="mono">{ev.locator ?? "—"}</div>
      <pre className="mono whitespace-pre-wrap bg-surface-2 rounded-md p-3">{ev.raw_text}</pre>
    </div>
  );
  return (
    <Card>
      <CardHead
        title={
          <span className="flex items-center gap-2">
            Source {side}
            <DocTypeBadge value={ev.doc_type} />
          </span>
        }
        description={
          <span className="mono">
            {ev.file_name}
            {ev.page !== null && <span className="text-ink-3"> · page {ev.page}</span>}
          </span>
        }
        actions={
          <>
            {src && (
              <>
                <Button size="sm" variant="ghost" onClick={() => setFit(!fit)} icon={<ArrowsOutSimple size={14} />}>
                  {fit ? "Actual size" : "Fit width"}
                </Button>
                <AnchorButton size="sm" variant="ghost" href={src} target="_blank" rel="noreferrer" icon={<ArrowSquareOut size={14} />}>
                  Open page
                </AnchorButton>
              </>
            )}
            <LinkButton size="sm" variant="ghost" to={docLink} icon={<ListMagnifyingGlass size={14} />}>
              View document
            </LinkButton>
          </>
        }
      />
      <div className="p-3">
        <PageImage src={src} bbox={ev.bbox} fit={fit} alt={`${ev.file_name} page ${ev.page ?? ""}`} fallback={fallback} />
        {src && ev.bbox === null && <div className="text-xs text-ink-3 mt-2">No page highlight is available for this value.</div>}
      </div>
      <dl className="kv px-5 pb-5 pt-1">
        <dt>Description</dt>
        <dd className="font-medium">{ev.description}</dd>
        <dt>Item number</dt>
        <dd className="mono">{ev.item_number ?? "—"}</dd>
        <dt>Quantity</dt>
        <dd className="num">
          {fmtQty(ev.quantity)} {ev.uom ?? ""}
          {ev.sub_quantity && <span className="text-ink-3"> · sub-quantity {ev.sub_quantity.raw}</span>}
          {ev.oper_seq && <span className="text-ink-3"> · seq {ev.oper_seq}</span>}
        </dd>
        <dt>Locator</dt>
        <dd>
          {ev.locator ?? "—"}
          {ev.sheet ? <span className="text-ink-3"> · sheet {ev.sheet}</span> : null}
        </dd>
        <dt>Category</dt>
        <dd>
          {ev.category.replace(/_/g, " ").toLowerCase()}
          {ev.category_reason && <span className="text-ink-3"> · {ev.category_reason}</span>}
        </dd>
        <dt>Confidence</dt>
        <dd>
          {lowConf ? (
            <Badge tone="warn">{(ev.confidence * 100).toFixed(0)}% · verify against the page</Badge>
          ) : (
            <span className="num">{(ev.confidence * 100).toFixed(0)}%</span>
          )}
        </dd>
        <dt>Raw text</dt>
        <dd>
          <pre className="mono whitespace-pre-wrap bg-surface-2 rounded-md px-3 py-2">{ev.raw_text}</pre>
        </dd>
        <dt>File</dt>
        <dd className="mono text-ink-3 break-all text-xs">
          {ev.file}
          <br />
          sha256 {shortSha(ev.sha256, 16)}…
        </dd>
      </dl>
    </Card>
  );
}
