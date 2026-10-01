"""Independent PDF/export parity checks. These measure extraction, not matching accuracy."""

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation

from kaizen.models import Document


def _number(value):
    if value in (None, ""):
        return None
    try:
        return str(Decimal(str(value)).normalize())
    except InvalidOperation:
        return str(value)


def _date(value):
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value or "", fmt).date().isoformat()
        except ValueError:
            pass
    return value or ""


def _rows(doc: Document) -> Counter:
    return Counter((i.item_number, i.description, _number(i.quantity), i.uom, _number(i.oper_seq), _date(i.attributes.get("effective_from")), _date(i.attributes.get("effective_thru"))) for i in doc.items)


def compare_bom_sources(pdf: Document, export: Document) -> dict:
    """Compare multisets, so duplicate components and their sequence/quantity survive.

    The spreadsheet is independently parsed; equality does not establish that either
    source is the approved specification or that its components match a label.
    """
    left, right = _rows(pdf), _rows(export)
    missing, extra = right - left, left - right
    return {"sku": pdf.sku, "pdf": pdf.path, "export": export.path, "pdf_rows": len(pdf.items), "export_rows": len(export.items), "equal": left == right,
            "fields": ["item_number", "description", "quantity", "uom", "oper_seq", "effective_from", "effective_thru"],
            "missing_from_pdf": [{"row": list(k), "occurrences": v} for k, v in missing.items()], "extra_in_pdf": [{"row": list(k), "occurrences": v} for k, v in extra.items()]}
