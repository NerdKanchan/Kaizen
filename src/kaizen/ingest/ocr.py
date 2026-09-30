"""OCR fallback for image-only pages. Priority is native PDF text → layout extraction → OCR → (optional) AI vision.
OCR runs only when a page has no extractable text and only if an engine is installed (`pip install
rapidocr-onnxruntime`, fully offline). Results carry per-word confidence and are marked extraction_method='ocr'.

Product-name OCR corrections are loaded from ``ocr_corrections.json`` (same directory) so they can be
edited without touching source code.  Structural spacing rules (digit/CM/X spacing) are kept in code."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from kaizen.ingest.pdf_words import Word

# ---------------------------------------------------------------------------
# Product-name corrections — loaded from the adjacent JSON file so that new
# brand-name OCR glitches can be added without changing Python source.
# ---------------------------------------------------------------------------
_CORRECTIONS_FILE = Path(__file__).with_name("ocr_corrections.json")


def _load_product_corrections(path: Path = _CORRECTIONS_FILE) -> tuple[tuple[re.Pattern, str], ...]:
    """Read [pattern, replacement] pairs from *path* and compile them."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple((re.compile(entry[0], re.IGNORECASE), entry[1]) for entry in data["corrections"])


_PRODUCT_CORRECTIONS: tuple[tuple[re.Pattern, str], ...] = _load_product_corrections()

# ---------------------------------------------------------------------------
# Structural spacing rules — regex mechanics, not brand-name lists.
# These fix systematic OCR joining artefacts (digit–unit, dimension notation).
# ---------------------------------------------------------------------------
_STRUCTURAL_CORRECTIONS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"(\d%?)(?=Isopropyl)", re.IGNORECASE), r"\1 "),
    (re.compile(r"(?<=Isopropyl)(?=Alcohol)", re.IGNORECASE), " "),
    (re.compile(r"(?<=\d)(?=Isopropyl)", re.IGNORECASE), " "),
    (re.compile(r"(?<=pouch)(?=\d|Each)", re.IGNORECASE), " "),
    (re.compile(r"(\d+(?:\.\d+)?)(CM)(?=X|\d)", re.IGNORECASE), r"\1\2 "),
    (re.compile(r"(?<=\d)(?=CM\b)", re.IGNORECASE), " "),
    (re.compile(r"(?<=X)(?=\d)", re.IGNORECASE), " "),
)


def correct_ocr_text(text: str) -> str:
    for pattern, replacement in _PRODUCT_CORRECTIONS:
        text = pattern.sub(replacement, text)
    for pattern, replacement in _STRUCTURAL_CORRECTIONS:
        text = pattern.sub(replacement, text)
    return text


@dataclass
class OcrResult:
    words: list[tuple[float, float, float, float, str, float]] = field(default_factory=list)  # x0,y0,x1,y1 (PDF points), text, confidence
    engine: str = ""
    dpi: int = 200


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except Exception:
        return False


def ocr_page(page: pymupdf.Page, dpi: int = 200) -> OcrResult:
    """Run RapidOCR on a rendered page; coordinates are converted back to PDF points."""
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    pix = page.get_pixmap(dpi=dpi)
    result, _ = engine(pix.tobytes("png"))
    scale = 72.0 / dpi
    words: list[tuple[float, float, float, float, str, float]] = []
    for box, text, conf in result or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, y0, x1, y1 = min(xs) * scale, min(ys) * scale, max(xs) * scale, max(ys) * scale
        # OCR returns line-level boxes; split into words proportionally so downstream column logic still works
        tokens = str(text).split()
        if not tokens:
            continue
        total = sum(len(t) for t in tokens) + max(len(tokens) - 1, 0)
        cursor = x0
        for t in tokens:
            w = (x1 - x0) * (len(t) + 1) / total if total else (x1 - x0)
            words.append((cursor, y0, min(cursor + w, x1), y1, t, float(conf)))
            cursor += w
    return OcrResult(words=words, engine="rapidocr-onnxruntime", dpi=dpi)


def ocr_words(result: OcrResult) -> list[Word]:
    return [Word(text=t, x0=x0, y0=y0, x1=x1, y1=y1, block=0, line=i, word_no=0, confidence=c) for i, (x0, y0, x1, y1, t, c) in enumerate(result.words)]


def ocr_min_confidence(result: OcrResult) -> float:
    return min((c for *_, c in result.words), default=1.0)
