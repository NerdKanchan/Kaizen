import { describe, expect, it } from "vitest";
import { ownsKeyboard } from "./hotkeys";

function target(tagName: string, interactiveAncestor = false, editable = false) {
  return { tagName, isContentEditable: editable, closest: () => interactiveAncestor ? {} : null } as unknown as EventTarget;
}
describe("review shortcut boundaries", () => {
  it("preserves Enter activation on links, buttons and disclosure controls", () => {
    for (const tag of ["A", "BUTTON", "SUMMARY", "SPAN"]) expect(ownsKeyboard(target(tag, true))).toBe(true);
  });
  it("leaves form fields and editable text in control of typing", () => {
    for (const tag of ["INPUT", "SELECT", "TEXTAREA"]) expect(ownsKeyboard(target(tag))).toBe(true);
    expect(ownsKeyboard(target("DIV", false, true))).toBe(true);
  });
  it("allows review shortcuts on unfocused page content", () => {
    expect(ownsKeyboard(target("BODY"))).toBe(false);
    expect(ownsKeyboard(target("TD"))).toBe(false);
    expect(ownsKeyboard(null)).toBe(false);
  });
});
