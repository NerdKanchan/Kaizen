// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ImportResult, TerminologySource } from "../types";
import { TerminologyImport } from "./TerminologyImport";

vi.mock("../lib/reviewer", () => ({ useReviewer: () => ({ name: "quality@bd.com" }) }));
vi.mock("../lib/toast", () => ({ useToast: () => vi.fn() }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const source: TerminologySource = {
  sheets: ["CSV"], sheet: "CSV", header_row: 1, columns: ["Canonical", "Aliases"], row_count: 1,
  sample: [{ row: 2, values: { Canonical: "Cap", Aliases: "CAP DEAD END" } }],
  column_map: { Canonical: ["Canonical"], Aliases: ["Aliases"] }, sha256: "filehash", header_error: null,
};
const preview: ImportResult = {
  summary: "Preview: created 1, updated 0, unchanged 0, errors 0", created: 1, updated: 0, unchanged: 0,
  errors: [], dry_run: true, applied: false,
  rows: [{ row: 2, action: "create", id: "REL-017", canonical: "Cap", aliases: ["CAP DEAD END"], scope: "global", item_anchors: [], doc_types: [], active: true }],
  source: { file: "authorized.csv", sha256: "filehash", sheet: "CSV", header_row: 1, column_map: source.column_map, terminology_version: "reviewed-version" },
};

async function readColumns() {
  fireEvent.change(screen.getByLabelText("File to import"), { target: { files: [new File(["Canonical,Aliases\nCap,CAP DEAD END"], "authorized.csv")] } });
  fireEvent.click(screen.getByRole("button", { name: "Read columns" }));
  await screen.findByRole("button", { name: "Preview import" });
}

describe("relationship source import", () => {
  it("requires a preview, sends the reviewed version and applies only on the import click", async () => {
    const imports: FormData[] = [];
    vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit) => {
      if (path.endsWith("/inspect")) return new Response(JSON.stringify(source));
      const body = init.body as FormData;
      imports.push(body);
      return new Response(JSON.stringify(body.get("dry_run") === "true" ? preview : { ...preview, summary: "Import: created 1", dry_run: false, applied: true }));
    }));
    const onImported = vi.fn();
    render(<TerminologyImport onImported={onImported} />);
    await readColumns();
    expect(screen.queryByRole("button", { name: /approved relationships/ })).toBeNull();
    expect(imports).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));
    const approve = await screen.findByRole("button", { name: "Import 1 approved relationships" });
    expect(onImported).not.toHaveBeenCalled();
    expect(imports[0].get("dry_run")).toBe("true");
    fireEvent.click(approve);
    await waitFor(() => expect(onImported).toHaveBeenCalledTimes(1));
    expect(imports[1].get("dry_run")).toBe("false");
    expect(imports[1].get("expected_version")).toBe("reviewed-version");
    expect(JSON.parse(String(imports[1].get("column_map")))).toEqual(source.column_map);
  });

  it("invalidates the approval button when the scope changes after preview", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith("/inspect") ? source : preview))));
    render(<TerminologyImport onImported={vi.fn()} />);
    await readColumns();
    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));
    await screen.findByRole("button", { name: "Import 1 approved relationships" });
    fireEvent.change(screen.getByLabelText("Default scope"), { target: { value: "sku:1175108DNS" } });
    expect(screen.queryByRole("button", { name: /approved relationships/ })).toBeNull();
  });

  it("shows invalid rows without an import button", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith("/inspect") ? source : {
      ...preview, summary: "Preview: errors 1", errors: ["CSV row 3: Canonical wording is missing."],
    }))));
    render(<TerminologyImport onImported={vi.fn()} />);
    await readColumns();
    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));
    await screen.findByText("CSV row 3: Canonical wording is missing.");
    expect(screen.queryByRole("button", { name: /approved relationships/ })).toBeNull();
    expect(screen.getByText(/No changes saved/)).toBeTruthy();
  });
});
