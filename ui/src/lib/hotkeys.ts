// Single-key shortcuts for the review loop. A reviewer working two hundred rows should not need the mouse.
// Shortcuts never fire while typing (inputs, textareas, selects, contenteditable) or with a modifier held,
// so they cannot hijack a comment box or a browser shortcut.
import { useEffect } from "react";

export type HotkeyMap = Record<string, (e: KeyboardEvent) => void>;

export function isTyping(target: EventTarget | null): boolean {
  const t = target as HTMLElement | null;
  if (!t || !t.tagName) return false;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return true;
  return t.isContentEditable === true;
}

/** Native controls and dialogs own their keys; row shortcuts only run on the page. */
export function ownsKeyboard(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return isTyping(target) || !!element?.closest?.('a[href], button, summary, [role="button"], [role="dialog"], [contenteditable="true"]');
}

export function useHotkeys(map: HotkeyMap, deps: unknown[]) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || ownsKeyboard(e.target)) return;
      const fn = map[e.key];
      if (!fn) return;
      e.preventDefault();
      fn(e);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/** The shortcut reference shown by "?". Keep in step with the bindings in the queue and evidence pages. */
export const HOTKEYS: [string, string][] = [
  ["j  or  ]", "next row"],
  ["k  or  [", "previous row"],
  ["Enter", "queue: open the highlighted row · evidence: submit the chosen decision"],
  ["a", "choose ACCEPT"],
  ["c", "choose CONFIRM DISCREPANCY"],
  ["o", "choose OVERRIDE"],
  ["n", "choose NEEDS MORE INFORMATION"],
  ["Esc", "close this help, or go back to the queue"],
  ["?", "show or hide this help"],
];
