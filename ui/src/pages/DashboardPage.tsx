import { ArrowRight, Certificate, CheckCircle, FileXls, GitDiff, ShieldWarning, Warning } from "@phosphor-icons/react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, ClassificationBadge, SeverityBadge, StateBadge } from "../components/Badges";
import { ErrorBox, Loading } from "../components/Feedback";
import { Bar, CLASS_COLORS, Stat } from "../components/Stat";
import { AnchorButton, Button, Card, CardHead, LinkButton, PageHeader, Skeleton } from "../components/ui";
import { enc, fmtBytes, fmtDate, shortSha } from "../lib/format";
import { useReviewer } from "../lib/reviewer";
import { useToast } from "../lib/toast";
import { errorMessage, useAsync } from "../lib/useAsync";
import { CHECK_TYPES, CLASSIFICATIONS, DOC_TYPES, REVIEW_STATES, type Severity, type VerifyOutcome } from "../types";

const SEV_RANK: Record<Severity, number> = { BLOCKER: 0, MAJOR: 1, MINOR: 2, INFO: 3 };
const CHECK_LABEL: Record<string, string> = { BOM_LABEL: "BOM to label", BOM_DRAWING: "BOM to drawing", LABEL_DRAWING: "Label to drawing", PCO_BOM: "PCO to BOM", LABEL_REVISION: "Label revision" };

export default function DashboardPage() {
  const { runId = "" } = useParams();
  const { viewerParams } = useReviewer();
  const toast = useToast();
  const run = useAsync(() => api.getRun(runId), [runId]);
  // Rows needing validation, to list unresolved discrepancies by type (cheap: a few hundred rows).
  const nv = useAsync(
    () => api.getResults(runId, { needs_validation: true, limit: 5000, viewer: viewerParams.viewer, blind: viewerParams.blind || undefined }),
    [runId, viewerParams.viewer, viewerParams.blind],
  );
  const [verify, setVerify] = useState<VerifyOutcome | null>(null);
  const [verifyErr, setVerifyErr] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);

  if (run.error) return <ErrorBox error={run.error} onRetry={run.reload} />;
  if (!run.data) return <DashboardSkeleton />;
  const r = run.data;
  const base = `/runs/${enc(runId)}`;
  const queue = (params: Record<string, string>) => `${base}/review?${new URLSearchParams(params).toString()}`;

  const rows = nv.data?.rows ?? [];
  const unresolved = rows.filter((x) => x.discrepancies.length > 0 && x.state !== "FINALIZED");
  const byType = new Map<string, { count: number; top: Severity }>();
  for (const x of unresolved) {
    for (const d of x.discrepancies) {
      const cur = byType.get(d.type);
      if (!cur) byType.set(d.type, { count: 1, top: d.severity });
      else {
        cur.count += 1;
        if (SEV_RANK[d.severity] < SEV_RANK[cur.top]) cur.top = d.severity;
      }
    }
  }
  const typeRows = [...byType.entries()].sort((a, b) => SEV_RANK[a[1].top] - SEV_RANK[b[1].top] || b[1].count - a[1].count);
  const coverageIssues = r.coverage.filter((c) => c.status !== "OK");
  const untouched = rows.filter((x) => x.state === "ENGINE_RECOMMENDED").length;
  const reviewable = r.reviewable_rows ?? r.rows;
  const headerNeeds = r.header_rows_needing_validation ?? 0;
  const disagreements = r.state_counts.DISAGREEMENT ?? 0;
  const clearedPct = reviewable ? Math.round((100 * r.auto_cleared) / reviewable) : 0;
  const verdict = r.blockers > 0 ? { tone: "bad" as const, label: "Blocked", icon: <ShieldWarning size={14} weight="fill" /> } : r.needs_validation > 0 ? { tone: "warn" as const, label: "Needs review", icon: <Warning size={14} weight="fill" /> } : { tone: "ok" as const, label: "Cleared", icon: <CheckCircle size={14} weight="fill" /> };

  const doVerify = async () => {
    setVerifying(true);
    setVerifyErr(null);
    try {
      const out = await api.verifyAndClose(runId);
      setVerify(out);
      toast({ tone: out.resolved.length ? "ok" : "info", title: `${out.resolved.length} action item${out.resolved.length === 1 ? "" : "s"} resolved`, description: `${out.still_open.length} still open · ${out.not_covered.length} not covered by this run` });
    } catch (e) {
      setVerifyErr(errorMessage(e));
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div>
      <PageHeader
        title={
          <>
            <span className="mono text-xl whitespace-nowrap">{r.run_id}</span>
            <Badge tone={verdict.tone} dot={false} size="md">
              {verdict.icon}
              {verdict.label}
            </Badge>
          </>
        }
        meta={
          <>
            <span>{fmtDate(r.timestamp)}</span>
            <span>tool {r.tool_version}</span>
            <span>
              terminology <span className="mono" title={r.terminology_version}>{shortSha(r.terminology_version)}</span> · {r.terminology_count} relationships
            </span>
            {/* The input folder is deliberately not shown here: it is the widest thing on the line,
                a reviewer never needs it mid-review, and it is an absolute local path. It stays
                recorded in the workbook's run-info sheet and on the certificate. */}
          </>
        }
        actions={
          <>
            <Button variant="ghost" onClick={doVerify} loading={verifying} title="Match open action items from earlier runs against this run's results">
              Verify and close
            </Button>
            <LinkButton to={`${base}/diff`} icon={<GitDiff size={16} />} title="Resolved, new and still-open discrepancies against an earlier run">
              Compare runs
            </LinkButton>
            <AnchorButton href={api.certificateUrl(runId)} download icon={<Certificate size={16} />} title="One page per SKU: run id, file hashes, counts, named reviewers, open action items">
              Certificate
            </AnchorButton>
            <AnchorButton href={api.exportUrl(runId)} download icon={<FileXls size={16} />}>
              Export workbook
            </AnchorButton>
            <LinkButton variant="primary" to={queue({})} iconRight={<ArrowRight size={16} />}>
              Open review queue
            </LinkButton>
          </>
        }
      />

      <div className="space-y-5 stagger">
        {verifyErr && <ErrorBox error={verifyErr} />}
        {verify && (
          <Card>
            <CardHead title="Verify and close" description="Open action items matched against this run by comparison key, not by file name." />
            <div className="grid md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-line">
              <Outcome tone="ok" label="Resolved" ids={verify.resolved} note="The discrepancy is no longer present; the item is marked resolved in this run." />
              <Outcome tone="bad" label="Still open" ids={verify.still_open} note="The same comparison still shows the discrepancy." />
              <Outcome tone="neutral" label="Not covered" ids={verify.not_covered} note="This run has no comparison for the item (different SKU set)." />
            </div>
          </Card>
        )}

        {/* ---- the picture: what the engine cleared, what needs a person */}
        <Card>
          <div className="grid md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-line">
            <div className="p-5">
              <div className="text-sm font-medium text-ink-2">Auto-cleared by the engine</div>
              <div className="flex items-baseline gap-3 mt-1">
                <span className="num text-4xl font-semibold text-ok-strong">{r.auto_cleared}</span>
                <span className="text-sm text-ink-3">{clearedPct}% of {reviewable} reviewable</span>
              </div>
              <p className="text-sm text-ink-3 mt-2">
                Exact or equivalent with no discrepancy. Still recorded and auditable:{" "}
                <Link to={queue({ nv: "0", classification: "EXACT" })}>inspect them</Link>.
              </p>
            </div>
            <div className="p-5">
              <div className="text-sm font-medium text-ink-2">Needs human review</div>
              <div className="flex items-baseline gap-3 mt-1">
                <span className="num text-4xl font-semibold text-bad-strong">{r.needs_validation}</span>
                <span className="text-sm text-ink-3">{nv.data ? `${untouched} not yet opened` : "…"}</span>
              </div>
              <div className="flex flex-wrap gap-1.5 mt-2">
                <Badge tone={r.blockers ? "bad" : "neutral"}>
                  {r.blockers} blocker{r.blockers === 1 ? "" : "s"}
                </Badge>
                <Badge tone={r.low_confidence_rows ? "warn" : "neutral"}>
                  {r.low_confidence_rows} low-confidence
                </Badge>
                {disagreements > 0 && <Badge tone="bad">{disagreements} disagreement{disagreements === 1 ? "" : "s"}</Badge>}
                {headerNeeds > 0 && <Badge tone="neutral">{headerNeeds} header or coverage rows</Badge>}
              </div>
            </div>
          </div>
          <div className="px-5 pb-5 pt-1">
            <Bar key={r.run_id} animate height={12} segments={[{ label: "Auto-cleared", value: r.auto_cleared, color: CLASS_COLORS.EXACT }, { label: "Needs human review", value: r.needs_validation, color: CLASS_COLORS.MISMATCH }]} />
            {(r.exempt_rows ?? 0) > 0 && <p className="text-xs text-ink-3 mt-2">Not counted above: {r.exempt_rows} exempt rows (non-physical BOM lines such as labels and process steps), listed in the queue and the workbook for traceability.</p>}
          </div>
        </Card>

        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          <Stat label="SKUs" value={r.skus} />
          <Stat label="Documents" value={r.documents} sub={DOC_TYPES.map((t) => `${t} ${r.documents_by_type[t] ?? 0}`).join(" · ")} />
          <Stat label="Comparisons" value={r.rows} sub={r.reviewable_rows !== undefined ? `${r.reviewable_rows} reviewable · ${r.exempt_rows ?? 0} exempt` : undefined} />
          <Stat label="Blockers" value={r.blockers} tone={r.blockers ? "bad" : "good"} />
          <Stat label="Coverage issues" value={coverageIssues.length} tone={coverageIssues.length ? "bad" : "good"} sub="a BOM for every PCO affected code" />
          <Stat label="Unrecognised files" value={r.unrecognised_files.length} tone={r.unrecognised_files.length ? "warn" : "neutral"} />
        </div>

        <div className="grid xl:grid-cols-2 gap-5">
          <Card>
            <CardHead title="Open discrepancies by type" count={nv.loading ? "counting…" : `${unresolved.length} rows not finalized`} />
            {nv.error && (
              <div className="p-4">
                <ErrorBox error={nv.error} onRetry={nv.reload} />
              </div>
            )}
            {nv.loading && !nv.data && (
              <div className="p-4">
                <Loading lines={4} />
              </div>
            )}
            {typeRows.length === 0 && !nv.loading && !nv.error && <div className="p-5 text-sm text-ink-3">No open discrepancies.</div>}
            {typeRows.length > 0 && (
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Severity</th>
                      <th>Discrepancy</th>
                      <th className="text-right">Rows</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {typeRows.map(([t, v]) => (
                      <tr key={t}>
                        <td>
                          <SeverityBadge value={v.top} />
                        </td>
                        <td className="mono">{t}</td>
                        <td className="text-right num font-medium">{v.count}</td>
                        <td className="text-right">
                          <Link to={queue({ discrepancy: t, nv: "0" })}>open</Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {r.warnings.length > 0 && (
              <div className="border-t border-line px-5 py-4">
                <div className="text-sm font-medium text-ink mb-1.5">Run warnings</div>
                <ul className="text-sm space-y-1">
                  {r.warnings.map((w, i) => (
                    <li key={i} className={`flex gap-2 ${/BLOCKER/.test(w) ? "text-bad-strong font-medium" : "text-ink-2"}`}>
                      <Warning size={16} className={`shrink-0 mt-0.5 ${/BLOCKER/.test(w) ? "text-bad" : "text-warn"}`} />
                      <span>{w}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>

          <div className="space-y-5">
            <Card>
              <CardHead title="Engine classification" count={`${r.rows} comparisons`} />
              <div className="p-5">
                <Bar segments={CLASSIFICATIONS.map((c) => ({ label: c, value: r.counts[c] ?? 0, color: CLASS_COLORS[c] }))} />
                <div className="flex flex-wrap gap-1.5 mt-3">
                  {CLASSIFICATIONS.map((c) => (
                    <Link key={c} className="no-underline" to={queue({ classification: c, nv: "0" })}>
                      <ClassificationBadge value={c} />
                    </Link>
                  ))}
                </div>
              </div>
            </Card>
            <div className="grid md:grid-cols-2 gap-5">
              <Card>
                <CardHead title="By check" />
                <div className="overflow-x-auto">
                  <table className="tbl">
                    <tbody>
                      {CHECK_TYPES.map((c) => (
                        <tr key={c}>
                          <td>{CHECK_LABEL[c] ?? c}</td>
                          <td className="text-right num">{r.per_check[c] ?? 0}</td>
                          <td className="text-right">
                            <Link to={queue({ check: c })}>review</Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <Card>
                <CardHead title="Review state" />
                <div className="overflow-x-auto">
                  <table className="tbl">
                    <tbody>
                      {REVIEW_STATES.map((s) => (
                        <tr key={s}>
                          <td>
                            <StateBadge value={s} />
                          </td>
                          <td className="text-right num">{r.state_counts[s] ?? 0}</td>
                          <td className="text-right">
                            <Link to={queue({ state: s, nv: "0" })}>open</Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          </div>
        </div>

        <div className="grid xl:grid-cols-2 gap-5">
          <Card>
            <CardHead title="PCO coverage and SKU sets" count={`${coverageIssues.length} issue${coverageIssues.length === 1 ? "" : "s"}`} />
            <div className="max-h-80 overflow-auto">
              <div className="overflow-x-auto">
                {/* A min width so the card scrolls sideways instead of squeezing `source` down to
                    one character per line; the source paths wrap on separators, not mid-token. */}
                <table className="tbl min-w-[52rem]">
                  <thead>
                    <tr>
                      <th>Status</th>
                      <th>Kind</th>
                      <th>SKU</th>
                      <th className="min-w-[20rem]">Detail</th>
                      <th className="min-w-[14rem]">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...r.coverage]
                      .sort((a, b) => (a.status === "OK" ? 1 : 0) - (b.status === "OK" ? 1 : 0))
                      .map((c, i) => {
                        const bad = c.status.startsWith("MISSING");
                        return (
                          <tr key={i} className={bad ? "bg-bad-soft/40" : ""}>
                            <td>{bad ? <SeverityBadge value="BLOCKER" /> : <Badge tone="ok">OK</Badge>}</td>
                            <td className="text-ink-3">{c.kind.replace(/_/g, " ")}</td>
                            <td className="mono">{c.sku}</td>
                            <td className={bad ? "text-bad-strong font-medium" : ""}>{c.detail}</td>
                            <td className="mono text-ink-3 break-words">{c.source}</td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </div>
          </Card>
          <Card>
            <CardHead title="Parser warnings" count={r.parser_warnings.reduce((n, p) => n + p.warnings.length, 0)} />
            {r.parser_warnings.length === 0 ? (
              <div className="p-5 text-sm text-ink-3">No parser warnings. Every document was read without a caveat.</div>
            ) : (
              <div className="max-h-80 overflow-auto">
                <div className="overflow-x-auto">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Document</th>
                        <th>Warning</th>
                      </tr>
                    </thead>
                    <tbody>
                      {r.parser_warnings.flatMap((p) =>
                        p.warnings.map((w, i) => (
                          <tr key={`${p.doc_id}-${i}`}>
                            <td className="whitespace-nowrap">
                              <Link className="mono" to={`${base}/documents/${enc(p.doc_id)}`}>
                                {p.document}
                              </Link>
                            </td>
                            <td className="text-ink-2">{w}</td>
                          </tr>
                        )),
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            {r.unrecognised_files.length > 0 && (
              <div className="border-t border-line px-5 py-4">
                <div className="text-sm font-medium text-ink mb-1">Unrecognised files (ignored)</div>
                <ul className="mono text-xs text-ink-2 space-y-0.5">
                  {r.unrecognised_files.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        </div>

        <Card>
          <details className="group">
            <summary className="card-head cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden">
              <span className="card-title">Run record</span>
              <span className="text-xs text-ink-3">SKU groups, relationships used, thresholds, capabilities, input hashes</span>
              <span className="ml-auto text-xs text-ink-3 group-open:hidden">show</span>
              <span className="ml-auto text-xs text-ink-3 hidden group-open:inline">hide</span>
            </summary>
            <div className="p-5 grid lg:grid-cols-2 gap-6 text-sm">
              <div className="space-y-5">
                <div>
                  <div className="text-sm font-medium mb-2">SKU groups ({r.groups.length})</div>
                  <div className="overflow-x-auto">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>SKU</th>
                        <th>Family</th>
                        <th className="text-right">Docs</th>
                        <th>Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {r.groups.map((g) => (
                        <tr key={g.sku}>
                          <td>
                            <Link className="mono" to={queue({ sku: g.sku })}>
                              {g.sku}
                            </Link>
                          </td>
                          <td className="mono">{g.family}</td>
                          <td className="text-right num">{g.document_ids.length}</td>
                          <td className="text-warn-strong">{g.warnings.join("; ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  </div>
                </div>
                <div>
                  <div className="text-sm font-medium mb-2">Relationships used ({r.relationships_used.length})</div>
                  <div className="flex flex-wrap gap-1.5">
                    {r.relationships_used.map((id) => (
                      <Link key={id} className="chip mono no-underline hover:bg-brand-100" to={`/terminology?id=${enc(id)}`}>
                        {id}
                      </Link>
                    ))}
                    {r.relationships_used.length === 0 && <span className="text-ink-3">none</span>}
                  </div>
                </div>
                <div>
                  <div className="text-sm font-medium mb-2">Thresholds</div>
                  <dl className="kv">
                    {Object.entries(r.thresholds).map(([k, v]) => (
                      <div key={k} className="contents">
                        <dt className="mono">{k}</dt>
                        <dd className="num">{String(v)}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </div>
              <div className="space-y-5">
                <div>
                  <div className="text-sm font-medium mb-2">Capabilities</div>
                  <div className="overflow-x-auto">
                  <table className="tbl">
                    <tbody>
                      {Object.entries(r.capabilities).map(([k, v]) => (
                        <tr key={k}>
                          <td className="min-w-[14rem]">{k}</td>
                          <td className={`text-xs ${/^IMPLEMENTED/.test(v) ? "text-ok-strong" : "text-ink-3"}`}>{v}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  </div>
                </div>
                <div>
                  <div className="text-sm font-medium mb-2">Inputs ({r.inputs.length})</div>
                  <div className="max-h-64 overflow-auto">
                    <div className="overflow-x-auto">
                      <table className="tbl">
                        <thead>
                          <tr>
                            <th>Path</th>
                            <th>Type</th>
                            <th className="text-right">Size</th>
                            <th>SHA-256</th>
                          </tr>
                        </thead>
                        <tbody>
                          {r.inputs.map((f) => (
                            <tr key={f.path}>
                              <td className="mono break-all">{f.path}</td>
                              <td>{f.doc_type ?? <span className="text-warn-strong">unrecognised</span>}</td>
                              <td className="text-right num whitespace-nowrap">{fmtBytes(f.size_bytes)}</td>
                              <td className="mono text-ink-3" title={f.sha256}>
                                {shortSha(f.sha256, 16)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </details>
        </Card>
      </div>
    </div>
  );
}

function Outcome({ tone, label, ids, note }: { tone: "ok" | "bad" | "neutral"; label: string; ids: string[]; note: string }) {
  return (
    <div className="p-4">
      <div className="flex items-center gap-2">
        <Badge tone={tone}>{label}</Badge>
        <span className="num text-sm font-semibold">{ids.length}</span>
      </div>
      <p className="text-xs text-ink-3 mt-1 mb-2">{note}</p>
      {ids.length === 0 ? (
        <div className="text-ink-4 text-sm">—</div>
      ) : (
        <ul className="mono text-sm space-y-0.5">
          {ids.map((id) => (
            <li key={id}>
              <Link to={`/action-items?id=${enc(id)}`}>{id}</Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div aria-busy aria-label="Loading run">
      <div className="mb-5">
        <Skeleton className="h-7 w-72 mb-2" />
        <Skeleton className="h-3 w-96" />
      </div>
      <div className="card p-5 mb-5 grid md:grid-cols-2 gap-6">
        <div>
          <Skeleton className="h-3 w-40 mb-3" />
          <Skeleton className="h-10 w-28" />
        </div>
        <div>
          <Skeleton className="h-3 w-40 mb-3" />
          <Skeleton className="h-10 w-28" />
        </div>
        <Skeleton className="h-3 md:col-span-2" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="card px-4 py-3">
            <Skeleton className="h-3 w-16 mb-2" />
            <Skeleton className="h-7 w-12" />
          </div>
        ))}
      </div>
    </div>
  );
}
