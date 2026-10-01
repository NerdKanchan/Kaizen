"""Optional Excel round-trip: reviewer decisions recorded in the exported workbook, imported back.

Reviewers live in Excel and may prefer to work offline. This is an *optional* path beside the UI, with
rules that keep it as safe as the UI:

- the workbook must belong to the run it is imported into (the Run ID on the Run_Metadata sheet);
- only the importing reviewer's own columns are read, so nobody can write the other reviewer's decisions;
- every value is validated; an OVERRIDE must name its classification (`OVERRIDE→EQUIVALENT`);
- a decision the database changed *after* the workbook was exported is a conflict and is never overwritten
  unless the caller says `force`;
- a dry run reports everything and writes nothing; every applied decision goes through the normal store, so
  it is audited like a decision made in the UI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import openpyxl

from kaizen.models import Classification, Run
from kaizen.review.store import ReviewStore

CHECK_SHEETS = ("BOM_Label", "BOM_Drawing", "Label_Drawing", "PCO_BOM", "Label_Revision")
SLOT_COLUMNS = {1: ("Reviewer Decision", "Reviewer Comment"), 2: ("Reviewer 2 Decision", "Reviewer 2 Comment")}
PLAIN_DECISIONS = ("ACCEPT", "CONFIRM_DISCREPANCY", "NEEDS_MORE_INFORMATION")
OVERRIDE_SEPARATORS = ("→", "->", ":")


@dataclass
class RoundTripResult:
    run_id: str
    slot: int
    reviewer: str
    dry_run: bool
    force: bool
    exported_at: str | None
    applied: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    invalid: list[dict[str, Any]] = field(default_factory=list)
    unknown_rows: list[str] = field(default_factory=list)

    def summary(self) -> str:
        head = "Dry run (nothing written): " if self.dry_run else ""
        return (f"{head}{len(self.applied)} applied, {len(self.unchanged)} unchanged, {len(self.conflicts)} conflict(s), "
                f"{len(self.invalid)} invalid, {len(self.unknown_rows)} unknown row(s) — slot {self.slot}, reviewer {self.reviewer}"
                + (", conflicts overwritten (force)" if self.force and self.conflicts else "")
                + (", conflicts left untouched" if self.conflicts and not self.force else ""))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"summary": self.summary()}


def parse_decision(cell: Any) -> tuple[str, str | None] | str:
    """`ACCEPT` → ("ACCEPT", None); `OVERRIDE→EQUIVALENT` → ("OVERRIDE", "EQUIVALENT"); anything else → an error string."""
    text = str(cell or "").strip()
    if not text:
        return "empty"
    upper = text.upper()
    if upper in PLAIN_DECISIONS:
        return upper, None
    if upper.startswith("OVERRIDE"):
        rest = upper[len("OVERRIDE"):].strip()
        for sep in OVERRIDE_SEPARATORS:
            if rest.startswith(sep):
                rest = rest[len(sep):].strip()
                break
        else:
            if rest:
                return f"unrecognised decision {text!r}"
        if not rest:
            return "OVERRIDE must name the classification, e.g. OVERRIDE→EQUIVALENT"
        if rest not in {c.value for c in Classification}:
            return f"unknown override classification {rest!r} (use one of {', '.join(c.value for c in Classification)})"
        return "OVERRIDE", rest
    return f"unrecognised decision {text!r} (use ACCEPT, OVERRIDE→<classification>, CONFIRM_DISCREPANCY or NEEDS_MORE_INFORMATION)"


def read_metadata(wb) -> dict[str, str]:
    if "Run_Metadata" not in wb.sheetnames:
        raise ValueError("this workbook has no Run_Metadata sheet; it was not exported by Kaizen Cross-Check")
    out: dict[str, str] = {}
    for row in wb["Run_Metadata"].iter_rows(min_row=1, max_row=40, max_col=2):
        if row[0].value in ("Run ID", "Exported at") and row[1].value is not None:
            out[str(row[0].value)] = str(row[1].value)
    return out


def _column_map(sheet) -> dict[str, int]:
    return {str(c.value): i + 1 for i, c in enumerate(sheet[1]) if c.value is not None}


def import_decisions(workspace, run: Run, path: Path | str, slot: int, reviewer: str, *, dry_run: bool = False, force: bool = False, review_store: ReviewStore | None = None) -> RoundTripResult:
    if slot not in SLOT_COLUMNS:
        raise ValueError("reviewer slot must be 1 or 2")
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise ValueError("a reviewer name is required")
    try:
        wb = openpyxl.load_workbook(Path(path), read_only=False, data_only=True)
    except Exception as e:  # zipfile.BadZipFile, KeyError from a non-xlsx zip, ... — the file is not a workbook
        raise ValueError(f"{Path(path).name} is not a valid .xlsx workbook ({e.__class__.__name__})") from e
    try:
        with workspace.db.transaction():
            meta = read_metadata(wb)
            run_id = run.metadata.run_id
            if meta.get("Run ID") != run_id:
                raise ValueError(f"this workbook belongs to run {meta.get('Run ID') or '(unknown)'}, not {run_id}; export the workbook for this run first")
            exported_at = meta.get("Exported at")
            result = RoundTripResult(run_id, slot, reviewer, dry_run, force, exported_at)
            review = review_store or ReviewStore(workspace.db)
            known = {r.row_id for r in run.results}
            finalized = set(review.finals(run_id))
            decision_col, comment_col = SLOT_COLUMNS[slot]

            for name in CHECK_SHEETS:
                if name not in wb.sheetnames:
                    continue
                sheet = wb[name]
                cols = _column_map(sheet)
                if "Row ID" not in cols or decision_col not in cols:
                    continue
                for r in range(2, sheet.max_row + 1):
                    rid = sheet.cell(row=r, column=cols["Row ID"]).value
                    if rid is None or str(rid).strip() == "":
                        continue
                    rid = str(rid).strip()
                    raw = sheet.cell(row=r, column=cols[decision_col]).value
                    parsed = parse_decision(raw)
                    if parsed == "empty":
                        continue
                    if rid not in known:
                        result.unknown_rows.append(rid)
                        continue
                    if isinstance(parsed, str):
                        result.invalid.append({"row_id": rid, "sheet": name, "value": str(raw), "reason": parsed})
                        continue
                    decision, override = parsed
                    if rid in finalized:
                        result.invalid.append({"row_id": rid, "sheet": name, "value": str(raw), "reason": "row is finalized; change it in the UI to reopen it before importing"})
                        continue
                    comment = str(sheet.cell(row=r, column=cols[comment_col]).value or "").strip() if comment_col in cols else ""
                    existing = review.decisions(run_id, rid).get(slot)
                    if existing and existing.decision == decision and (existing.override_classification or None) == override and (existing.comment or "") == comment:
                        result.unchanged.append(rid)
                        continue
                    if existing and not force and (exported_at is None or existing.decided_at > exported_at):
                        result.conflicts.append({"row_id": rid, "sheet": name, "workbook": raw, "database": existing.decision + (f"→{existing.override_classification}" if existing.override_classification else ""), "database_decided_at": existing.decided_at, "database_reviewer": existing.reviewer})
                        continue
                    if not dry_run:
                        review.decide(run_id, rid, slot, reviewer, decision, comment, override, blind=False, timed=False)
                    result.applied.append(rid)

            if not dry_run:
                workspace.db.audit(reviewer, "review.import", f"{run_id}: {result.summary()} ({Path(path).name})")
            return result
    finally:
        wb.close()
