// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { GroundTruthPanel } from "./GroundTruthPanel";
import { api } from "../api";
import type { Annotation, LearningRow } from "../learning";
import type { RowDetail } from "../types";

const reviewer = {session: {is_admin: true}, name: "verifier@bd.com"};
vi.mock("../lib/reviewer", () => ({useReviewer: () => reviewer}));
vi.mock("../api", () => ({api: {learning: {row: vi.fn(), annotate: vi.fn(), approve: vi.fn()}}}));

const detail = {permission: "edit", revision: 7, result: {source_a: {id: "bom-mask"}, source_b: {id: "label-mask"}, classification: "EQUIVALENT", discrepancies: []}} as unknown as RowDetail;
const data: LearningRow = {enabled: true, split: "train", annotation: null,
  a_options: [{id: "bom-mask", doc_id: "bom", description: "Mask", item_number: "100", quantity: "1", page: 1, suggested_attributes: {component_type: "mask", dimensions_mm: [], gauge: null, concentration_pct: null, pack_quantity: null}}],
  b_options: [{id: "label-mask", doc_id: "label", description: "Mask", item_number: null, quantity: "1", page: 1, suggested_attributes: {component_type: "mask", dimensions_mm: [], gauge: null, concentration_pct: null, pack_quantity: null}}]};

function show(row = detail) {
  return render(<MemoryRouter><GroundTruthPanel runId="run" rowId="row" detail={row} /></MemoryRouter>);
}

beforeEach(() => {vi.clearAllMocks(); reviewer.session.is_admin = true; vi.mocked(api.learning.row).mockResolvedValue(data); vi.mocked(api.learning.annotate).mockResolvedValue({} as Annotation);});
afterEach(cleanup);

describe("ground-truth review", () => {
  it("saves explicit ground truth with revisions, without silently verifying suggested attributes", async () => {
    show();
    await screen.findByLabelText("What did you verify?");
    fireEvent.change(screen.getByLabelText("What did you verify?"), {target: {value: "CORRECT_PAIR"}});
    fireEvent.change(screen.getByLabelText("Evidence and reason"), {target: {value: "Verified both source pages."}});
    fireEvent.click(screen.getByRole("button", {name: "Save annotation"}));
    await waitFor(() => expect(api.learning.annotate).toHaveBeenCalledWith("run", "row", expect.objectContaining({expected_version: 0, review_revision: 7,
      verdict: "CORRECT_PAIR", expected_a_ids: ["bom-mask"], expected_b_ids: ["label-mask"], attributes: {}})));
  });

  it("requires saving edits before an administrator verifies the saved annotation", async () => {
    const annotation = {version: 1, status: "pending", annotated_by: "tester@bd.com", approved_by: "", payload: {verdict: "CORRECT_PAIR", classification: "EQUIVALENT",
      expected_a_ids: ["bom-mask"], expected_b_ids: ["label-mask"], discrepancies: [], attributes: {}, assembly_quantities: {}, note: "Verified source pages."}} as unknown as Annotation;
    vi.mocked(api.learning.row).mockResolvedValue({...data, annotation});
    show();
    const verify = await screen.findByRole("button", {name: "Verify saved annotation"});
    await waitFor(() => expect((verify as HTMLButtonElement).disabled).toBe(false));
    fireEvent.change(screen.getByLabelText("Evidence and reason"), {target: {value: "Edited evidence note."}});
    expect((verify as HTMLButtonElement).disabled).toBe(true);
    expect(api.learning.approve).not.toHaveBeenCalled();
  });

  it("keeps view-only reviewers from changing ground truth", async () => {
    show({...detail, permission: "view"});
    const decision = await screen.findByLabelText("What did you verify?");
    expect(decision.closest("fieldset")?.disabled).toBe(true);
    expect(screen.queryByRole("button", {name: "Save annotation"})).toBeNull();
  });

  it("lets a reviewer enter decimal dimensions without rewriting partially typed text", async () => {
    show();
    await screen.findByLabelText("What did you verify?");
    fireEvent.click(screen.getByText("Component attributes"));
    fireEvent.click(screen.getByRole("checkbox", {name: "I checked these attributes against the sources."}));
    const dimensions = screen.getAllByLabelText("Dimensions in mm (comma separated)")[0] as HTMLInputElement;
    fireEvent.change(dimensions, {target: {value: "101.6,"}});
    expect(dimensions.value).toBe("101.6,");
    fireEvent.change(dimensions, {target: {value: "101.6, 101.6"}});
    fireEvent.change(screen.getByLabelText("Evidence and reason"), {target: {value: "Verified dimensions on source."}});
    fireEvent.click(screen.getByRole("button", {name: "Save annotation"}));
    await waitFor(() => expect(api.learning.annotate).toHaveBeenCalledWith("run", "row", expect.objectContaining({attributes: expect.objectContaining({"bom-mask": expect.objectContaining({dimensions_mm: [101.6, 101.6]})})})));
  });
});
