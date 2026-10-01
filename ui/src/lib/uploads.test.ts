// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { MAX_RUN_BYTES, supportedRunFiles, uploadProblem } from "./uploads";

describe("upload selection", () => {
  it("keeps supported documents and excludes lock files and unrelated folder contents", () => {
    const files = ["bom.PDF", "label.pdf", "pco.xlsm", "export.csv", "~$bom.xlsx", ".hidden.pdf", "notes.txt"].map(name => new File(["data"], name));
    expect(supportedRunFiles(files).map(file => file.name)).toEqual(["bom.PDF", "label.pdf", "pco.xlsm", "export.csv"]);
  });
  it("refuses empty and oversized selections before sending a request", () => {
    expect(uploadProblem([])).toContain("Choose");
    expect(uploadProblem([{ size: MAX_RUN_BYTES + 1 } as File])).toContain("250 MB");
    expect(uploadProblem([{ size: MAX_RUN_BYTES } as File])).toBeNull();
  });
});
