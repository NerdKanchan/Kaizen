"""Run-to-run diff: what changed between two runs of the same documents.

After corrected documents come back, the reviewer wants to see only what moved: discrepancies that are now
resolved, discrepancies that are new, and those still open. Rows are matched by the same stable comparison
key that action items use, so the diff does not depend on row ids.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kaizen.models import CheckResult, Run
from kaizen.review.action_items import comparison_key

DIFFED_ROLES = ("item", "header", "reference", "coverage", "change")
STATUSES = ("resolved", "new", "still_open", "changed", "unchanged", "gone", "not_covered")


@dataclass
class RowChange:
    key: str
    sku: str
    check: str
    status: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    note: str = ""


@dataclass
class RunDiff:
    before_run_id: str
    after_run_id: str
    skus: dict[str, list[str]]
    documents: dict[str, list[Any]]
    counts: dict[str, int]
    rows: list[RowChange] = field(default_factory=list)  # every row except the unchanged ones

    def to_dict(self) -> dict[str, Any]:
        return {"before_run_id": self.before_run_id, "after_run_id": self.after_run_id, "skus": self.skus, "documents": self.documents, "counts": self.counts, "rows": [asdict(r) for r in self.rows]}


def _brief(r: CheckResult) -> dict[str, Any]:
    return {
        "row_id": r.row_id, "classification": r.classification.value, "match_level": r.match_level.value,
        "discrepancies": [d.type.value for d in r.discrepancies], "severity": r.severity.value if r.severity else None,
        "requires_validation": r.requires_validation, "explanation": r.explanation,
        "a": (r.source_a.item_number, r.source_a.description, str(r.source_a.quantity) if r.source_a.quantity is not None else None) if r.source_a else None,
        "b": (r.source_b.description, str(r.source_b.quantity) if r.source_b.quantity is not None else None) if r.source_b else None,
    }


def _rows_by_key(run: Run) -> dict[str, list[CheckResult]]:
    out: dict[str, list[CheckResult]] = defaultdict(list)
    for r in run.results:
        if r.role in DIFFED_ROLES:
            out[comparison_key(r)].append(r)
    return out


def _rel(path: str, root: str) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _documents(before: Run, after: Run) -> dict[str, list[Any]]:
    b = {_rel(d.path, before.metadata.input_root): d.sha256 for d in before.documents}
    a = {_rel(d.path, after.metadata.input_root): d.sha256 for d in after.documents}
    return {
        "changed": [{"path": p, "before_sha256": b[p], "after_sha256": a[p]} for p in sorted(set(a) & set(b)) if a[p] != b[p]],
        "added": sorted(set(a) - set(b)),
        "removed": sorted(set(b) - set(a)),
    }


def _status(before: CheckResult | None, after: CheckResult | None) -> tuple[str, str]:
    if before is not None and after is None:
        if before.discrepancies:
            return "gone", "the comparison no longer exists in the later run (a document line was removed or renamed); it was NOT verified as fixed"
        return "gone", "the comparison no longer exists in the later run"
    if before is None and after is not None:
        return ("new", "a discrepancy that was not there before") if after.discrepancies else ("changed", "a new comparison with no discrepancy")
    assert before is not None and after is not None
    b_disc, a_disc = bool(before.discrepancies), bool(after.discrepancies)
    if b_disc and not a_disc and after.requires_validation:
        return "still_open", "no discrepancy is reported, but the later comparison still requires validation"
    if b_disc and not a_disc:
        return "resolved", "the discrepancy is no longer reported"
    if not b_disc and a_disc:
        return "new", "a discrepancy that was not there before"
    if b_disc and a_disc:
        same = [d.type.value for d in before.discrepancies] == [d.type.value for d in after.discrepancies]
        return "still_open", "still reported" + ("" if same else " (different discrepancy type)")
    if before.classification is not after.classification or before.requires_validation != after.requires_validation:
        return "changed", f"{before.classification.value} → {after.classification.value}"
    return "unchanged", ""


def diff_runs(before: Run, after: Run) -> RunDiff:
    b_skus, a_skus = {g.sku for g in before.groups}, {g.sku for g in after.groups}
    skus = {"added": sorted(a_skus - b_skus), "removed": sorted(b_skus - a_skus), "common": sorted(a_skus & b_skus)}
    b_rows, a_rows = _rows_by_key(before), _rows_by_key(after)
    counts = {s: 0 for s in STATUSES}
    rows: list[RowChange] = []
    common = set(skus["common"])
    for key in sorted(set(b_rows) | set(a_rows)):
        bl, al = b_rows.get(key, []), a_rows.get(key, [])
        for i in range(max(len(bl), len(al))):  # duplicate keys (rare) are aligned positionally
            b = bl[i] if i < len(bl) else None
            a = al[i] if i < len(al) else None
            sample = b or a
            assert sample is not None
            if sample.sku not in common:
                counts["not_covered"] += 1  # SKUs present in only one run are listed under `skus`, not diffed row by row
                continue
            status, note = _status(b, a)
            counts[status] += 1
            if status != "unchanged":
                rows.append(RowChange(key, sample.sku, sample.check.value, status, _brief(b) if b else None, _brief(a) if a else None, note))
    order = {s: i for i, s in enumerate(STATUSES)}
    rows.sort(key=lambda c: (order[c.status], c.sku, c.check, c.key))
    return RunDiff(before.metadata.run_id, after.metadata.run_id, skus, _documents(before, after), counts, rows)
