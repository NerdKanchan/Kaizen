# Import an authorized relationship export

The supplied Relationship Input WorkBook is protected by Microsoft rights management. Kaizen can import
a readable export; it cannot obtain the organization's access rights or remove protection itself.

An authorized document owner opens the original in Excel using their organization account and, where
the document policy permits it, exports the relationship table as a readable XLSX or CSV. If export is
disabled, the owner needs to provide a permitted extract. Keep the original intact and the readable
export local, outside the document input folder. `out/` is ignored by Git and is a suitable location.
Preserve item numbers as text, including their leading zeros. Convert formulas to their evaluated values.

## Use the app

On Terminology → Import and export:

1. Select the readable export and its header row, then choose Read columns.
2. Select the relationship worksheet if needed and read its columns again.
3. Map one canonical wording column and the columns containing its approved equivalent wordings.
   Map BOM item numbers to Item Anchors when the relationship applies to those components.
4. Set the scope to `global`, `family:<prefix>` or `sku:<code>`, or map an existing Scope column.
   A worksheet with multiple SKU scopes needs a Scope column containing those formatted values.
5. Choose Preview import. Check the terms, anchors, scope, active status and proposed creates/updates.
6. Choose Import approved relationships after confirming the source pairs. Changes apply to the next run.

Aliases within a cell use semicolons or newlines; commas remain part of descriptions. Additional fields
support IDs, document types, active status and notes. Only map an ID when intentionally updating a Kaizen
relationship. All invalid rows must be corrected before any import is saved. Re-importing an identical
no-ID relationship avoids duplicates and preserves any existing inactive status. Historical runs retain
their original terminology snapshots.

New rules record the source filename, SHA-256 hash, worksheet, row and importing reviewer. Updates record
the import source and hash in version history. Shared terminology imports require an application administrator.

## Use the CLI

Inspect the actual sheet and column names first:

```bash
.venv/bin/kaizen terminology inspect out/authorized-relationships.xlsx
.venv/bin/kaizen terminology inspect out/authorized-relationships.xlsx --sheet "Approved pairs" --header-row 2
```

The names below are examples, not claims about the protected workbook's layout. Substitute the export's
actual names. A canonical row represents one component; aliases must refer to that same component.

```bash
.venv/bin/kaizen --workspace kaizen-workspace terminology import out/authorized-relationships.xlsx \
  --sheet "Approved pairs" --header-row 2 \
  --canonical-column "Label Wording" \
  --alias-column "ERP Description" --alias-column "Drawing Wording" \
  --anchor-column "Component" --default-scope sku:1175108DNS \
  --by quality --dry-run
```

After reviewing the preview, run the same command without `--dry-run`. For a Kaizen-format export, no
column options are required. Invalid rows return exit code 2 and save no relationships.

## Measure coverage on the same dataset

Keep the previous `run.json` and write the new audit to a separate output folder. The audit uses the
workspace's approved active terminology and registers the new run with its exact relationship versions:

```bash
.venv/bin/python scripts/audit_real_data.py trainingdataset \
  --workspace kaizen-workspace \
  --baseline out/real-bd/run.json \
  --out out/real-bd-after-relationships
```

`validation.json` and `validation.md` show review rows before/after, added auto-cleared rows and changes
in classifications for each check. Coverage comparisons require identical input paths and file hashes.
If extraction also changed, the deltas can reflect that change as well as terminology. Coverage is not
accuracy: reviewer-approved true pairings and discrepancies are still needed to measure false clears.
