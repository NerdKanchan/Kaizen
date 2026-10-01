import { useEffect, useRef } from "react";

const EVENT = "kaizen:data-changed";
const STORAGE_KEY = "kaizen.dataChanged";
type Change = { runId?: string; nonce: string };

/** Refresh read-only views after a successful mutation, including other browser tabs. */
export function notifyDataChanged(path: string) {
  if (typeof window === "undefined" || !path.startsWith("/api/runs")) return;
  const id = path.match(/^\/api\/runs\/([^/?]+)/)?.[1];
  const change: Change = { runId: id && !["upload", "from-path"].includes(id) ? decodeURIComponent(id) : undefined, nonce: `${Date.now()}-${Math.random()}` };
  window.dispatchEvent(new CustomEvent<Change>(EVENT, { detail: change }));
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(change)); } catch { /* Refresh on focus still works without storage. */ }
}

export function useDataRefresh(reload: () => void, runId?: string) {
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  useEffect(() => {
    const refresh = () => reloadRef.current();
    const changed = (change: Change) => { if (!runId || !change.runId || runId === change.runId) refresh(); };
    const event = (e: Event) => changed((e as CustomEvent<Change>).detail);
    const storage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY || !e.newValue) return;
      try { changed(JSON.parse(e.newValue) as Change); } catch { /* Ignore malformed browser storage. */ }
    };
    const visible = () => { if (document.visibilityState === "visible") refresh(); };
    window.addEventListener(EVENT, event);
    window.addEventListener("storage", storage);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", visible);
    const timer = window.setInterval(visible, 30000);
    return () => {
      window.removeEventListener(EVENT, event);
      window.removeEventListener("storage", storage);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", visible);
      window.clearInterval(timer);
    };
  }, [runId]);
}
