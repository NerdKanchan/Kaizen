# Known limitations (honest list)

The golden accuracy numbers are measured on synthetic documents. The supplied real BD delivery has now
been exercised, with separate extraction checks documented in [real-data validation](real-data-validation.md).
No reviewer-approved real-data pairing/discrepancy ground truth has been supplied, so real matching accuracy
is still unmeasured.

## Extraction
- **OCR** supports BOMs, labels and drawings when Tesseract or the project's optional RapidOCR extra is
  installed. Missing engines and failed pages are reported, and a page from which nothing could be read
  blocks the affected comparisons. A BOM line that looks like a component but does not parse becomes its
  own blocker row, and an unparsed label line is a warning; the rest of the document is still compared. OCR may still misread letters, numbers or fine print. RapidOCR word boxes
  are approximate splits of line boxes. Native PDF text can also contain recognition errors.
- **Drawing images** are not interpreted as physical components. Text callouts are read; leader endpoints,
  cavity occupancy, component orientation and placement are not checked. Scanned callout extraction is
  tuned for the delivered bilingual drawing; other languages or monolingual layouts need validation.
- **General assembly references** may depict optional parts from several products. The supplied drawing
  has reference-only notes and is not referenced by these BOMs. Applicability remains review-required.
- **Hand-drawn or scanned redlines** are not read. PDF FreeText annotations are captured and used by the
  PCO ↔ BOM check; hand annotations are not.
- **Truncated ERP descriptions** (JDE cuts at a fixed width, e.g. `PRODUCING LABELS ON THE`) are not
  prefix-matched; a truncated last token lowers similarity.
- **Case labels** are not parsed; the manual checklist carries the case-label check.
- Parsers are keyed on the layouts in the brief (header words, `N Each -` starters, title-block labels).
  Other layouts will need fixtures and, possibly, parser variants.

## Matching
- Fuzzy pairs whose BOM tokens all appear in a long label line score 1.0 but remain POTENTIAL by design
  (never auto-cleared). On the golden set that is ~80 of ~1,100 rows; the learning loop converts confirmed
  ones into relationships so the next SKU auto-clears them.
- Thresholds (0.85 potential, 0.60 floor, 0.05 ambiguity) were chosen on synthetic data and are recorded in
  every run; they must be re-tuned on real documents.
- The current assignment is one-to-one. A compound catheter/stylet label entry can represent multiple
  BOM components; approved assembly membership and quantity allocation are needed before such checks can
  be automated. ERP abbreviations and pack quantities need item-specific, reviewed relationships.
- The supplied relationship workbook is protected by a BD sensitivity label with rights management, so no
  password opens it; it has not been imported. An unprotected copy saved by someone with access is needed. MISSING means no accepted
  pairing was found; it is not proof that a physical component is absent.
- Semantic matching (L4) needs a locally installed embedding model and is off by default; AI adjudication (L5)
  needs explicit opt-in and an API key and only produces labelled suggestions.

## Checks
- Drawing checks are presence/identity only (by design: the drawing is not a quantity source).
- The drawing reference row requires a BOM line mentioning the drawing number; otherwise it asks the reviewer.
- Old ↔ New label expectations come only from PCOs in the same set; change instructions in other forms are
  not read.
- PCO affected codes must match BOM parent items exactly.
- The real delivery contains no PCO or old/new label revision pair, so these checks have only synthetic
  validation. No standalone case-label source was supplied.

## Review workflow
- Reviewer identity, slot and blind mode are a server-side session and cannot be changed from the browser.
  Sign-in needs a password, but registration is open to any `@bd.com` address without proving it belongs
  to the person: no confirmation email is sent, because BD mail blocks external senders. A company-wide
  deployment should use BD single sign-on. Forgotten passwords are set by an administrator. The session cookie is not marked `Secure` because
  the local server is plain HTTP.
- With Supabase accounts only the login is shared: decisions, terminology and runs stay on the laptop where
  they were made. Sign-in needs internet access. Supabase rate-limits sign-ins per IP address, and a
  whole office behind one address shares that limit.
- Sessions do not expire on their own; end one with "Sign out" or `kaizen review sessions --end <name>`.
- Decisions live in the workspace database. Re-running the same inputs, extraction output, parser/checker
  versions and terminology reproduces the same run id and row ids. Changes to extracted text, quantities,
  confidence or geometry produce a different run id, preventing stale reviews from silently re-attaching.

- Measured review effort is the time between opening a row and deciding it in the UI, counted only between
  5 seconds and 15 minutes per row; it cannot see time spent outside the tool and starts counting only once ten decisions are timed.
- The optional Excel round-trip reads only the importing reviewer's columns and never overwrites a decision
  changed after the export unless forced, but it cannot detect edits to engine columns (they are ignored) and
  a workbook edited by two people is imported as one reviewer's work.
- The run-to-run diff matches rows by comparison key; a comparison that disappears is reported as "gone",
  not as resolved, and SKUs present in only one run are counted, not diffed.

## Reporting
- Annotated BOM marks need page geometry; spreadsheet BOMs get a separate review page instead.
- Only reviewer decisions come back from an edited Excel workbook (`kaizen review import`, optional);
  other edits made in Excel are ignored.

## Not regulatory-compliant
This is a hackathon prototype. It is deterministic, auditable and offline, but it has not been validated
under a quality system and makes no compliance claim.
