import { ArrowRight, Certificate, CheckCircle, FileXls, GitDiff, ShieldWarning, Warning } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { RunSharing } from "../components/RunSharing";
import { api } from "../api";
import { Badge, ClassificationBadge, SeverityBadge, StateBadge } from "../components/Badges";
import { ErrorBox } from "../components/Feedback";
import { Bar, CLASS_COLORS, Stat } from "../components/Stat";
import { AnchorButton, Button, Card, CardHead, LinkButton, PageHeader, Skeleton } from "../components/ui";
import { enc, fmtBytes, fmtDate, issueLabel, shortSha } from "../lib/format";
import { useDataRefresh } from "../lib/dataRefresh";
import { useToast } from "../lib/toast";
import { errorMessage, useAsync } from "../lib/useAsync";
import { CHECK_TYPES, CLASSIFICATIONS, DOC_TYPES, REVIEW_STATES, type VerifyOutcome } from "../types";

const CHECK_LABEL: Record<string, string> = { BOM_LABEL: "BOM to label", BOM_DRAWING: "BOM to drawing", LABEL_DRAWING: "Label to drawing", PCO_BOM: "PCO to BOM", LABEL_REVISION: "Label revision" };

export default function DashboardPage() {
  const { runId = "" } = useParams();
  const toast = useToast();
  const run = useAsync(() => api.getRun(runId), [runId]);
  useDataRefresh(run.reload, runId);
  const [verify, setVerify] = useState<VerifyOutcome | null>(null);
  const [verifyErr, setVerifyErr] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const verifyRequest = useRef(0);
  useEffect(() => { verifyRequest.current += 1; setVerify(null); setVerifyErr(null); setVerifying(false); }, [runId]);

  if (run.error) return <ErrorBox error={run.error} onRetry={run.reload} />;
  if (!run.data) return <DashboardSkeleton />;
  const r = run.data;
  const base = `/runs/${enc(runId)}`;
  const queue = (params: Record<string, string>) => `${base}/review?${new URLSearchParams(params).toString()}`;

  const progress = r.review_progress;
  const typeRows = progress.discrepancies;
  const coverageIssues = r.coverage.filter((c) => c.status !== "OK");
  const reviewable = r.reviewable_rows ?? r.rows;
  const flagged = progress.pending;
  const clearedPct = reviewable ? Math.round((100 * r.auto_cleared) / reviewable) : 0;
  const verdict = progress.blockers > 0 || coverageIssues.some(c => c.status.startsWith("MISSING"))
    ? { tone: "bad" as const, label: "Blocked", icon: <ShieldWarning size={14} weight="fill" /> }
    : r.rows === 0
    ? { tone: "warn" as const, label: "Not checked", icon: <Warning size={14} weight="fill" /> }
    : flagged > 0 || r.unrecognised_files.length > 0
    ? { tone: "warn" as const, label: "Needs review", icon: <Warning size={14} weight="fill" /> }
    : progress.unresolved_rows > 0
    ? { tone: "warn" as const, label: "Discrepancies confirmed", icon: <Warning size={14} weight="fill" /> }
    : { tone: "ok" as const, label: "Cleared", icon: <CheckCircle size={14} weight="fill" /> };

  const doVerify = async () => {
    const requestId = ++verifyRequest.current;
    setVerifying(true);
    setVerifyErr(null);
    try {
      const out = await api.verifyAndClose(runId);
      if (requestId !== verifyRequest.current) return;
      setVerify(out);
      toast({ tone: out.resolved.length ? "ok" : "info", title: `${out.resolved.length} action item${out.resolved.length === 1 ? "" : "s"} resolved`, description: `${out.still_open.length} still open · ${out.not_covered.length} not covered by this run` });
    } catch (e) {
      if (requestId === verifyRequest.current) setVerifyErr(errorMessage(e));
    } finally {
      if (requestId === verifyRequest.current) setVerifying(false);
    }
  };

  return (
    <div>
      <PageHeader
        className="overview-heading"
        title={
          <>
            <span>Overview</span>
            <Badge tone={verdict.tone} dot={false} size="md">
              {verdict.icon}
              {verdict.label}
            </Badge>
          </>
        }
        meta={
          <>
            {r.name && <span>{r.name}</span>}
            <span>{fmtDate(r.timestamp)}</span>
            <span>{r.skus} SKUs</span>
            <span>{r.documents} documents</span>
            {/* The input folder is deliberately not shown here: it is the widest thing on the line,
                a reviewer never needs it mid-review, and it is an absolute local path. It stays
                recorded in the workbook's run-info sheet and on the certificate. */}
          </>
        }
        description="Results and review status for this run."
        actions={<div className="overview-review-action">
          <LinkButton variant="primary" to={queue({ nv: "1" })} iconRight={<ArrowRight size={16} />}>Review queue <span className="queue-count">{flagged}</span></LinkButton>
          <span>{flagged ? "Awaiting review or approval" : "No pending reviews"}</span>
        </div>}
      />
      <details className="run-management">
        <summary>Run settings and exports</summary>
        <RunSharing key={runId} run={r} onChanged={run.reload} />
        <div className="flex flex-wrap gap-2 pb-3">
            <Button disabled={r.permission === "view"} variant="ghost" onClick={doVerify} loading={verifying} title="Check action items belonging to this run">
              Verify and close
            </Button>
            <LinkButton to={`${base}/diff`} icon={<GitDiff size={16} />} title="Resolved, new and still-open discrepancies against an earlier run">
              Compare runs
            </LinkButton>
            {r.permission !== "view" && <>
            <AnchorButton href={api.certificateUrl(runId)} download icon={<Certificate size={16} />} title="One page per SKU: run id, file hashes, counts, named reviewers, open action items">
              Certificate
            </AnchorButton>
            <AnchorButton href={api.exportUrl(runId)} download icon={<FileXls size={16} />}>
              Export workbook
            </AnchorButton>
            </>}
        </div>
      </details>

      <div className="space-y-5 stagger">
        {verifyErr && <ErrorBox error={verifyErr} />}
        {verify && (
          <Card>
            <CardHead title="Verify and close" description="Check whether this run resolves any open action items." />
            <div className="grid md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-line">
              <Outcome tone="ok" label="Resolved" ids={verify.resolved} note="No longer reported in this run." />
              <Outcome tone="bad" label="Still open" ids={verify.still_open} note="Still reported in this run." />
              <Outcome tone="neutral" label="Not covered" ids={verify.not_covered} note="No matching comparison in this run." />
            </div>
          </Card>
        )}

        {/* ---- the picture: what the engine cleared, what needs a person */}
        <Card>
          <div className="grid md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-line">
            <div className="p-5">
              <div className="text-sm font-medium text-ink-2">Auto-cleared</div>
              <div className="flex items-baseline gap-3 mt-1">
                <span className="num text-4xl font-semibold text-ok-strong">{r.auto_cleared}</span>
                <span className="text-sm text-ink-3">{clearedPct}% of {reviewable} reviewable</span>
              </div>
              <p className="text-sm text-ink-3 mt-2">
                Original automated results. <Link className="whitespace-nowrap" to={queue({ nv: "0", engine_classification: "EXACT" })}>View exact matches</Link>.
              </p>
            </div>
            <div className="p-5">
              <div className="text-sm font-medium text-ink-2">Needs review</div>
              <div className="flex items-baseline gap-3 mt-1">
                <span className="num text-4xl font-semibold text-bad-strong" data-testid="pending-reviews">{flagged}</span>
              </div>
              <p className="text-sm text-ink-3 mt-2">{progress.awaiting_review} not reviewed · {progress.awaiting_approval} awaiting approval. <Link className="whitespace-nowrap" to={queue({ nv: "1" })}>Open review queue</Link>.</p>
              <div className="flex flex-wrap gap-1.5 mt-2">
                <Badge tone={progress.blockers ? "bad" : "neutral"}>
                  {progress.blockers} blocker{progress.blockers === 1 ? "" : "s"}
                </Badge>
                <Badge tone={progress.low_confidence_rows ? "warn" : "neutral"}>
                  {progress.low_confidence_rows} low-confidence
                </Badge>
                {progress.needs_information > 0 && <Badge tone="warn">{progress.needs_information} need more information</Badge>}
              </div>
            </div>
            <div className="p-5">
              <div className="text-sm font-medium text-ink-2">Approved</div>
              <div className="num text-4xl font-semibold text-ok-strong mt-1" data-testid="approved-reviews">{progress.approved}</div>
              <p className="text-sm text-ink-3 mt-2">{progress.confirmed_discrepancies} with confirmed discrepancies. <Link to={queue({ nv: "0", state: "FINALIZED" })}>View approved rows</Link>.</p>
            </div>
          </div>
        </Card>

        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          <Stat label="SKUs" value={r.skus} />
          <Stat label="Documents" value={r.documents} sub={DOC_TYPES.map((t) => `${t} ${r.documents_by_type[t] ?? 0}`).join(" · ")} />
          <Stat label="Comparisons" value={r.rows} sub={r.reviewable_rows !== undefined ? `${r.reviewable_rows} reviewable · ${r.exempt_rows ?? 0} exempt` : undefined} />
          <Stat label="Blockers" value={progress.blockers} tone={progress.blockers ? "bad" : "good"} />
          <Stat label="Coverage issues" value={coverageIssues.length} tone={coverageIssues.length ? "bad" : "good"} sub="Missing or incomplete SKU sets" />
          <Stat label="Unrecognised files" value={r.unrecognised_files.length} tone={r.unrecognised_files.length ? "warn" : "neutral"} />
        </div>

        <div className="grid xl:grid-cols-2 gap-5">
          <Card>
            <CardHead title="Open discrepancies" count={`${progress.unresolved_rows} comparisons`} />
            {progress.confirmed_discrepancies > 0 && <p className="px-5 pt-3 text-sm text-ink-3">Includes {progress.confirmed_discrepancies} approved rows with confirmed findings that still need correction.</p>}
            {typeRows.length === 0 && <div className="p-5 text-sm text-ink-3">No open discrepancies.</div>}
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
                    {typeRows.map((v) => (
                      <tr key={v.type}>
                        <td>
                          <SeverityBadge value={v.severity} />
                        </td>
                        <td title={v.type}>{issueLabel(v.type)}</td>
                        <td className="text-right num font-medium">{v.count}</td>
                        <td className="text-right">
                          <Link to={queue({ discrepancy: v.type, unresolved: "1", nv: "0" })}>open</Link>
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
              <CardHead title="Automated results" count={`${reviewable} reviewable comparisons`} />
              <div className="p-5">
                <p className="text-xs text-ink-3 mb-3">Original engine recommendations, recorded before review. Approvals appear in the review status above.</p>
                <Bar segments={CLASSIFICATIONS.map((c) => ({ label: c, value: r.counts[c] ?? 0, color: CLASS_COLORS[c] }))} />
                <div className="flex flex-wrap gap-1.5 mt-3">
                  {CLASSIFICATIONS.map((c) => (
                    <Link key={c} className="no-underline" to={queue({ engine_classification: c, nv: "0" })}>
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
                <CardHead title="Review status" />
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
            <CardHead title="Document coverage" count={`${coverageIssues.length} issue${coverageIssues.length === 1 ? "" : "s"}`} />
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
            <CardHead title="Extraction warnings" count={r.parser_warnings.reduce((n, p) => n + p.warnings.length, 0)} />
            {r.parser_warnings.length === 0 ? (
              <div className="p-5 text-sm text-ink-3">No extraction warnings.</div>
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
            <div className="run-record-details p-5 grid lg:grid-cols-2 gap-6 text-sm">
              <div className="space-y-5">
                <dl className="kv"><dt>Run ID</dt><dd className="mono">{r.run_id}</dd><dt>Tool version</dt><dd>{r.tool_version}</dd><dt>Terminology version</dt><dd className="mono">{shortSha(r.terminology_version)}</dd><dt>Relationships</dt><dd>{r.terminology_count}</dd></dl>
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
