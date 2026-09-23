"""Layout-aware PDF text primitives built on PyMuPDF: words with boxes, visual lines, column bands, annotations."""

from dataclasses import dataclass

import pymupdf

from kaizen.models import BBox


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    block: int
    line: int
    word_no: int
    confidence: float = 1.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class ColumnBand:
    name: str
    x0: float
    x1: float

    def contains(self, x: float) -> bool:
        return self.x0 <= x < self.x1

    def distance(self, x: float) -> float:
        if self.contains(x):
            return 0.0
        return min(abs(x - self.x0), abs(x - self.x1))


@dataclass(frozen=True)
class Annotation:
    type: str
    content: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


def extract_words(page: pymupdf.Page, exclude_annotation_text: bool = True) -> list[Word]:
    """Words with boxes. Annotation appearance text (redlines, comments) is excluded from page words by default
    so it never pollutes row extraction; use extract_annotations() to read it deliberately."""
    words = [Word(text=w[4], x0=w[0], y0=w[1], x1=w[2], y1=w[3], block=w[5], line=w[6], word_no=w[7]) for w in page.get_text("words")]
    if exclude_annotation_text:
        rects = [a.rect for a in page.annots()]
        words = [w for w in words if not any(r.x0 <= w.cx <= r.x1 and r.y0 <= w.cy <= r.y1 for r in rects)]
    return sorted(words, key=lambda w: (round(w.y0, 1), w.x0))


def group_lines(words: list[Word], y_tol: float = 3.0) -> list[list[Word]]:
    """Group words into visual lines by vertical centre; each line sorted left-to-right."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.cy, w.x0)):
        if lines and abs(w.cy - lines[-1][0].cy) <= y_tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def line_text(line: list[Word]) -> str:
    return " ".join(w.text for w in sorted(line, key=lambda w: w.x0))


def line_bbox(line: list[Word]) -> BBox:
    return BBox(x0=min(w.x0 for w in line), y0=min(w.y0 for w in line), x1=max(w.x1 for w in line), y1=max(w.y1 for w in line))


def assign_columns(line: list[Word], bands: list[ColumnBand]) -> dict[str, list[Word]]:
    cols: dict[str, list[Word]] = {b.name: [] for b in bands}
    for w in sorted(line, key=lambda w: w.x0):
        band = min(bands, key=lambda b: b.distance(w.cx))
        cols[band.name].append(w)
    return cols


def extract_annotations(page: pymupdf.Page) -> list[Annotation]:
    out: list[Annotation] = []
    for a in page.annots():
        r = a.rect
        out.append(
            Annotation(
                type=a.type[1] if isinstance(a.type, tuple) else str(a.type),
                content=(a.info.get("content") or "").strip(),
                x0=r.x0,
                y0=r.y0,
                x1=r.x1,
                y1=r.y1,
                page=page.number + 1,
            )
        )
    return out


def split_line_by_gaps(line: list[Word], gap: float) -> list[list[Word]]:
    """Split a visual line into fragments wherever two consecutive words are further apart than `gap`.
    Drawings and forms place unrelated text at the same height in different columns."""
    words = sorted(line, key=lambda w: w.x0)
    fragments: list[list[Word]] = []
    for w in words:
        if fragments and w.x0 - fragments[-1][-1].x1 <= gap:
            fragments[-1].append(w)
        else:
            fragments.append([w])
    return fragments
