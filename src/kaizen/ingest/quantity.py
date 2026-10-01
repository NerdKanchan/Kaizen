"""Parsing of label kit-content lines such as '2 Each - Tape Strips (3 per)'."""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from kaizen.models import SubQuantity

_UOM_CANONICAL = {
    "EACH": "EACH", "EA": "EACH", "PC": "EACH", "PCS": "EACH",
    "PAIR": "PAIR", "PAIRS": "PAIR",
    "PACK": "PACK", "PACKS": "PACK", "PKG": "PACK",
    "ROLL": "ROLL", "ROLLS": "ROLL",
    "SET": "SET", "SETS": "SET",
}
_LINE_RE = re.compile(
    r"^\s*(?P<qty>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<uom>" + "|".join(_UOM_CANONICAL) + r")?\s*[-–—:]\s*(?P<desc>.+?)\s*$",
    re.IGNORECASE,
)


def parse_decimal(text: str | None) -> Decimal | None:
    """Decimal from ERP/label text; tolerates thousands separators and stray spaces ('1,000.0000')."""
    if text is None:
        return None
    cleaned = str(text).replace(",", "").replace(" ", "").strip()
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
        return value if value.is_finite() else None
    except InvalidOperation:
        return None
_SUB_KINDS = {"PER": "per", "PAIR": "pair", "PAIRS": "pair", "PACK": "pack", "PK": "pack", "EACH": "each", "EA": "each"}
_SUB_PAREN_RE = re.compile(r"\(\s*(?P<n>\d+)\s*(?P<kind>per|pairs?|pack|pk|each|ea)(?:\s+[a-z]+)?\s*\)", re.IGNORECASE)
_SUB_TRAIL_RE = re.compile(r",?\s*(?P<n>\d+)\s*(?P<kind>per)\s+[a-z]+\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedLabelLine:
    matched: bool
    quantity: Decimal | None
    uom: str | None
    description: str
    sub_quantity: SubQuantity | None


def _extract_sub_quantity(desc: str) -> tuple[str, SubQuantity | None]:
    for rx in (_SUB_PAREN_RE, _SUB_TRAIL_RE):
        m = rx.search(desc)
        if m:
            if int(m.group('n')) < 1:
                return desc, None
            sub = SubQuantity(value=int(m.group("n")), kind=_SUB_KINDS[m.group("kind").upper()], raw=m.group(0).strip())
            cleaned = (desc[: m.start()] + desc[m.end():]).strip().rstrip(",").strip()
            return cleaned, sub
    return desc, None


def parse_label_line(text: str) -> ParsedLabelLine:
    m = _LINE_RE.match(text)
    if not m:
        return ParsedLabelLine(False, None, None, text.strip(), None)
    uom_raw = m.group("uom")
    uom = _UOM_CANONICAL[uom_raw.upper()] if uom_raw else "EACH"
    desc, sub = _extract_sub_quantity(m.group("desc"))
    return ParsedLabelLine(True, parse_decimal(m.group("qty")), uom, desc, sub)
