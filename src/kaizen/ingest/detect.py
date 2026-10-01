"""Document-type detection (content first, filename as fallback) and parser dispatch."""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl
import pymupdf

from kaizen.ingest.bom_pdf import parse_bom_pdf
from kaizen.ingest.bom_table import parse_bom_table
from kaizen.ingest.drawing_pdf import parse_drawing_pdf
from kaizen.ingest.label_pdf import parse_label_pdf
from kaizen.ingest.pco import parse_pco
from kaizen.ingest.workbook import workbook_access_problem
from kaizen.models import DocType, Document

_FILENAME_TOKENS = {
    DocType.BOM: {"bom", "bill"},
    DocType.LABEL: {"label", "labels", "lbl"},
    DocType.DRAWING: {"dwg", "drawing", "drw", "pkg"},
    DocType.PCO: {"pco"},
}


@dataclass(frozen=True)
class ParseOutcome:
    path: str
    doc_type: DocType | None
    document: Document | None
    reason: str = ""


def _by_filename(path: Path) -> DocType | None:
    # Released BD files use identifiers without a separator (for example DWG1234567, LAB1234567).
    # Content detection still takes precedence over these anchored fallbacks.
    stem = path.stem.upper()
    if re.match(r"^DWG\d{5,}(?:\b|_)", stem):
        return DocType.DRAWING
    if re.match(r"^LAB\d{5,}(?:\b|_)", stem):
        return DocType.LABEL
    tokens = set(re.split(r"[^a-z0-9]+", path.stem.lower()))
    for doc_type, keys in _FILENAME_TOKENS.items():
        if tokens & keys:
            return doc_type
    return None


def _by_content(path: Path) -> DocType | None:
    ext = path.suffix.lower()
    text = ""
    if ext in (".xlsx", ".xlsm", ".csv"):
        try:
            if ext == ".csv":
                with open(path, newline="", encoding="utf-8-sig") as fh:
                    text = " ".join(" ".join(r) for _, r in zip(range(40), csv.reader(fh)))
            else:
                wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
                for ws in wb.worksheets:
                    for i, row in enumerate(ws.iter_rows(values_only=True)):
                        if i > 40:
                            break
                        text += " " + " ".join(str(c) for c in row if c is not None)
                wb.close()
        except Exception:  # unreadable spreadsheet → filename fallback
            return None
        low = text.lower()
        if "affected codes" in low or "fm00835" in low:
            return DocType.PCO
        if "component item" in low or "item number" in low:
            return DocType.BOM
        return None
    if ext == ".pdf":
        try:
            pdf = pymupdf.open(path)
            text = " ".join(pdf[i].get_text() for i in range(min(2, len(pdf))))
            pdf.close()
        except Exception:
            return None
        low = text.lower()
        if "bill of material print" in low or ("component item" in low and "component description" in low):
            return DocType.BOM
        if "affected codes" in low or "fm00835" in low:
            return DocType.PCO
        if "drawing no" in low or "do not scale" in low or "third angle projection" in low:
            return DocType.DRAWING
        if "contents" in low and "ref" in low:
            return DocType.LABEL
    return None


def detect_doc_type(path: Path | str) -> DocType | None:
    path = Path(path)
    if path.suffix.lower() not in (".pdf", ".xlsx", ".xlsm", ".csv"):
        return None
    return _by_content(path) or _by_filename(path)


def parse_document(path: Path | str) -> ParseOutcome:
    path = Path(path)
    if reason := workbook_access_problem(path):
        return ParseOutcome(str(path), None, None, reason)
    doc_type = detect_doc_type(path)
    ext = path.suffix.lower()
    if doc_type is DocType.BOM:
        doc = parse_bom_pdf(path) if ext == ".pdf" else parse_bom_table(path)
        return ParseOutcome(str(path), doc_type, doc)
    if doc_type is DocType.LABEL:
        if ext != ".pdf":
            return ParseOutcome(str(path), doc_type, None, "label parser supports PDF only; tabular labels are NOT IMPLEMENTED")
        return ParseOutcome(str(path), doc_type, parse_label_pdf(path))
    if doc_type is DocType.DRAWING:
        if ext != ".pdf":
            return ParseOutcome(str(path), doc_type, None, "drawing parser supports PDF only")
        return ParseOutcome(str(path), doc_type, parse_drawing_pdf(path))
    if doc_type is DocType.PCO:
        return ParseOutcome(str(path), doc_type, parse_pco(path))
    return ParseOutcome(str(path), None, None, "unrecognised document type")
