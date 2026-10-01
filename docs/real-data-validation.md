# Real BD documents: extraction validation and remaining work

On 30 September 2026 the problem owners' delivery of four real SKU sets was run through Kaizen locally.
The source files, the detailed findings (which name BD documents) and the private regression suite stay on
the team's machines and are ignored by Git: `trainingdataset/`, `docs/private/` and `tests/real/`. This page
is the public summary. The audit forces the offline provider, so no page is sent to an AI service.

## What the delivery contains

Four SKU sets, each with a JDE BOM report (PDF), a unit label and one ten-sheet packaging drawing, plus a
second copy of every file in type folders, the four BOMs as JDE spreadsheet exports, and an encrypted
relationship workbook protected by a BD sensitivity label. The labels and every drawing sheet are image scans rotated by 270 degrees; one label
also carries a damaged text layer whose REF cannot be read. There is no PCO, no old/new label pair and no
case label, so those checks cannot be validated from this delivery.

## Where the application was, and what changed

Before this work the tool recognised the four BOMs but skipped every label and drawing, because the released
file names carry BD document numbers rather than words such as "label", and scanned drawings had no OCR path.
The BOM parser also lost 129 of 373 rows, because JDE indents its column headings
independently of the row data.

The changes wire offline OCR (RapidOCR, or Tesseract where installed) into the BOM, label and drawing
parsers; keep every box in the page's displayed orientation so highlights land on rotated scans; align JDE
columns from the rows themselves; read bilingual callouts, instructions, conditional notes and the revision
cell on drawings; compare identical copies once; and make run identity depend on what was extracted, so a
different OCR result is never mistaken for the same run.

## What the validation establishes

- **BOM extraction parity.** The four BOM PDFs agree with their independently parsed JDE exports on every
  compared field (item, description, quantity, unit, operation sequence, effective dates) for all
  373 rows: yes. This proves extraction, not that either source is the
  approved specification.
- **Labels.** Every label yields 35 entries. The private suite checks each primary quantity and the pack
  idioms (such as "3 per pouch" and "1 pair") against values transcribed from the page images.
- **Drawing.** All ten sheets are read, with named components checked on every sheet. The revision is read
  with low confidence and stays review-required. OCR reads the text on a drawing; it cannot yet prove which
  pictured object a leader points at, cavity occupancy or placement.

## Current comparison result

Counts from the local audit with the default relationship store, after the review fixes below. Exempt rows
are shown separately and are not part of the classification counts. **MISSING means no accepted pairing was
found**; it is not a verified product defect, and none of these figures is a measured matching accuracy.

| Check | EXACT | EQUIVALENT | POTENTIAL | MISSING | Needs review | Exempt |
|---|---:|---:|---:|---:|---:|---:|
| BOM ↔ Label | 11 | 24 | 30 | 168 | 198 | 223 |
| BOM ↔ Drawing | 8 | 8 | 188 | 86 | 274 | 138 |
| Label ↔ Drawing | 40 | 5 | 130 | 63 | 197 | 85 |

669 rows need review across the three checks. Extraction is now dependable on this delivery;
matching is the limit. JDE descriptions are terse and noun-first ("MASK, VAPOR BARRIER"), while labels are
customer wording ("Mask"), so most real pairings need approved terminology before they can clear.

## Review follow-ups (30 September)

A review of the real-data work found and fixed these before commit:

- A single unparsed label line, or a BOM page without a table (for example "End of Report"), no longer
  replaces a whole SKU's comparison with one blocker. Only pages from which nothing could be read block;
  a BOM row that looks like a component but does not parse becomes its own blocker row while the rest of
  the BOM is compared.
- A label page whose REF is missing from the text layer is re-read by OCR only while the label's identity
  is unknown, and its native text is kept when OCR is unavailable or reads nothing.
- Words such as REFERENCE or REFRIGERATE are no longer read as a REF catalogue number.
- Tesseract output is parsed as plain TSV, so an inch mark cannot swallow the rest of a page.
- A NOTES block high on a drawing sheet no longer hides the callouts beneath it, and an English-only scanned
  drawing keeps its callouts.
- A trademark suffix glued to a product name by OCR ("SherlockTM") is removed, so approved relationships
  such as the sensor holder match.

## What is still missing

| Priority | Gap | What resolves it |
|---|---|---|
| 1 | Approved terminology | The relationship workbook is protected by a BD sensitivity label with rights management, so there is no password to supply. Someone with access opens it in Excel and saves an unprotected copy, kept local, which can then be imported as versioned relationships. |
| 1 | Real ground truth | A reviewer marks the true pairings, quantities, exclusions and discrepancies on these four sets. Only then can real precision, recall and false-clear rates be measured. |
| 1 | Drawing applicability | None of the four BOMs references the supplied drawing's number; they reference a different assembly drawing. The owners need to confirm the released drawing for each SKU. |
| 2 | Noun-first matching | One-word label lines ("Mask", "Gown", "Gloves") score zero against noun-first JDE descriptions. A rule that proposes such pairs as POTENTIAL would turn about 25 unpaired pairs on this delivery into review suggestions. |
| 2 | Compound assemblies and dimensions | The catheter label line covers a catheter with its stylet assembly that the BOM lists separately, and gauze sizes appear in inches on one side and centimetres on the other. Both need approved rules. |
| 2 | OCR engine in the hosted image | Real scans were validated with RapidOCR. The Docker image ships Tesseract only; install the `ocr` extra there or validate Tesseract on this delivery. |
| 3 | Other document types | A real PCO, an old/new label pair and a case label are needed to validate those checks. |

## Reproduce

```bash
.venv/bin/pip install -e ".[dev,ocr]"
.venv/bin/python scripts/audit_real_data.py trainingdataset --out out/real-bd
.venv/bin/pytest tests/real tests/unit/test_real_layouts.py tests/unit/test_extraction_robustness.py
.venv/bin/kaizen eval datasets/golden --fail-under 1.0
```

The audit writes `validation.md`, `validation.json`, `run.json` and `report.xlsx` under `out/`, which Git
ignores. The golden gate remains a synthetic benchmark: it still finds all seeded discrepancies with no false
positives or negatives.
