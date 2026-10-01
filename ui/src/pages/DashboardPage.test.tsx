// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { RunSummary } from "../types";
import DashboardPage from "./DashboardPage";

vi.mock("../components/RunSharing", () => ({ RunSharing: () => null }));
vi.mock("../lib/toast", () => ({ useToast: () => vi.fn() }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });

function summary(): RunSummary {
  return {
    run_id: "run", name: "Test project", owner: "test@bd.com", permission: "owner", copied_from: "",
    timestamp: "2026-10-01T00:00:00Z", input_root: "source", tool_version: "0.1.0", skus: 1, documents: 2,
    documents_by_type: { BOM: 1, LABEL: 1, DRAWING: 0, PCO: 0 }, unrecognised_files: [], rows: 12,
    reviewable_rows: 12, exempt_rows: 0, header_rows_needing_validation: 0,
    counts: { EXACT: 0, EQUIVALENT: 0, POTENTIAL: 0, MISMATCH: 12, MISSING: 0 }, needs_validation: 12, auto_cleared: 0,
    per_check: { BOM_LABEL: 12, BOM_DRAWING: 0, LABEL_DRAWING: 0, PCO_BOM: 0, LABEL_REVISION: 0 },
    blockers: 0, coverage: [], groups: [], warnings: [], parser_warnings: [], low_confidence_rows: 0,
    state_counts: { ENGINE_RECOMMENDED: 12, REVIEWED: 0, FINALIZED: 0, REVIEWER_1_COMPLETE: 0, REVIEWER_2_COMPLETE: 0, AGREED: 0, DISAGREEMENT: 0 },
    review_progress: { pending: 12, awaiting_review: 12, awaiting_approval: 0, approved: 0, needs_information: 0,
      unresolved_rows: 12, confirmed_discrepancies: 0, blockers: 0, low_confidence_rows: 0,
      discrepancies: [{ type: "QTY_MISMATCH", count: 12, severity: "MAJOR" }] },
    terminology_version: "version", terminology_count: 0, relationships_used: [], capabilities: {}, thresholds: {}, inputs: [],
  };
}

function show() {
  const router = createMemoryRouter([{ path: "/runs/:runId", element: <DashboardPage /> }], { initialEntries: ["/runs/run"] });
  render(<RouterProvider router={router} />);
  return router;
}

describe("overview review progress", () => {
  it("updates after approval without using a second, truncated queue request", async () => {
    const data = summary();
    const fetch = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/runs/run") return new Response(JSON.stringify(data));
      if (path === "/api/runs/run/finalize" && init?.method === "POST") {
        data.review_progress.pending = 11;
        data.review_progress.awaiting_review = 11;
        data.review_progress.approved = data.state_counts.FINALIZED = 1;
        data.review_progress.unresolved_rows = data.review_progress.discrepancies[0].count = 11;
        return new Response('{}');
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetch);
    show();
    await waitFor(() => expect(screen.getByTestId("pending-reviews").textContent).toBe("12"));
    await act(async () => { await api.finalize("run", { row_id: "row", final_decision: "OVERRIDE", expected_revision: 1, confirm_self_approval: true }); });
    await waitFor(() => expect(screen.getByTestId("pending-reviews").textContent).toBe("11"));
    expect(screen.getByTestId("approved-reviews").textContent).toBe("1");
    expect(screen.getByRole("img", { name: /MISMATCH 12/ })).toBeTruthy();
    expect(fetch.mock.calls.every(([path]) => !path.includes("/results"))).toBe(true);
  });

  it("keeps approved confirmed findings visible and does not claim the run is cleared", async () => {
    const data = summary();
    data.review_progress.pending = data.review_progress.awaiting_review = 0;
    data.review_progress.approved = data.review_progress.confirmed_discrepancies = 1;
    data.state_counts.FINALIZED = 1;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(data))));
    show();
    await screen.findByText("Discrepancies confirmed");
    expect(screen.getByTestId("pending-reviews").textContent).toBe("0");
    expect(screen.getByTestId("approved-reviews").textContent).toBe("1");
    expect(screen.getByText(/approved rows with confirmed findings that still need correction/)).toBeTruthy();
    const link = screen.getAllByRole("link", { name: "open" }).find(a => a.getAttribute("href")?.includes("QTY_MISMATCH"));
    expect(link?.getAttribute("href")).toContain("unresolved=1");
  });

  it("uses current blockers while preserving the original automated count", async () => {
    const data = summary();
    data.blockers = 12;
    data.review_progress.pending = data.review_progress.awaiting_review = data.review_progress.unresolved_rows = 0;
    data.review_progress.approved = data.state_counts.FINALIZED = 12;
    data.review_progress.discrepancies = [];
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(data))));
    show();
    await screen.findByText("Cleared");
    expect(screen.getByTestId("approved-reviews").textContent).toBe("12");
    expect(screen.getByText("No open discrepancies.")).toBeTruthy();
  });

  it("does not show a previous run's late verification result", async () => {
    let resolve!: (response: Response) => void;
    const late = new Promise<Response>(done => { resolve = done; });
    vi.stubGlobal("fetch", vi.fn(async (path: string) => path.endsWith("/verify-and-close") ? late : new Response(JSON.stringify(summary()))));
    const router = show();
    const button = await screen.findByRole("button", { name: "Verify and close" });
    act(() => button.click());
    await act(async () => { await router.navigate("/runs/other"); });
    await act(async () => resolve(new Response(JSON.stringify({ resolved: ["old-action"], still_open: [], not_covered: [] }))));
    expect(screen.queryByText("old-action")).toBeNull();
  });
});
