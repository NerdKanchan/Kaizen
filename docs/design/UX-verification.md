# UI/UX revision verification

- Production TypeScript + Vite build passed.
- Vitest: 19 tests passed, including a regression test for shortcut ownership.
- Browser: verified new-run dialog input, Escape dismissal and focus restoration.
- Browser: verified name search, no-result feedback, and ownership filters.
- Browser: verified mobile menu opens with labels and closes on route selection.
- Browser: verified advanced filter disclosure with Enter and a BLOCKER selection
  updates the URL; the existing run returned two matching comparisons.
- Workspace viewport checks: 320, 375, 414 and 1280px had no horizontal page overflow.
- Queue viewport checks: 320, 375, 414 and 768px had no horizontal page overflow;
  its wide comparison table retains its own horizontal scroll area.
- Light and dark appearances were inspected. No new runs, uploads, decisions,
  account changes or share grants were created during verification.

The local backend was already running with an older response shape: the list
returned the name “Test Run”, while the run detail omitted its name/access fields.
Backend processes were not restarted or modified for this UI task. Current source
contains the collaborative API changes independently of this revision.

## Copy and appearance refinement

- Production TypeScript + Vite build passed after the final UI changes.
- Vitest: 19 tests passed. Git whitespace check passed.
- Browser: all 11 accessible application views, including a source document and
  comparison, checked at 320, 375, 414 and 768px (44 route/viewport combinations).
  No page overflow or content spilling beyond the viewport outside intended
  table/image scroll containers remained. This check caught and fixed clipped
  terminology search, import and action-item controls.
- Browser: inspected the wide comparison layout at 1440px and the default desktop
  layout. Decision jump retained the comparison route and focused its select.
- Browser: pressing Enter on a document line selected it and updated its deep link.
- Sign-in and account creation inspected on a separate local origin, including
  320px layout. No credentials entered and no accounts created.
- Main text, secondary/muted text, sidebar labels, primary action text and three
  status-text/background pairs exceeded 4.5:1 in both themes. Lowest checked pair:
  4.77:1 in light mode and 6.44:1 in dark mode. This is a token-pair check, not a
  certification of every possible third-party document or user-provided value.
- Administrative account rows reviewed in source; the signed-in local account is
  a reviewer. Administrator mutations and account flows were not exercised.
- No new runs, decisions, shares, imports, account approvals or action items were
  created. Existing review data was used for visual verification.

The earlier local-backend response-shape limitation still applies. The current
running process omits collaborative fields in run detail responses; current source
contains those fields. The UI now avoids showing “Full access” when access metadata
is absent. Collaboration endpoints and source backend changes remain outside this
visual verification.

## Main-branch validation

Before publishing this revision with its required collaboration API dependencies:

- Python lint: passed (`ruff check src tests`).
- Full Python suite: 533 tests passed, including account approval, access grants,
  revision checks, self-approval, independent copies and export/import coverage.
- UI: production build and all 19 Vitest tests passed.
- Golden-dataset accuracy gate: precision and recall both 1.0, with no false
  missing-item violations. Evaluation used a separate temporary workspace.

These checks exercise current backend source in isolated test workspaces. They do
not change the previously running local preview process or its response shape.
