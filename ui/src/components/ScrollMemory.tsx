// Scroll position across history entries. A reviewer works the queue from the top down, opens a
// row, decides it and presses Back; landing at the top of the list every time is the single most
// repeated annoyance in the app. React Router ships ScrollRestoration only for the data routers,
// and this app is on a HashRouter (the bundle is served as static files), so we keep our own.
import { useEffect } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

const offsets = new Map<string, number>();

export function ScrollMemory() {
  const { key } = useLocation();
  const type = useNavigationType();

  // The browser's own restoration fights ours, and it does not know about hash routes.
  useEffect(() => {
    const prev = history.scrollRestoration;
    try {
      history.scrollRestoration = "manual";
    } catch {
      /* not supported: the effect below still runs, the browser just guesses too */
    }
    return () => {
      try {
        history.scrollRestoration = prev;
      } catch {
        /* ignore */
      }
    };
  }, []);

  // Keep this entry's offset current while the reader scrolls, and once more as they leave.
  useEffect(() => {
    const remember = () => offsets.set(key, window.scrollY);
    window.addEventListener("scroll", remember, { passive: true });
    return () => {
      remember();
      window.removeEventListener("scroll", remember);
    };
  }, [key]);

  useEffect(() => {
    // PUSH is a new place: start at the top. REPLACE is a filter or a selection changing the
    // address in place, so leave the page exactly where it is.
    if (type === "PUSH") {
      window.scrollTo(0, 0);
      return;
    }
    if (type !== "POP") return;
    const want = offsets.get(key);
    if (!want) return;
    // The rows are still loading, so the document is not tall enough to scroll to yet. Keep
    // asking until it is, or until it is clear it never will be.
    let frames = 0;
    let raf = requestAnimationFrame(function attempt() {
      window.scrollTo(0, want);
      if (Math.abs(window.scrollY - want) > 2 && frames++ < 90) raf = requestAnimationFrame(attempt);
    });
    return () => cancelAnimationFrame(raf);
  }, [key, type]);

  return null;
}
