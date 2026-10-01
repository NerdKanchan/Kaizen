// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { notifyDataChanged, useDataRefresh } from "./dataRefresh";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); localStorage.clear(); });

describe("review data refresh", () => {
  it("refreshes matching runs and the run list after a successful approval", async () => {
    const matching = vi.fn(), other = vi.fn(), list = vi.fn();
    renderHook(() => useDataRefresh(matching, "first"));
    renderHook(() => useDataRefresh(other, "other"));
    renderHook(() => useDataRefresh(list));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{}')));
    await act(async () => { await api.finalize("first", { row_id: "row", final_decision: "ACCEPT", expected_revision: 1, confirm_self_approval: true }); });
    expect(matching).toHaveBeenCalledOnce();
    expect(list).toHaveBeenCalledOnce();
    expect(other).not.toHaveBeenCalled();
  });

  it("does not broadcast a rejected approval", async () => {
    const refresh = vi.fn();
    renderHook(() => useDataRefresh(refresh, "first"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"Row changed"}', { status: 409 })));
    await expect(api.finalize("first", { row_id: "row", final_decision: "ACCEPT", expected_revision: 1, confirm_self_approval: false })).rejects.toThrow("Row changed");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("receives changes from another tab and removes listeners on unmount", () => {
    const refresh = vi.fn();
    const { unmount } = renderHook(() => useDataRefresh(refresh, "first"));
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: "kaizen.dataChanged", newValue: JSON.stringify({ runId: "first", nonce: "1" }) })));
    expect(refresh).toHaveBeenCalledOnce();
    unmount();
    notifyDataChanged("/api/runs/first/decisions");
    window.dispatchEvent(new Event("focus"));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("refreshes on focus and periodically while visible", () => {
    vi.useFakeTimers();
    const refresh = vi.fn();
    renderHook(() => useDataRefresh(refresh, "first"));
    act(() => window.dispatchEvent(new Event("focus")));
    act(() => vi.advanceTimersByTime(30000));
    expect(refresh).toHaveBeenCalledTimes(2);
  });
});
