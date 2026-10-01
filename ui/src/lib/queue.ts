// The review-queue filter state lives in the URL query string so the evidence view can navigate
// prev/next within the same filtered set and the browser back button returns to the same page.
import type { ResultsQuery, ViewerParams } from "../types";

export const PAGE_SIZE = 100;

export const QUEUE_PARAM_KEYS = ["sku", "check", "discrepancy", "severity", "classification", "engine_classification", "unresolved", "state", "role", "nv", "q", "offset"];

// `v` is not sent to the server (the session decides visibility); it stays in the signature so callers
// re-run the query when the signed-in reviewer changes.
export function queueQueryFromParams(sp: URLSearchParams, _v: ViewerParams, overrides: Partial<ResultsQuery> = {}): ResultsQuery {
  return {
    sku: sp.get("sku") || undefined,
    check: sp.get("check") || undefined,
    discrepancy: sp.get("discrepancy") || undefined,
    severity: sp.get("severity") || undefined,
    classification: sp.get("classification") || undefined,
    engine_classification: sp.get("engine_classification") || undefined,
    unresolved: sp.has("unresolved") ? sp.get("unresolved") === "1" : undefined,
    state: sp.get("state") || undefined,
    role: sp.get("role") || undefined,
    // Pending review is ON by default; "nv=0" shows every row, including approvals.
    needs_validation: sp.get("nv") === "0" ? undefined : true,
    search: sp.get("q") || undefined,
    limit: PAGE_SIZE,
    offset: Number.isSafeInteger(Number(sp.get("offset"))) ? Math.max(0, Number(sp.get("offset"))) : 0,
    ...overrides,
  };
}

/** Only the queue-related params, so links stay short. */
export function queueParams(sp: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams();
  for (const k of QUEUE_PARAM_KEYS) {
    const v = sp.get(k);
    if (v) out.set(k, v);
  }
  return out;
}
