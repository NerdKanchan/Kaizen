// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useAsync } from "./useAsync";

afterEach(cleanup);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

describe("useAsync", () => {
  it("clears the previous run immediately when the run ID changes", async () => {
    const next = deferred<string>();
    const { result, rerender } = renderHook(({ id }) => useAsync(() => id === "old" ? Promise.resolve("old data") : next.promise, [id]), { initialProps: { id: "old" } });
    await waitFor(() => expect(result.current.data).toBe("old data"));
    rerender({ id: "new" });
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
    await act(async () => next.resolve("new data"));
    expect(result.current.data).toBe("new data");
  });

  it("ignores out-of-order completions after switching rows", async () => {
    const old = deferred<string>();
    const next = deferred<string>();
    const { result, rerender } = renderHook(({ id }) => useAsync(() => id === "old" ? old.promise : next.promise, [id]), { initialProps: { id: "old" } });
    rerender({ id: "new" });
    await act(async () => next.resolve("new data"));
    await act(async () => old.resolve("old data"));
    expect(result.current.data).toBe("new data");
  });

  it("keeps same-run data during a refresh and reports a synchronous loader failure", async () => {
    let fail = false;
    const { result } = renderHook(() => useAsync(() => { if (fail) throw new Error("loader failed"); return Promise.resolve("data"); }, []));
    await waitFor(() => expect(result.current.data).toBe("data"));
    fail = true;
    act(() => result.current.reload());
    expect(result.current.data).toBe("data");
    await waitFor(() => expect(result.current.error).toBe("loader failed"));
    expect(result.current.loading).toBe(false);
  });

  it("clears a previous row's error when the row changes", async () => {
    const next = deferred<string>();
    const { result, rerender } = renderHook(({ id }) => useAsync(() => id === "old" ? Promise.reject(new Error("old error")) : next.promise, [id]), { initialProps: { id: "old" } });
    await waitFor(() => expect(result.current.error).toBe("old error"));
    rerender({ id: "new" });
    expect(result.current.error).toBeNull();
    expect(result.current.data).toBeNull();
    await act(async () => next.resolve("new data"));
    expect(result.current.error).toBeNull();
  });

  it("does not publish a late response after unmount", async () => {
    const late = deferred<string>();
    const { result, unmount } = renderHook(() => useAsync(() => late.promise, []));
    unmount();
    await act(async () => late.resolve("late data"));
    expect(result.current.data).toBeNull();
  });
});
