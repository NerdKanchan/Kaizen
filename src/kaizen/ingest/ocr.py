"""OCR fallback for image-only pages. Priority is native PDF text → layout extraction → OCR → (optional) AI vision.
OCR runs only when a page has no extractable text and only if an engine is installed (`pip install
rapidocr-onnxruntime`, fully offline). Results carry per-word confidence and are marked extraction_method='ocr'."""

from dataclasses import dataclass, field

import pymupdf

from kaizen.ingest.pdf_words import Word


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
