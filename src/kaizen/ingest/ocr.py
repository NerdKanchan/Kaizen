"""Offline OCR for scanned BOMs, labels, and drawings, including damaged label text layers.
Native PDF text is preferred. Tesseract or the optional RapidOCR engine renders pages locally;
results carry confidence and displayed-page bounding boxes, marked extraction_method='ocr'.

Product-name OCR corrections are loaded from ``ocr_corrections.json`` (same directory) so they can be
edited without touching source code.  Structural spacing rules (digit/CM/X spacing) are kept in code."""

import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
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
    (re.compile(r"(\d+)per(?=pouch\b)", re.IGNORECASE), r"\1 per "),
    (re.compile(r"(\d%?)(?=Isopropyl)", re.IGNORECASE), r"\1 "),
    (re.compile(r"(?<=Isopropyl)(?=Alcohol)", re.IGNORECASE), " "),
    (re.compile(r"(?<=\d)(?=Isopropyl)", re.IGNORECASE), " "),
    (re.compile(r"(?<=pouch)(?=\d|Each)", re.IGNORECASE), " "),
    (re.compile(r"(\d+(?:\.\d+)?)(CM)(?=X|\d)", re.IGNORECASE), r"\1\2 "),
    (re.compile(r"(?<=\d)(?=CM\b)", re.IGNORECASE), " "),
    (re.compile(r"(?<=X)(?=\d)", re.IGNORECASE), " "),
)

_LABEL_WORDS = frozenset(
    """
    ABSORBENT ADHESIVE ALCOHOL AMPULE APPLICATOR ASSEMBLY ASPIRATION BAND BARRIER BENDABLE BLUE
    BOUFFANT CAP CATHETER CHLORAPREP CONTROL DEVICE DILATOR DRAPE DRESSING DUAL EACH ECG ELECTRODE
    ELECTRODES END FENESTRATED FLEXURA FUNNEL GAUZE GLOVE GLOVES GUIDE GUIDEWIRE HOLDER HYPODERMIC
    ID INTRODUCER ISOPROPYL IV LEAD LEADS LENGTH LID LUMEN MASK MEASURE MEASURING MICROINTRODUCER
    NEEDLE NITINOL OD PERIPHERAL PICC PROTECTIVE SAFETY SALINE SCALPEL SHERLOCK SOLUTION STRAIGHT
    STYLET SURGICAL SYRINGE TAPE TIP TOURNIQUET TRIMMING VESSEL WITH
    """.split()
)
_FUSED_LABEL_TOKEN_RE = re.compile(r"\b[A-Za-z]{8,}\b")


def _split_fused_label_token(token: str) -> str:
    upper = token.upper()
    if upper in _LABEL_WORDS:
        return token

    @lru_cache(maxsize=None)
    def segment(start: int) -> tuple[tuple[str, ...], ...]:
        if start == len(token):
            return ((),)
        paths = []
        for end in range(start + 2, len(token) + 1):
            if upper[start:end] not in _LABEL_WORDS:
                continue
            for suffix in segment(end):
                paths.append((token[start:end], *suffix))
                if len(paths) > 1:
                    return tuple(paths[:2])
        return tuple(paths)

    candidates = segment(0)
    if len(candidates) == 1 and len(candidates[0]) > 1:
        return " ".join(candidates[0])
    return token


def correct_fused_label_words(text: str) -> str:
    """Split only uniquely segmented OCR tokens made entirely of known label terms."""
    return _FUSED_LABEL_TOKEN_RE.sub(lambda match: _split_fused_label_token(match.group()), text)


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


_LOCK = threading.RLock()
_CACHE: OrderedDict[str, OcrResult] = OrderedDict()


def available_engines() -> list[str]:
    """No external calls; report engines that can run on this host."""
    engines = []
    if shutil.which("tesseract"):
        engines.append("tesseract")
    try:
        import rapidocr_onnxruntime  # noqa: F401

        engines.append("rapidocr-onnxruntime")
    except Exception:
        pass
    return engines


def ocr_available() -> bool:
    return bool(available_engines())


@lru_cache(maxsize=2)
def _rapid_engine(single_line: bool = False):
    from rapidocr_onnxruntime import RapidOCR

    # The default detector downsizes engineering sheets to 736px, losing small callouts.
    # Passing model_path also supports RapidOCR 1.2's parameter updater.
    return RapidOCR(det_model_path=None, det_limit_side_len=2400, det_limit_type="max", use_text_det=not single_line, text_score=0.0 if single_line else 0.5)


def ocr_page(page: pymupdf.Page, dpi: int = 240, *, clip: pymupdf.Rect | None = None, single_line: bool = False) -> OcrResult:
    """Offline OCR with word confidence and rendered-page coordinates in PDF points.

    Tesseract (already present in the hosted image) is preferred; RapidOCR is the portable
    alternative. A bounded content cache reuses a shared drawing without retaining rasters.
    Engine failures propagate to parsers, which report an unreadable page explicitly.
    """
    engines = available_engines()
    if not engines:
        raise RuntimeError("no offline OCR engine; install Tesseract or kaizen-crosscheck[ocr]")
    rect = clip or page.rect
    pix = page.get_pixmap(dpi=dpi, clip=rect, colorspace=pymupdf.csRGB, alpha=False)
    png = pix.tobytes("png")
    key = hashlib.sha256(png + str((dpi, tuple(rect), page.rotation, engines[0], single_line)).encode()).hexdigest()
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return OcrResult(words=list(_CACHE[key].words), engine=_CACHE[key].engine, dpi=dpi)
        result = _recognize(png, engines[0], single_line)
        words = []
        for x0, y0, x1, y1, t, conf in result:
            # Pixmap origin includes clip offsets. Keep the displayed orientation for
            # layout parsing and evidence overlays, including BD's 270-degree scans.
            box = pymupdf.Rect((x0 + pix.x) * 72 / dpi, (y0 + pix.y) * 72 / dpi, (x1 + pix.x) * 72 / dpi, (y1 + pix.y) * 72 / dpi)
            words.append((box.x0, box.y0, box.x1, box.y1, t, conf))
        out = OcrResult(words=words, engine=engines[0], dpi=dpi)
        _CACHE[key] = out
        if len(_CACHE) > 32:
            _CACHE.popitem(last=False)
        return OcrResult(words=list(out.words), engine=out.engine, dpi=dpi)


def _recognize(png: bytes, engine: str, single_line: bool) -> list[tuple]:
    if engine == "tesseract":
        proc = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "7" if single_line else "11", "tsv"],
            input=png, capture_output=True, timeout=120, check=True,
        )
        out = []
        # TSV is not CSV: an inch mark or quote in a word must not start a quoted field.
        for row in csv.DictReader(io.StringIO(proc.stdout.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE):
            if row.get("level") != "5" or not (row.get("text") or "").strip():
                continue
            x, y, w, h = (float(row[k]) for k in ("left", "top", "width", "height"))
            out.append((x, y, x + w, y + h, row["text"], max(0, min(1, float(row["conf"]) / 100))))
        return out
    result, _ = _rapid_engine(single_line)(png)
    words: list[tuple[float, float, float, float, str, float]] = []
    for box, text, conf in result or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        # OCR returns line-level boxes; split into words proportionally so downstream column logic still works
        tokens = str(text).split()
        if not tokens:
            continue
        total = sum(len(t) for t in tokens) + max(len(tokens) - 1, 0)
        cursor = 0
        for t in tokens:
            left = x0 + (x1 - x0) * cursor / total
            right = x0 + (x1 - x0) * (cursor + len(t)) / total
            words.append((left, y0, right, y1, t, float(conf)))
            cursor += len(t) + 1
    return words


def ocr_words(result: OcrResult) -> list[Word]:
    return [Word(text=t, x0=x0, y0=y0, x1=x1, y1=y1, block=0, line=i, word_no=0, confidence=c) for i, (x0, y0, x1, y1, t, c) in enumerate(result.words)]


def ocr_min_confidence(result: OcrResult) -> float:
    return min((c for *_, c in result.words), default=1.0)
