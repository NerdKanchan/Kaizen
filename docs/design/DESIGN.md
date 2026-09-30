# DESIGN.md — Kaizen Cross-Check reviewer interface

Durable visual decisions. Mode: **Operate** (the reviewer is in a task; the tool should disappear into
it). Brief: BD colour system, clear hierarchy, easy keyboard-first review, crafted motion.

## Visual world

**A BD instrument panel.** Clinical white surfaces on a cool, blue-tinted canvas; BD blue as the
structural colour (navigation, links, selection, headings' emphasis); BD orange reserved for the one
action that matters on each screen, the active marker, and focus. Dense but calm: the density of a
laboratory instrument, not a spreadsheet. Colour means something or is not there.

The panel has two compositions, light and dark, built from the same tokens. Dark is the same
instrument with the lights down: a deep blue-black canvas, cards one step lighter, hairlines that are
barely there, off-white ink, and the same orange. It is composed, not inverted (see *Dark theme*).

## Colour

Brand, from BD's identity. Navy is the structural colour, BD blue carries links and emphasis, and
orange is reserved for the one action that matters on a screen.

| Token | Hex | Use |
|---|---|---|
| `brand-900` / `brand-fill` | `#05093D` | Navy: navigation rail, filled brand chips |
| `brand-700` | `#053CA3` | Strongest brand text |
| `brand-600` | `#044ED7` | BD blue: selected states, structural emphasis, INFO |
| `brand-500` | `#1D74FF` | Bright blue: hover on blue |
| `brand-100` | `#E0EAFD` | Selected row, soft blue surfaces, file-picker button |
| `rail-dim` | `#9199D8` | Periwinkle: section labels in the rail |
| `link` | `#044DD6` | Hyperlinks, visited and unvisited alike |
| `accent-600` | `#E56300` | Orange pressed, and the focus ring in light |
| `accent-500` | `#FF6E00` | BD orange: primary action, active nav marker, caret, selection |
| `accent-100` | `#FFE4D1` | Orange soft surface |

Neutrals, one family, warmed rather than blue-tinted — the page is off-white paper, not a screen:

| Token | Hex | Use |
|---|---|---|
| `canvas` | `#F9F4F1` | Warm off-white page background |
| `surface` | `#FFFFFF` | Cards, tables, inputs |
| `surface-2` | `#F3EDE9` | Toolbars, side panels, table headers |
| `line` | `#E6E0DC` | Hairline borders |
| `line-2` | `#DBD8D7` | Warm grey: stronger borders, input borders on hover |
| `ink` | `#3D3E41` | Charcoal: primary body text, 9.4:1 on canvas |
| `ink-2` | `#5A5B5F` | Secondary text, 6.1:1 on canvas |
| `ink-3` | `#6B6C71` | Muted text and placeholders, 4.6:1 on canvas |

Semantic (state), separate from brand:

| Token | Hex | Meaning |
|---|---|---|
| `ok` / `ok-soft` | `#1E7F4F` / `#E4F2EA` | success, cleared |
| `warn` / `warn-soft` | `#B7791F` / `#FAF0DC` | needs attention |
| `bad` / `bad-soft` | `#CE4B35` / `#FDEDE9` | failure, blocker |

Classification (carried by colour and word, always together): EXACT `#1E7F4F`, EQUIVALENT `#0E7C86`,
POTENTIAL `#B7791F`, MISMATCH `#CE4B35`, MISSING `#7E3AA6`. Severity: BLOCKER `#7A1F1F`, MAJOR
`#C13A2B`, MINOR `#B7791F`, INFO `#044ED7`. Missing is plum, never orange: orange belongs to the brand.
Filled severity badges carry white text only where it reaches 4.5:1 (blocker, major, info); the minor
badge is soft amber with dark amber text.

Dark is tuned for a long session rather than for maximum separation: body text sits at 9.5:1 on a
card, not the 14:1 a near-white ink would give, and every accent is pulled back from full saturation.
The floor still holds everywhere — muted text on a table header, the tightest pair, is 4.7:1.

Contrast floor 4.5:1 for body and placeholder text, 3:1 for large text; every pair in both themes is
measured, and the lowest real pair is `ink-3` on `canvas` at 4.6:1. A primary button rests as orange
with navy text (6.7:1); on hover and press the fill darkens to `accent-700` and the label turns white
(5.1:1). White is never placed on the resting orange, where it would be 2.8:1. The focus ring is `accent-600` in light
(3.5:1 on white) and `accent-500` in dark.

### Dark theme

Every colour token is a CSS variable (`--c-*`, RGB channels) with a light set on `:root` and a dark set
on `:root[data-theme="dark"]`; Tailwind's colour utilities read them, so no component knows which
theme is on. The choice is remembered per browser under `kaizen.theme`; until a choice is made the
tool follows the operating system, including live changes. A boot script in `index.html` stamps the
theme before first paint so there is no flash. `color-scheme` follows the theme, so native selects,
scrollbars and form controls render in it too.

| Token | Dark | Note |
|---|---|---|
| `canvas` | `#11152A` | navy, lifted well off black; the whole theme is tuned down, not inverted |
| `surface` / `surface-2` / `surface-3` | `#1A1F38` / `#222844` / `#2C3456` | one step lighter per level, 1.1:1 apart |
| `line` / `line-2` | `#2A3152` / `#3E4770` | hairlines 1.3:1, input borders 2:1 |
| `ink` / `ink-2` / `ink-3` | `#CAC6C3` / `#A19D9A` / `#96928F` | warm grey, deliberately short of white: body text is 9.5:1, not 14:1 |
| `rail` / `rail-ink` / `rail-muted` | `#04071C` / `#F2F0EE` / `#A7AEE0` | a deeper BD navy with a hairline edge |
| `brand-600` / `link` | `#6994E8` / `#88A9E0` | BD blue lightened until it reads as text, without glare |
| `brand-100` / `brand-700` | `#1B2450` / `#A6BEF0` | soft blue surface and the text on it |
| `brand-fill` | `#1D4FA8` | filled brand chip, white text |
| `accent-500` | `#FF6E00` | unchanged; text on it is always navy |
| `accent-50` / `accent-100` | `#2B1607` / `#3D200E` | soft orange surfaces, selection, focus halo |
| `ok` / `ok-soft` / `ok-strong` | `#4FB183` / `#0F2A1D` / `#86D0A9` | strong on soft 8:1 |
| `warn` / `warn-soft` / `warn-strong` | `#D9A055` / `#2C2210` / `#E2BA79` | 8.3:1 |
| `bad` / `bad-soft` / `bad-strong` | `#E8836F` / `#3A1C17` / `#EEA396` | 7.1:1 |
| Classification dots and bars | EXACT `#3DBF7A`, EQUIVALENT `#38B6C2`, POTENTIAL `#E4A33B`, MISMATCH `#E8836F`, MISSING `#B08CCE` | lifted so they carry on a dark ground without glaring |
| Severity fills | BLOCKER `#A32323`, MAJOR `#C13A2B`, INFO `#2B63C7` | white text 5.4:1 or better |
| Scrim | `rgba(0,0,0,.6)` | light uses `rgba(5,9,61,.45)` |
| Shadows | `rgba(0,0,0,.7)` and `.45` | tinted shadows do not read on dark |

Rules that hold in the dark: orange is unchanged and still carries ink text; meaning colours stay
paired with words; page images are evidence and stay white paper inside a dark frame; strong tones
read both on their soft surface and on plain `surface`; text stays at or above 4.5:1 (measured, both
themes, for every pair the interface uses).

## Typography

One family: **Geist** (variable, self-hosted). **Geist Mono** only for data: ids, hashes, item numbers,
quantities and file names. No display face; product UI carries hierarchy with size and weight.

| Role | Size / line | Weight | Tracking |
|---|---|---|---|
| Page title | 22 / 28 | 600 | -0.01em |
| Section title | 16 / 24 | 600 | -0.005em |
| Body | 14 / 20 | 400 | 0 |
| Small | 13 / 18 | 400 | 0 |
| Caption | 12 / 16 | 500 | 0 |
| Big number | 34–40 / 1 | 600 | -0.02em, tabular |

Sentence case everywhere. No all-caps eyebrows above headings. Labels for fields and table headers are
12px, weight 500, `ink-2`, sentence case. Numbers that line up are `tabular-nums`.

## Space, shape, depth

Spacing scale 4 / 8 / 12 / 16 / 24 / 32 / 48. Tight inside a group, generous between groups; more space
above a heading than below it. Cards: radius 12px, 1px `line` border, no shadow (elevation declared
once). Overlays (dialogs, popovers, toasts): radius 12px, tinted shadow
`0 12px 32px -12px rgba(15,31,53,.28), 0 2px 6px rgba(15,31,53,.08)`. Controls: radius 8px, height 36px
(small 30px, large 44px). Badges are pills, 22px tall. Page content is capped at 1440px with 24px padding.

## Layout

App shell: a 232px navigation rail in `brand-700` with two groups, *Workspace* (Runs, Terminology,
Action items) and *This run* (Dashboard, Review queue, Documents, Worklist and mining, Business case,
Compare runs); the active item carries a 3px orange marker. A 56px top bar on `surface`: wordmark, run
switcher, theme toggle (moon or sun, one press), reviewer identity (initials, name, slot pill, BLIND
pill), sign out. Each page opens with a title, one line saying what the page is for, and the page's
actions on the right.

## Motion

Motion conveys state and feedback, never decoration. Easing `cubic-bezier(0.16, 1, 0.3, 1)` for
arrivals, `cubic-bezier(0.77, 0, 0.175, 1)` for on-screen movement; exits faster than entrances.

| Moment | Treatment |
|---|---|
| Press | `transform: scale(.97)` 120ms on any pressable |
| Hover | background or border change 150ms; gated to `(hover: hover) and (pointer: fine)` |
| Panels and rows appearing after a load | rise 6px + fade, 200ms, sibling stagger 40ms capped at 8 items |
| Dialog, help overlay | scale .97 to 1 + fade, 180ms in, 120ms out; centred origin |
| Toast | slide 8px + fade, 200ms in, 120ms out |
| The authored moment | the dashboard's cleared-versus-review split bar fills from empty over 600ms when a run first opens, once |
| Theme switch | every colour cross-fades 200ms (background, border, text); the toggle's icon pops in |
| Keyboard navigation (`j`/`k`, `Enter`) | no animation |
| `prefers-reduced-motion` | no movement; opacity and colour transitions only |

Loading: skeletons shaped like the content, never a spinner in the middle of a page. Empty states say
what to do next.

## Iconography

Phosphor icons, regular weight, 16px inline and 18px in navigation, always with a text label or an
`aria-label`. No emoji, no unicode glyphs as icons.

## Browser surfaces

Selection `accent-100` with `ink`; caret `accent-500`; focus ring 2px `accent-600` (light) or
`accent-500` (dark) with 2px offset; scrollbars thin, thumb `line-2` on `surface-2`; underline offset
3px on links; `color-scheme` set per theme so the browser's own controls match.

## Refuse

Eyebrows and section numbers; nested cards; coloured left borders thicker than 1px; gradient text;
glass or blur as decoration; monospace as a costume; emoji icons; white text on orange; animation on
keyboard-driven actions; any colour whose meaning is not stated in words next to it; a dark theme made
by inverting the light one; hard-coded hex colours in components.

## September 2026 navigation revision

This section supersedes the earlier shell dimensions and workspace hierarchy.
The intent is to help reviewers find their work and identify their next action.

- Workspace home is **All runs**. It combines owned and shared runs by default,
  with ownership filters and name, ID or owner search persisted in the URL.
- **New cross-check** opens a focused dialog. Folder upload is primary; demo data
  and administrator-only local paths are secondary options. Errors remain in the
  dialog, which traps focus and returns it on close.
- A 248px desktop sidebar groups Workspace, Current run, and Analysis. Desktop
  collapse is remembered. Below 1024px a labelled menu replaces the icon rail.
- Workspace destinations appear first. Run destinations appear only after a run
  is selected. The current run selector appears on run pages, where it is relevant.
- **Overview**, **Review queue**, and **Documents** form the main review flow.
  Suggested matches, Compare runs, and Business case are separate analysis tools.
- The overview puts the queue action first. Sharing, copying, exports and
  verification remain under **Share, export and manage this run**.
- The queue exposes SKU, check, review status, search and flagged-only selection.
  Discrepancy, severity, classification and role live under **More filters**,
  automatically expanded when one of those filters is present in a deep link.
- Engine flags are labelled as engine results, not as live outstanding review
  counts. Ownership and access remain visible on run entries.
- Shared page headings use a 24–30px scale. Light surfaces use a cool neutral
  canvas; semantic status colours, dark mode, and the BD accent remain.
- Native links, buttons, disclosures, form fields and dialogs retain their own
  keyboard behavior. Review shortcuts must not consume their Enter key.

### Research and application

Reviewed official product guidance on 2026-09-30:

- [Notion sidebar](https://www.notion.com/en-gb/help/navigate-with-the-sidebar):
  grouped destinations, a stable home and a clear workspace context.
- [Linear team pages](https://linear.app/docs/default-team-pages): focused views
  for distinct kinds of work; applied as common review filters and separate analysis.
- [Atlassian navigation](https://support.atlassian.com/navigation/docs/navigation-best-practices/):
  keep relevant destinations accessible and let users collapse navigation.

These references informed interaction patterns; no assets or page designs were copied.

### Route inventory

| Page | Purpose |
| --- | --- |
| RunsPage | Find owned/shared runs and start a cross-check |
| DashboardPage | Inspect run results and enter review |
| ReviewQueuePage | Filter comparisons and select evidence |
| EvidencePage | Examine evidence and record a decision |
| DocumentsPage | Find source documents by SKU |
| DocumentPage | Inspect extracted document content |
| MiningPage | Inspect suggested terminology matches |
| BusinessCasePage | Inspect measured effort and projections |
| DiffPage | Compare discrepancies across runs |
| TerminologyPage | Manage terminology relationships |
| ActionItemsPage | Track follow-up work |
| AdminPage | Manage approved accounts |

The shared shell and headings apply across these routes. Detailed content redesign
in this revision focuses on workspace home, run overview and review queue.

## September 2026 copy and appearance refinement

This section supersedes the earlier palette, shell dimensions and animation guidance.

### Writing

Use short page titles and concrete instructions. Home begins with run totals,
filters and the list of runs. Introductory slogans have been removed. Describe
what the reviewer can do; avoid promises, metaphors and repeated explanations.
Use human-readable issue names in the interface while retaining the original
codes in API requests and recorded results. Estimates remain explicitly labelled
as estimates, with their assumptions available on the page.

### Appearance

| Role | Light | Dark |
| --- | --- | --- |
| Canvas | `#F8F9FB` | `#14161B` |
| Surface | `#FFFFFF` | `#1B1E24` |
| Secondary surface | `#F5F6F8` | `#22252C` |
| Main text | `#1E242E` | `#EBEEF4` |
| Secondary text | `#4A5463` | `#C5CBD6` |
| Muted text | `#636E7F` | `#A3ACBB` |
| Sidebar | `#F5F6F8` | `#17191E` |
| Primary action | `#FF6E00` | `#F49F62` |
| Primary action text | `#181B21` | `#181B21` |

The sidebar is 240px wide and the top bar is 60px high. Statuses use restrained
backgrounds and explicit labels. Cards use 10px corners; inputs and buttons use
7px corners. Geist remains the main font. Geist Mono is reserved for identifiers
and extracted source text. Decorative arrival and bar animations are disabled.

### Page layout and access

- Home shows actual total, owned and shared run counts above the run list.
- The overview prioritises review status. Version identifiers remain under Run record.
- Comparison pages show a readable check title, explanation, discrepancies and
  recommended next steps. Source-document and decision buttons jump within the page
  without changing the route. The decision panel sits beside the source documents
  on wide screens, and history is an expandable section.
- Business case separates the current estimate from future-run terminology estimates.
- Shared field labels are linked to their controls. Hints and errors on direct
  input controls are associated through `aria-describedby`.
- Document lines and terminology relationships have keyboard-operable selection
  buttons. Tables retain their own horizontal scrolling on narrow screens.
- Search, import, sharing and action-item controls wrap within narrow layouts.
- Sign-in, account creation, access-denied and missing-page views use the same system.

### References

Reviewed on 2026-09-30:

- [Atlassian voice and tone](https://atlassian.design/foundations/content/voice-tone):
  concise, practical instructions informed the writing pass.
- [Primer colour primitives](https://primer.style/product/primitives/color/):
  semantic roles informed the palette and status treatment.
- [GitHub's inclusive colour system](https://github.blog/engineering/unlocking-inclusive-design-how-primers-color-system-is-making-github-com-more-inclusive/):
  informed contrast checks and distinct light/dark surface levels.

Validation and local backend limitations are recorded in
[UX-verification.md](UX-verification.md). This refinement covers the shared system
and copy across all twelve application pages and the authentication views.
