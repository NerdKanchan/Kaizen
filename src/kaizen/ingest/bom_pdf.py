"""Parser for JDE 'Bill of Material Print' (R30460-style) PDFs.

Strategy: locate the column-header line by its labels, derive column x-bands from the label positions, group
words into visual lines, and read one component per line. Header key/values come from the lines above the
column header. FreeText annotations overlapping a row are captured as redlines (field + text).
"""

import re
import statistics
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pymupdf

from kaizen.ingest.bom_categorize import CATEGORIZER_VERSION, categorize
from kaizen.ingest.hashing import document_id, sha256_file
from kaizen.ingest.ocr import ocr_available, ocr_page, ocr_words
from kaizen.ingest.pdf_words import ColumnBand, Word, assign_columns, extract_annotations, extract_words, group_lines, line_bbox, line_text
from kaizen.ingest.quantity import parse_decimal
from kaizen.models import DocType, Document, DocumentItem, Evidence

PARSER_NAME = "bom_pdf"
PARSER_VERSION = f"2+cat{CATEGORIZER_VERSION}"

# Column labels in left-to-right order, as token sequences.
HEADER_LABELS: list[tuple[str, tuple[str, ...]]] = [
    ("level", ("Level",)),
    ("component_item", ("Component", "Item")),
    ("component_description", ("Component", "Description")),
    ("branch_plant", ("Branch/Plant",)),
    ("quantity_per", ("Quantity", "Per")),
    ("ext_qty", ("Ext", "Qty")),
    ("um", ("UM",)),
    ("t", ("T",)),
    ("effective_from", ("From",)),
    ("effective_thru", ("Thru",)),
    ("oper_seq", ("Seq", "No")),
    ("flags", ("R",)),
]
_HEADER_PATTERNS = {
    "parent_item": re.compile(r"Parent Item\s+(\S+)"),
    "parent_description": re.compile(r"Parent Description\s+(.*?)\s+Branch/Plant"),
    "branch_plant": re.compile(r"Branch/Plant\s+(\S+)"),
    "type": re.compile(r"\bType\s+(\S+)"),
    "batch_quantity": re.compile(r"Batch Quantity\s+((?!Batch)\S+)"),
    "batch_uom": re.compile(r"Batch UOM\s+(\S+)"),
    "requested_quantity": re.compile(r"Requested Quantity\s+(\S+)"),
    "requested_uom": re.compile(r"Requested UOM\s+(\S+)"),
    "bill_revision_level": re.compile(r"Bill Revision Level\s+(\S+)"),
    "as_of_date": re.compile(r"As of Date\s+(\S+)"),
    "report_id": re.compile(r"^(R\d{5})\b"),
}
_ITEM_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]*$")
_OCR_ITEM_RE = re.compile(r"^[A-Z]{0,5}\d{4,}[A-Z]{0,5}$")


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _find_header_line(lines: list[list[Word]]) -> tuple[int, list[ColumnBand]] | None:
    for idx, line in enumerate(lines):
        text = line_text(line).lower()
        if "component item" in text and "component description" in text:
            return idx, _bands_from_header(line)
    return None


def _bands_from_header(line: list[Word], page_width: float = 10_000) -> list[ColumnBand]:
    words = sorted(line, key=lambda w: w.x0)
    starts: list[tuple[str, float]] = []
    pos = 0
    for name, tokens in HEADER_LABELS:
        n = len(tokens)
        found = None
        for i in range(pos, len(words) - n + 1):
            if tuple(w.text.lower() for w in words[i : i + n]) == tuple(t.lower() for t in tokens):
                found = i
                break
        if found is None:
            continue
        starts.append((name, words[found].x0))
        pos = found + n
    bands: list[ColumnBand] = []
    for i, (name, x0) in enumerate(starts):
        x1 = starts[i + 1][1] - 2 if i + 1 < len(starts) else page_width
        bands.append(ColumnBand(name, x0 - 2, x1))
    return bands


def _text(cols: dict[str, list[Word]], name: str) -> str:
    return " ".join(w.text for w in cols.get(name, []))


def _looks_like_row(line: list[Word]) -> bool:
    """A level number followed by an item number: how every JDE component row starts."""
    return len(line) >= 3 and line[0].text.isdigit() and len(line[0].text) <= 3 and bool(_ITEM_RE.fullmatch(line[1].text))


def _align_body_columns(bands: list[ColumnBand], lines: list[list[Word]], allow_missing_level: bool = False) -> list[ColumnBand]:
    """JDE headings are indented independently of the row data. Learn the first three
    column starts from explicit level/item/description rows instead of losing short IDs
    or treating the first description word as part of a long item number."""
    samples = [l for l in lines if _looks_like_row(l) and l[1].x0 - l[0].x1 > 5]
    if not samples:
        samples = [l for l in lines if len(l) >= 3 and _OCR_ITEM_RE.fullmatch(l[0].text)] if allow_missing_level else []
        if not samples:
            return bands
        names = ("component_item", "component_description")
    else:
        names = ("level", "component_item", "component_description")
    starts = {name: statistics.median(l[i].x0 for l in samples) - 2 for i, name in enumerate(names)}
    updated = [(b.name, starts.get(b.name, b.x0)) for b in bands]
    return [ColumnBand(name, x0, updated[i + 1][1] if i + 1 < len(updated) else bands[-1].x1) for i, (name, x0) in enumerate(updated)]


def parse_bom_pdf(path: Path | str) -> Document:
    path = Path(path)
    sha = sha256_file(path)
    doc_id = document_id("bom", sha, path)
    pdf = pymupdf.open(path)
    header: dict[str, str] = {}
    items: list[DocumentItem] = []
    warnings: list[str] = []
    row_counter = 0
    # Pages whose rows could not be read at all, and single rows that looked like components but
    # did not parse. The first blocks comparison; the second is reported row by row.
    unreadable: set[int] = set()
    unparsed_rows: list[dict] = []
    for page in pdf:
        page_no = page.number + 1
        words = extract_words(page)
        page_method = "pdf_text"
        if not words and page.get_images(full=True):
            if not ocr_available():
                warnings.append(f"page {page_no}: image-only page and no OCR engine; install Tesseract or kaizen-crosscheck[ocr] — page skipped")
                unreadable.add(page_no)
                continue
            try:
                result = ocr_page(page)
                words = ocr_words(result)
                page_method = "ocr"
                header["ocr_engine"] = result.engine
                warnings.append(f"page {page_no}: OCR ({result.engine}, {result.dpi} dpi), {len(words)} words — verify item numbers and quantities against the image")
            except Exception as exc:
                warnings.append(f"page {page_no}: OCR failed ({type(exc).__name__}); page skipped")
                unreadable.add(page_no)
                continue
        lines = group_lines(words)
        found = _find_header_line(lines)
        if found is None:
            row_like = sum(_looks_like_row(line) for line in lines)
            # A cover, notes or "End of Report" page has no table to read. A page that holds rows
            # without a repeated header, or a scan whose header OCR missed, is incomplete extraction.
            if row_like or page_method == "ocr":
                warnings.append(f"page {page_no}: column header not found; page skipped" + (f" although {row_like} lines look like BOM rows" if row_like else ""))
                unreadable.add(page_no)
            else:
                warnings.append(f"page {page_no}: no BOM table on this page (no column header); ignored")
            continue
        header_idx, bands = found
        bands = _align_body_columns(bands, lines[header_idx + 1:], allow_missing_level=page_method == "ocr")
        if not header.get("parent_item"):
            _parse_header(lines[:header_idx], header, page_no, page_method)
        as_of = _parse_date(header.get("as_of_date"))
        annots = extract_annotations(page)
        for line in lines[header_idx + 1 :]:
            cols = assign_columns(line, bands)
            item_number = _text(cols, "component_item")
            level = _text(cols, "level")
            missing_level = not level and page_method == "ocr" and bool(_OCR_ITEM_RE.fullmatch(item_number)) and bool(_text(cols, "component_description")) and parse_decimal(_text(cols, "quantity_per")) is not None
            if not item_number or not _ITEM_RE.match(item_number) or not (level.isdigit() or missing_level):
                if line and len(line) > 3 and (line[0].text.isdigit() or (page_method == "ocr" and _OCR_ITEM_RE.fullmatch(line[0].text))):
                    warnings.append(f"page {page_no}: possible BOM row could not be parsed: {line_text(line)[:100]}")
                    unparsed_rows.append({"page": page_no, "text": line_text(line)[:200], "bbox": line_bbox(line).model_dump()})
                continue
            row_counter += 1
            description = _text(cols, "component_description")
            qty_text = _text(cols, "quantity_per")
            quantity: Decimal | None
            confidence = min(w.confidence for w in line)
            if missing_level:
                confidence = min(confidence, 0.6)
                warnings.append(f"page {page_no} row {row_counter}: hierarchy level not read by OCR for {item_number}; verify the source row")
            quantity = parse_decimal(qty_text)
            if quantity is None:
                confidence = min(confidence, 0.5)
                warnings.append(f"page {page_no} row {row_counter}: quantity '{qty_text}' is not numeric")
            if not description:
                confidence = min(confidence, 0.4)
                warnings.append(f"page {page_no} row {row_counter}: empty description for {item_number}")
            eff_from, eff_thru = _text(cols, "effective_from"), _text(cols, "effective_thru")
            d_from, d_thru = _parse_date(eff_from), _parse_date(eff_thru)
            is_active = True
            if as_of and d_thru and d_thru < as_of:
                is_active = False
            if as_of and d_from and d_from > as_of:
                is_active = False
            category, reason = categorize(item_number, description, quantity)
            bbox = line_bbox(line)
            redlines = [
                {"field": _field_for_x(bands, a.cx), "text": a.content}
                for a in annots
                if a.content and a.y1 >= bbox.y0 - 4 and a.y0 <= bbox.y1 + 10
            ]
            items.append(
                DocumentItem(
                    id=f"{doc_id}:r{row_counter}",
                    doc_id=doc_id,
                    doc_type=DocType.BOM,
                    sku=header.get("parent_item"),
                    item_number=item_number,
                    description=description,
                    quantity=quantity,
                    uom=_text(cols, "um") or None,
                    oper_seq=_text(cols, "oper_seq") or None,
                    attributes={
                        "level": level,
                        "branch_plant": _text(cols, "branch_plant"),
                        "ext_qty": _text(cols, "ext_qty"),
                        "t": _text(cols, "t"),
                        "effective_from": eff_from,
                        "effective_thru": eff_thru,
                        "flags": _text(cols, "flags"),
                        "redlines": redlines,
                    },
                    category=category,
                    category_reason=reason,
                    is_active=is_active,
                    extraction_confidence=confidence,
                    evidence=Evidence(
                        file=str(path),
                        file_sha256=sha,
                        page=page_no,
                        bbox=bbox,
                        raw_text=line_text(line),
                        line_index=row_counter - 1,
                        locator=f"page {page_no}, row {row_counter}",
                        extraction_method=page_method,
                    ),
                )
            )
    pdf.close()
    if not header.get("parent_item"):
        warnings.append("parent item not found in header")
    header["extraction_method"] = "mixed" if len({i.evidence.extraction_method for i in items}) > 1 else items[0].evidence.extraction_method if items else "none"
    header["unreadable_pages"] = sorted(unreadable)
    header["unparsed_rows"] = unparsed_rows
    return Document(
        id=doc_id,
        doc_type=DocType.BOM,
        path=str(path),
        sha256=sha,
        sku=header.get("parent_item"),
        header=header,
        items=items,
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        warnings=warnings,
    )


def _parse_header(lines: list[list[Word]], header: dict, page_no: int = 1, method: str = "pdf_text") -> None:
    for line in lines:
        text = line_text(line)
        for key, rx in _HEADER_PATTERNS.items():
            if key in header:
                continue
            m = re.search(rx.pattern, text, re.IGNORECASE)
            if m:
                header[key] = m.group(1).strip()
                if key == "parent_item":
                    header["identity_evidence"] = {"page": page_no, "bbox": line_bbox(line).model_dump(), "raw_text": text, "extraction_method": method}
                    header["identity_confidence"] = min(w.confidence for w in line)


def _field_for_x(bands: list[ColumnBand], x: float) -> str:
    return min(bands, key=lambda b: b.distance(x)).name
