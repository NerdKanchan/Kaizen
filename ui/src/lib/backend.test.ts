import { describe, expect, it } from "vitest";
import { backendProblem } from "./backend";

describe("backend compatibility", () => {
  it("accepts the current contract", () => {
    expect(backendProblem({ status: "ok", version: "0.1.0", hosted: false, api_contract: 3 })).toBeNull();
  });
  it("explains the old local server that caused upload 500s", () => {
    expect(backendProblem({ status: "ok", version: "0.1.0", hosted: false })).toContain("start it again");
  });
  it("requires a restart after Python source changes even with the same API contract", () => {
    expect(backendProblem({ status: "ok", version: "0.1.0", hosted: false, api_contract: 3, restart_required: true })).toContain("start it again");
  });
  it("rejects a server that lacks current approval progress", () => {
    expect(backendProblem({ status: "ok", version: "0.1.0", api_contract: 2 })).toContain("start it again");
  });
});
