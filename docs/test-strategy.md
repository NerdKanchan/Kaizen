# Test strategy

Every layer has tests, and extraction failures found in the real BD delivery have hermetic regression
fixtures. Run the offline suite with `.venv/bin/pytest`; private-source/OCR tests run when their prerequisites
are available and otherwise skip. Runtime depends on the installed OCR engine and local hardware.

## Layers and what is asserted

| Layer | Tests | What is asserted |
|---|---|---|
| Canonical model | `tests/unit/test_models.py` | Validation (confidence 0–1, ordered bboxes, evidence required, non-empty explanations), enum coverage of the discrepancy taxonomy. |
| Normalisation | `test_normalize.py`, `test_hardening.py` | Table-driven: ™/®, `W/`, units, plurals, `.0`, `%`, dimensions, token order; determinism and idempotence. |
| Quantities | `test_quantity.py`, `test_quantity_compare.py` | `N Each -` parsing, `(3 per)`, `(1 pair)`, per-pouch idioms; unit-aware comparison and idiom reconciliation. |
| BOM categorisation | `test_bom_categorize.py` | Every category rule, zero and unreadable quantities, reasons are explanatory. |
| PDF primitives | `test_pdf_words.py` | Word boxes, line grouping (with sub-pixel jitter), column bands, gap splitting, annotation capture and exclusion. |
| Parsers | `test_bom_pdf.py`, `test_bom_table.py`, `test_label_pdf.py`, `test_pco.py`, `test_drawing.py`, `test_ocr_and_extraction_method.py` | Rendered fixtures designed to break naive extraction: multi-page BOMs, blank quantities, XLSX/CSV aliases, two/three-column labels, wrapped lines, decoy REFs, PCO XLSX and PDF forms, EN/ES callouts, conditional callouts, noise, image-only pages with and without an OCR engine (mocked). |
| Terminology | `test_terminology_store.py`, `test_terminology_repository.py`, `test_terminology_exchange.py` | Scope (global/family/SKU), item anchors (incl. the over-matching regression), versioning, history survives delete, historical run reconstruction, Excel/CSV round trips, `sync-defaults` never touching edited rows. |
| Matching | `test_fuzzy.py`, `test_ladder.py`, `test_assignment.py`, `test_semantic.py`, `test_providers.py` | Numeric guard, single-token guard, stopwords, level order, fuzzy never EXACT, ambiguity delta, contested candidates, semantic and AI layers can only yield POTENTIAL/weak outcomes. |
| Checks | `test_bom_label_check.py`, `test_pairing_engine.py`, `test_pco_bom_check.py`, `test_label_revision.py`, `test_adversarial.py` | Every classification and discrepancy type per check, REF/parent, duplicate BOM rows, unreadable label blocker, conditional/packaging exemptions, PCO ADD/DELETE/SUBSTITUTE/MODIFY with redlines, coverage blockers, expected vs unexpected label changes. |
| Review layer | `test_review_store.py`, `test_action_items.py`, `test_mining_and_business.py` | State machine, blind mode, disagreement, finalisation history, bulk accept, action items linked to rows, verify & close via comparison keys, mining evidence counts, business case honesty. |
| Reporting | `test_excel_report.py`, `test_excel_review_export.py`, `test_annotated_bom.py` | Sheet set and column order, conditional formatting and validations, metadata answers "where did this come from", decisions merged without touching engine columns, marks never over printed text, spreadsheet fallback. |
| Pipeline / CLI / API | `test_pipeline.py`, `test_detect_grouping.py`, `tests/integration/test_cli.py`, `test_cli_terminology.py`, `test_api.py` | Deterministic run ids, document-id uniqueness, grouping strategies, every CLI command, the full API contract including blind mode, save-as-relationship feeding the next run, mining, action items, exports, uploads and the demo loader. |
| Golden accuracy | `tests/golden/test_accuracy.py`, `tests/unit/test_dataset_build.py` | Floors on precision/recall/pairing/classification per check against a deterministic, byte-stable dataset whose ground truth is generated from the same scenario definitions. |
| Performance | `test_perf.py` (+ `kaizen perf`) | The harness builds N-SKU datasets and times ingest / matching / report. |

## Fixtures
Documents are rendered, not hand-drawn: `kaizen.datasets` produces JDE-style BOM prints (with FreeText redline
annotations), two-column labels, multi-sheet drawings and FM00835 PCO forms, all byte-stable. When a parser bug
is found, the failing fragment becomes a fixture (see `test_hardening.py`, `test_adversarial.py`).

## What is deliberately not mocked
Parsers, matching, checks, storage and the API execute in tests. Hermetic extraction tests mock OCR output
to exercise failure and geometry handling. `tests/integration/test_offline_ocr.py` also executes an installed engine
on a scanned JDE fixture; `tests/real/test_bd_delivery.py` runs OCR on the private source labels and drawing; it stays local and is ignored by Git because it holds values transcribed from BD documents.

## Real-data validation

`tests/unit/test_real_layouts.py` covers indented JDE headings, joined OCR starters, original evidence,
rotated page boxes and marks, encrypted/corrupt input handling, duplicate drawing occurrences, shared
drawings, inferred identities, low-confidence headers, incomplete extraction blockers, source parity
and run identity when extraction output changes. These fixtures contain no customer PDF pages.

The optional private suite validates four BOM PDFs against independently parsed JDE exports (all 373 rows,
including duplicate components, quantities, units, operation sequences and effective dates). Label
quantities and pack idioms were transcribed from the page images. Drawing assertions are named visual
probes on every sheet, plus identity, revision, conditionality and presence-only behavior.

```bash
.venv/bin/python scripts/audit_real_data.py trainingdataset --out out/real-bd
.venv/bin/pytest tests/real tests/unit/test_real_layouts.py
```

The audit forces the offline provider, retains all source copies, avoids duplicate comparisons and writes
a reviewable workbook, JSON run and extraction report. Source files and generated output are ignored by
Git. See [real-data validation](real-data-validation.md) for the distinction between extraction evidence
and matching accuracy.

## Known gaps
Real pairing/discrepancy accuracy cannot be measured without independently reviewed ground truth. The
encrypted relationship workbook remains unavailable, and there are no real PCO, revision-pair or case-label
fixtures in this delivery. Golden accuracy floors remain unchanged; they are not a real-data acceptance gate.
