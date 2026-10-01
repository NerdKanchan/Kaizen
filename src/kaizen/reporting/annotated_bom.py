"""Marked-up BOM PDF: the digital version of the coloured check marks reviewers draw on BOM printouts.

Marks sit in the right margin (never over printed text): colour = which check (blue label, purple drawing,
orange PCO), shape = status (tick = clear, cross = discrepancy, circle = needs review). A 'Checked by' stamp and
a legend go on page 1. If a BOM has no page geometry (XLSX/CSV source) a separate review page is produced
instead of guessing positions."""

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from kaizen.ingest.pdf_words import extract_words
from kaizen.models import Document, Run, Severity

CHECK_COLORS = {"BOM_LABEL": (0.05, 0.35, 0.9), "BOM_DRAWING": (0.55, 0.1, 0.75), "PCO_BOM": (0.95, 0.5, 0.05)}
CHECK_LABELS = {"BOM_LABEL": "Compared with Label", "BOM_DRAWING": "Compared with PKG Drawings", "PCO_BOM": "Compared with PCO"}
CHECK_OFFSETS = {"BOM_LABEL": 0.0, "BOM_DRAWING": 9.0, "PCO_BOM": 18.0}
MARK = 6.0
_FONT = pymupdf.Font("helv")


@dataclass(frozen=True)
class Mark:
    page: int
    item: str
    check: str
    kind: str  # clear | discrepancy | review
    x: float
    y: float


@dataclass
class AnnotatedOutcome:
    path: Path
    marks: int
    fallback: bool
    mark_list: list[Mark] = field(default_factory=list)


def _kind(r, review_states: dict[str, str] | None) -> str:
    if review_states:
        st = review_states.get(r.row_id)
        if st == "clear":
            return "clear"
        if st == "discrepancy":
            return "discrepancy"
    if any(d.severity is not Severity.INFO for d in r.discrepancies) or r.classification.value in ("MISMATCH", "MISSING"):
        return "discrepancy"
    if r.requires_validation:
        return "review"
    return "clear"


def _bom_rows(run: Run, bom: Document):
    for r in run.results:
        if r.role != "item" or r.check.value not in CHECK_COLORS:
            continue
        if r.source_a is not None and r.source_a.doc_id == bom.id:
            yield r, r.source_a
        elif r.source_b is not None and r.source_b.doc_id == bom.id:
            yield r, r.source_b


def _draw_mark(page: pymupdf.Page, kind: str, x: float, y: float, color) -> None:
    shape = page.new_shape()
    s = MARK
    def point(px, py):
        return pymupdf.Point(px, py) * page.derotation_matrix
    if kind == "clear":
        shape.draw_line(point(x, y), point(x + s * 0.4, y + s * 0.5))
        shape.draw_line(point(x + s * 0.4, y + s * 0.5), point(x + s, y - s * 0.5))
    elif kind == "discrepancy":
        shape.draw_line(point(x, y - s * 0.5), point(x + s, y + s * 0.5))
        shape.draw_line(point(x, y + s * 0.5), point(x + s, y - s * 0.5))
    else:
        shape.draw_circle(point(x + s / 2, y), s * 0.45)
    shape.finish(color=color, width=1.1)
    shape.commit()


def write_annotated_bom(run: Run, bom: Document, out_path: Path | str, checked_by: list[str] | None = None, review_states: dict[str, str] | None = None) -> AnnotatedOutcome:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(_bom_rows(run, bom))
    has_geometry = bom.path.lower().endswith(".pdf") and any(item.evidence.bbox is not None and item.evidence.page for _, item in rows)
    if not has_geometry:
        return _fallback_page(run, bom, rows, out_path, checked_by, review_states)
    doc = pymupdf.open(bom.path)
    marks: list[Mark] = []
    margin_x: dict[int, float] = {}
    for r, item in rows:
        ev = item.evidence
        if ev.bbox is None or not ev.page or ev.page > len(doc):
            continue
        page = doc[ev.page - 1]
        if ev.page not in margin_x:
            words = extract_words(page)
            max_x1 = max((w.x1 for w in words), default=page.rect.width - 40)
            base = max_x1 + 4
            if base + 3 * 9 + MARK > page.rect.width - 2:
                base = page.rect.width - 2 - 3 * 9 - MARK  # squeeze into whatever margin remains
            margin_x[ev.page] = max(base, max_x1 + 1)
        kind = _kind(r, review_states)
        x = margin_x[ev.page] + CHECK_OFFSETS[r.check.value]
        y = (ev.bbox.y0 + ev.bbox.y1) / 2
        _draw_mark(page, kind, x, y, CHECK_COLORS[r.check.value])
        marks.append(Mark(ev.page, item.item_number or "", r.check.value, kind, x, y))
    _stamp(doc[0], run, bom, checked_by)
    doc.save(out_path)
    doc.close()
    return AnnotatedOutcome(out_path, len(marks), False, marks)


def _stamp(page: pymupdf.Page, run: Run, bom: Document, checked_by: list[str] | None) -> None:
    w = pymupdf.TextWriter(page.rect)
    names = ", ".join(checked_by) if checked_by else "(reviewer names not recorded)"
    w.append((30, 14), f"Checked by {names}  |  Kaizen Cross-Check {run.metadata.run_id}  |  {run.metadata.timestamp.date().isoformat()}", font=_FONT, fontsize=7, )
    x = 330
    for check, label in CHECK_LABELS.items():
        w.append((x + 12, 26), f"{label}  (v clear, x discrepancy, o needs review)", font=_FONT, fontsize=5.5)
        _draw_mark(page, "clear", x, 24, CHECK_COLORS[check])
        x += 150
    w.write_text(page, color=(0.8, 0.1, 0.1), matrix=page.derotation_matrix)


def _fallback_page(run: Run, bom: Document, rows, out_path: Path, checked_by, review_states) -> AnnotatedOutcome:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    w = pymupdf.TextWriter(page.rect)
    names = ", ".join(checked_by) if checked_by else "(reviewer names not recorded)"
    w.append((30, 40), f"Annotated review page — BOM {bom.sku} ({Path(bom.path).name})", font=_FONT, fontsize=11)
    w.append((30, 56), "This BOM was supplied as a spreadsheet, so it has no page geometry to draw check marks on. Marks are listed per row instead.", font=_FONT, fontsize=7)
    w.append((30, 68), f"Checked by {names} | Kaizen Cross-Check {run.metadata.run_id} | {run.metadata.timestamp.date().isoformat()}", font=_FONT, fontsize=7)
    y = 92
    w.append((30, y), "Item", font=_FONT, fontsize=7)
    w.append((110, y), "Description", font=_FONT, fontsize=7)
    for i, label in enumerate(CHECK_LABELS.values()):
        w.append((330 + i * 90, y), label.replace("Compared with ", ""), font=_FONT, fontsize=7)
    by_item: dict[str, dict] = {}
    for r, item in rows:
        entry = by_item.setdefault(item.item_number or item.id, {"desc": item.description, "marks": {}})
        entry["marks"][r.check.value] = _kind(r, review_states)
    marks: list[Mark] = []
    y += 12
    for item, entry in by_item.items():
        if y > 760:
            w.write_text(page)
            page = doc.new_page(width=612, height=792)
            w = pymupdf.TextWriter(page.rect)
            y = 40
        w.append((30, y), item, font=_FONT, fontsize=6.5)
        w.append((110, y), entry["desc"][:48], font=_FONT, fontsize=6.5)
        for i, check in enumerate(CHECK_LABELS):
            kind = entry["marks"].get(check)
            if kind:
                x = 330 + i * 90
                _draw_mark(page, kind, x, y - 2, CHECK_COLORS[check])
                marks.append(Mark(page.number + 1, item, check, kind, x, y))
        y += 11
    w.write_text(page)
    doc.save(out_path)
    doc.close()
    return AnnotatedOutcome(out_path, len(marks), True, marks)
