# Kaizen Cross-Check

## Hosted collaboration

Kaizen now uses approved BD accounts, application administrators, and per-run ownership with View/Edit sharing. Users can make private copies, download independent workbooks and source files, and explicitly confirm self-approval. See [accounts, sharing and Render deployment](docs/hosted-collaboration.md). The web app no longer asks users to choose a facilitator or independent-reviewer slot; legacy CLI review commands remain available.


[![CI](https://github.com/Rahulreddy-23/Kaizen/actions/workflows/ci.yml/badge.svg)](https://github.com/Rahulreddy-23/Kaizen/actions/workflows/ci.yml)

Deterministic, explainable, traceable cross-checking of JDE BOMs against product labels, packaging drawings,
PCOs and label revisions, with the reviewer as the final decision-maker. Built for the Innovation Week 2026
"BOM Cross-Check Automation" hackathon (BD / AAD).

> The system recommends. The reviewer decides. Every recommendation says why, points at the page and box it
> came from, and is reproducible from the recorded inputs, thresholds and terminology version.

> New here? Read [docs/solution-overview.md](docs/solution-overview.md): the problem and the solution in plain language.

## What it does
- Reads the documents reviewers already download: JDE BOM prints (PDF) or exports (XLSX/CSV), product labels
  (PDF, multi-column kit contents, old and new revisions), packaging drawings (text or scanned PDF, EN/ES callouts) and
  PCO forms (FM00835 as XLSX/CSV/PDF).
- Runs the five cross-checks from the brief: BOM ↔ Label, BOM ↔ Drawing, Label ↔ Drawing, PCO ↔ BOM,
  Old ↔ New label, plus coverage (a BOM for every PCO affected code).
- Classifies every comparison EXACT / EQUIVALENT / POTENTIAL / MISMATCH / MISSING with a typed discrepancy,
  severity, explanation and evidence (file, SHA-256, page, bounding box, raw text).
- Uses explicit, versioned terminology relationships (global / product-family / SKU, item-anchored) that
  reviewers create, edit, import/export, and that runs pin by version.
- Requires an approved `@bd.com` account. Application administrators approve registrations and appoint other administrators.
- Gives each uploaded run an owner, a descriptive name, and explicit View/Edit sharing. Shared runs appear in the recipient's workspace.
- Records decisions and approvals with the user's identity. Self-approval requires confirmation and is labelled in the history. Independent copies keep their own documents, decisions and action items.
- Turns the business-case projection into a **terminology worklist** (approve these pairings, in this order, and this many rows clear), **measures** review effort per row instead of assuming it, and keeps the reviewer on the keyboard (j/k/Enter, a/c/o/n, ? for help).
- Produces an audit-grade Excel workbook, an annotated BOM PDF with coloured marks, measured accuracy against
  ground truth, and a business case computed from the actual run (measured figure plus a labelled projection
  for after reviewers confirm strong pairings as relationships).
- Works fully offline. An AI provider can be enabled explicitly; its output is labelled as a suggestion and
  never changes a classification, decision or relationship.

## Install (macOS / Linux)
```bash
python3.13 -m venv .venv                 # Python 3.12+ works
.venv/bin/pip install -e ".[dev]"        # engine + API + test tools
cd ui && npm install && npm run build && cd ..   # reviewer UI (optional; API works without it)
```

## Install (Windows PowerShell)

Install Python 3.12+ and Node.js 20+ first, then run from a clean checkout:
```powershell
py -3.13 -m venv .venv                    # use py -3.12 if that is your installed version
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"         # engine + API + test tools
Push-Location ui; npm install; npm run build; Pop-Location   # reviewer UI (optional; API works without it)
```
If PowerShell prevents activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` for the current session, then activate again.

## Run
```bash
.venv/bin/kaizen run <folder> --out out/myrun   # one SKU set per sub-folder (bom.*, label.pdf, label_old.pdf, drawing.pdf) plus pco/*.xlsx|pdf
.venv/bin/kaizen serve                          # local API + UI at http://127.0.0.1:8765 (register with your BD email, wait for admin approval, then sign in)
```

On Windows PowerShell, use:
```powershell
.\.venv\Scripts\kaizen.exe run <folder> --out out/myrun
.\.venv\Scripts\kaizen.exe serve
```
Outputs: `run.json` (documents, items, evidence, results, audit), `report.xlsx`. Reviewer decisions,
terminology and action items live in the workspace database (`./kaizen-workspace/kaizen.db`; change with
`--workspace` or `KAIZEN_WORKSPACE`).

## Demo
```bash
rm -rf kaizen-workspace
.venv/bin/kaizen demo          # golden dataset: run + measured accuracy + workbook
.venv/bin/kaizen serve         # then follow docs/demo-script.md in the browser
```

## Tests and evaluation
```bash
.venv/bin/pytest                                   # unit + integration + golden floors; private-data tests when available
.venv/bin/kaizen eval datasets/golden --out out/e  # precision / recall per check vs ground-truth.json
.venv/bin/kaizen perf --skus 8 --skus 100          # timing and memory on synthetic datasets
```

## Commands
| Command | Purpose |
|---|---|
| `run` / `check` / `report` / `ingest` | Run everything; check only; workbook from a saved run (reviews merged); parse only. |
| `eval` | Run a dataset with `ground-truth.json` and report accuracy; `--fail-under` for CI. |
| `demo`, `serve`, `perf` | Demo run; local API + UI; performance series. |
| `terminology list/show/add/update/deactivate/activate/delete/history/import/export/sync-defaults` | Manage relationships (every change is a new version). |
| `certificate <run.json> [--sku]` | One-page cross-check certificate per SKU (run id, file hashes, counts, reviewers, open action items). |
| `diff <before.json> <after.json> [--json]` | Resolved, new and still-open discrepancies between two runs. |
| `review import <run.json> <file.xlsx> --slot --reviewer [--dry-run] [--force]` | Optional Excel round-trip: apply decisions recorded in the exported workbook. |
| `review policy [--set required\|optional]`, `review sessions [--end <name>]` | Blind-review policy (server-side, never changeable from the UI); open reviewer sessions. |
| `auth show`, `auth supabase <url> <key>`, `auth local` | Where sign-in accounts are checked: this workspace (default) or a shared Supabase project. |
| `users list`, `users reset <email>` | Local accounts only: list them; clear one so the reviewer can sign up again. |
| `runs list`, `runs relationships <run>` | Runs in the workspace; reconstruct the exact relationship versions a run used. |
| `dataset build`, `dataset corrected <sku>` | Regenerate the synthetic golden dataset (byte-stable); write a corrected copy of one SKU set for rehearsing verify-and-close. |

## Architecture
```
files → detect → parsers → canonical model (evidence) → categorise → group/coverage
      → match ladder (normalise · exact · relationship · fuzzy+numeric guard · [semantic] · [AI suggestion])
      → one-to-one assignment → checks (pairing engine + policies; PCO; revision) → results with roles
      → run (hashes, thresholds, terminology snapshot, audit) → review store (2 reviewers, blind, states)
      → action items / mining / business case → Excel, annotated PDF, evaluation, API + UI
```
Details and the full diagram: `docs/final-architecture.md`. API contract: `docs/api-contract.md`.

## Supported document types
| Type | Formats | Notes |
|---|---|---|
| BOM | JDE "Bill of Material Print" PDF; XLSX/CSV export | Multi-page, FreeText redline annotations captured, non-physical lines categorised with reasons. |
| Label | PDF (text); image-only PDF via optional OCR | REF, product name, two/three-column kit contents, wrapped lines, `(3 per)` / `(1 pair)` idioms; `label_old.pdf` = previous revision. |
| Drawing | Text PDF; scanned PDF via offline OCR | Multi-sheet title block and EN/ES callouts, conditionality and instructions retained. Repeated callouts compared once with occurrence evidence. Presence source only. |
| PCO | FM00835 XLSX/CSV/PDF | Affected codes, ADD/DELETE/SUBSTITUTE/MODIFY rows with qty and operation sequence. |

## Limitations
See [known limitations](docs/known-limitations.md) and [real-data validation](docs/real-data-validation.md).
Diagram OCR reads text; pictured component identity, leader endpoints and placement still need review.
Real-data matching needs approved terminology and assembly mappings. Hand-drawn redlines and case labels
are not parsed; thresholds are tuned on synthetic data. No compliance claim.

## Optional: shared sign-in with Supabase
The hosted app stores accounts in its central workspace by default. Supabase can optionally check passwords instead. **Only email and password authentication move to Supabase.** Kaizen's account approvals, sessions, decisions, run grants and documents remain in the central workspace. Provider accounts still need Kaizen administrator approval. Sign-in with this provider needs internet access.
**No email is ever sent**: BD mail blocks external senders, so there are no confirmation or reset emails.

In the Supabase dashboard (once per project):
1. **Authentication → Sign In / Providers:** keep *Allow new users to sign up* on and turn **Confirm
   email off** (a confirmation email would never arrive, and the account could not sign in).
   Optionally set the email provider's *Minimum password length* to 10, to match Kaizen.
2. Copy the **Project URL** and the **anon / publishable** key (Project Settings → API Keys). Never use
   the `service_role` / secret key; Kaizen refuses it.

Then configure the application server (once):
```bash
.venv/bin/kaizen auth supabase https://<project>.supabase.co <anon-or-publishable-key>
.venv/bin/kaizen auth show      # confirms where accounts are checked; `kaizen auth local` switches back
```
The environment variables `KAIZEN_SUPABASE_URL` and `KAIZEN_SUPABASE_KEY` do the same and take
precedence. Accounts created locally beforehand are not copied: each reviewer signs up once. Accounts are
listed in the dashboard under Authentication → Users. Kaizen only lets `@bd.com` addresses in; anyone
holding the public key could create a non-BD account directly in Supabase, but it cannot sign in to Kaizen.

### Forgotten passwords (Supabase)
The admin sets a new password and tells the reviewer. In the Supabase dashboard open **SQL Editor**, run
this with the reviewer's address and a new password of at least 10 characters, and check it reports one
row updated:
```sql
update auth.users
set encrypted_password = extensions.crypt('New-password-123', extensions.gen_salt('bf')),
    updated_at = now()
where email = 'dharma.reddy@bd.com';
```
Alternatively delete the user (Authentication → Users) and let them sign up again. Decisions already
recorded keep their address either way.

## Optional AI configuration
Off by default (`NullProvider`; no external calls). To enable suggestions on unresolved pairs:
```bash
pip install anthropic
export KAIZEN_AI_PROVIDER=anthropic ANTHROPIC_API_KEY=...   # optional: KAIZEN_AI_MODEL
```
Only the two descriptions and the SKU/item number are sent. Every suggestion is labelled "AI SUGGESTION",
recorded with provider, model, prompt version and timestamp in the run, and never pairs items on its own.
Semantic matching (L4) accepts any local embedding function (`kaizen.matching.semantic.SemanticMatcher`).

## Optional OCR configuration
Scanned BOM, label and drawing pages use an installed offline engine automatically. The hosted Docker
image already includes Tesseract and its English language data. For a portable local installation:
```bash
.venv/bin/pip install -e ".[ocr]"
```
Alternatively install Tesseract with English language data and place it on `PATH`. Tesseract is preferred
when both engines are present. OCR runs locally at 240 DPI, preserves raw text, page boxes and confidence,
and records its engine in the document. RapidOCR supplies line-level confidence and proportionally split
word boxes; Tesseract supplies individual word boxes. A damaged label REF text layer is re-read from its
image. Missing engines or unreadable pages produce warnings and block affected comparisons.

## Validate the supplied BD delivery

Keep `trainingdataset/` local (it is ignored by Git), then run:

```bash
.venv/bin/python scripts/audit_real_data.py trainingdataset --out out/real-bd
.venv/bin/pytest tests/real tests/unit/test_real_layouts.py
```

The audit writes `run.json`, `report.xlsx`, `validation.json` and `validation.md`. It independently compares
the four BOM PDFs with their JDE spreadsheet exports, counts duplicate rows, and reports unresolved
comparisons. The supplied delivery validates 373 BOM rows, all 140 label quantities and selected callouts
on every drawing sheet. These extraction checks do not establish real-data matching accuracy or release
approval. See [the detailed findings and remaining work](docs/real-data-validation.md).

For the protected relationship workbook, obtain a permitted readable export from an authorized owner.
The Terminology page and `kaizen terminology inspect/import` support worksheet selection, column mapping,
a preview, atomic validation and repeat imports without duplicate rules. Then run the audit with
`--workspace kaizen-workspace --baseline out/real-bd/run.json --out out/real-bd-after-relationships` to
measure coverage changes on identical input files. See [the import workflow](docs/relationship-import.md).

## Documents
`docs/solution-overview.md` (plain-language overview for presenting), `docs/system-description.md` (what was built, module by module),
`docs/design/DESIGN.md` and `docs/design/PRODUCT.md` (the reviewer interface's visual system and product truth),
`docs/problem-understanding.md` (problem and proposal), `docs/implementation-plan.md` (plan and status),
`docs/final-architecture.md`, `docs/api-contract.md`, `docs/demo-script.md`, `docs/test-strategy.md`,
`docs/known-limitations.md`, `docs/security-review.md`, `datasets/golden/SCENARIOS.md`.
