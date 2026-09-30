import { HOTKEYS } from "../lib/hotkeys";
import { Dialog, Kbd } from "./ui";

/** Keyboard reference. Opened with "?"; closed with Esc, "?" or a click outside. */
export function HotkeyHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Keyboard shortcuts" description="Shortcuts work outside form fields. Enter opens a comparison or saves the selected decision." width="sm">
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
        {HOTKEYS.map(([key, what]) => (
          <div key={key} className="contents">
            <dt className="flex gap-1">
              {key.split(/\s+or\s+/).map((k) => (
                <Kbd key={k}>{k.trim()}</Kbd>
              ))}
            </dt>
            <dd className="text-ink-2">{what}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}

export function HotkeyHint() {
  return (
    <span className="hidden md:inline-flex items-center gap-1.5 text-xs text-ink-3" title="Keyboard shortcuts">
      <Kbd>j</Kbd>
      <Kbd>k</Kbd> move · <Kbd>Enter</Kbd> open · <Kbd>?</Kbd> help
    </span>
  );
}
