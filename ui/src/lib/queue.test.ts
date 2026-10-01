import { describe, expect, it } from "vitest";
import { queueQueryFromParams } from "./queue";

describe("queue pagination", () => {
  it("preserves engine and unresolved-finding links from the overview", () => {
    const query = queueQueryFromParams(new URLSearchParams({ nv: "0", engine_classification: "MISMATCH", unresolved: "1" }), { viewer: 1, blind: false });
    expect(query.engine_classification).toBe("MISMATCH");
    expect(query.unresolved).toBe(true);
    expect(query.needs_validation).toBeUndefined();
  });
  it.each(["-1", "0.5", "Infinity", "NaN", "9007199254740992"])("sanitizes malformed offset %s", offset => {
    expect(queueQueryFromParams(new URLSearchParams({ offset }), { viewer: 1, blind: false }).offset).toBe(0);
  });
});
