from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
from pathlib import Path


OUT = Path("output/pdf/kaizen-showcase-summary.pdf")
PAGE_W, PAGE_H = landscape(A4)

INK = HexColor("#102A43")
MUTED = HexColor("#52606D")
TEAL = HexColor("#007C83")
GREEN = HexColor("#16803C")
AMBER = HexColor("#C87400")
RED = HexColor("#C23B3B")
PALE = HexColor("#EEF7F7")
SLATE = HexColor("#F4F7FA")
LINE = HexColor("#D8E1E8")
WHITE = colors.white


def ptext(c, text, x, y_top, width, style):
    p = Paragraph(text, style)
    _, h = p.wrap(width, 1000)
    p.drawOn(c, x, y_top - h)
    return h


def round_rect(c, x, y, w, h, fill, stroke=None, radius=4 * mm):
    c.setFillColor(fill)
    c.setStrokeColor(stroke or fill)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1 if stroke else 0)


def pill(c, label, x, y, fill, text_color=WHITE):
    c.setFont("Helvetica-Bold", 7.1)
    w = stringWidth(label, "Helvetica-Bold", 7.1) + 12
    round_rect(c, x, y, w, 14, fill, radius=7)
    c.setFillColor(text_color)
    c.drawCentredString(x + w / 2, y + 4, label)
    return w


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=landscape(A4))
    c.setTitle("Project Kaizen - Showcase Summary")
    c.setAuthor("Project Kaizen")

    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=25,
                           leading=28, textColor=INK)
    subtitle = ParagraphStyle("subtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=10.1,
                              leading=13.2, textColor=MUTED)
    section = ParagraphStyle("section", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9.2,
                             leading=11, textColor=INK)
    body = ParagraphStyle("body", parent=styles["Normal"], fontName="Helvetica", fontSize=8.35,
                          leading=11.2, textColor=INK)
    small = ParagraphStyle("small", parent=body, fontSize=7.45, leading=9.3, textColor=MUTED)
    callout = ParagraphStyle("callout", parent=body, fontName="Helvetica-Bold", fontSize=9.2,
                             leading=12.1, textColor=INK)

    # Background and top rail
    c.setFillColor(WHITE); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(TEAL); c.rect(0, PAGE_H - 9, PAGE_W, 9, fill=1, stroke=0)
    c.setFillColor(TEAL); c.circle(20 * mm, PAGE_H - 27 * mm, 9 * mm, fill=1, stroke=0)
    c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 15); c.drawCentredString(20 * mm, PAGE_H - 32 * mm, "K")

    ptext(c, "PROJECT KAIZEN", 34 * mm, PAGE_H - 18 * mm, 120 * mm, title)
    ptext(c, "Cross-check automation for medical-kit documentation", 34 * mm, PAGE_H - 29 * mm, 170 * mm, subtitle)
    pill(c, "INNOVATION WEEK 2026", PAGE_W - 69 * mm, PAGE_H - 26 * mm, INK)

    # Hero statement
    hero_y = PAGE_H - 43 * mm
    round_rect(c, 12 * mm, hero_y - 28 * mm, PAGE_W - 24 * mm, 24 * mm, PALE, radius=5 * mm)
    ptext(c, "Kaizen turns a slow, side-by-side document review into an explainable work queue: it clears what is proven, flags what is risky, and preserves the reviewer as the final decision-maker.",
          18 * mm, hero_y - 8 * mm, PAGE_W - 36 * mm, callout)

    # Three problem cards
    col_gap = 5 * mm; card_w = (PAGE_W - 24 * mm - 2 * col_gap) / 3; card_y = 104 * mm; card_h = 42 * mm
    cards = [
        ("THE PAIN", "Manual review", "Two reviewers compare BOMs, labels, drawings and PCOs line by line - roughly 60 minutes per SKU, per reviewer."),
        ("THE COMPLICATION", "Different words, same part", "A BOM, label and drawing may describe the same component differently, so a basic text match is unsafe."),
        ("THE COST OF DELAY", "Quality work waits", "For a 129-SKU project, review can consume about 258 reviewer hours while independent review capacity is limited."),
    ]
    for i, (eyebrow, head, copy) in enumerate(cards):
        x = 12 * mm + i * (card_w + col_gap)
        round_rect(c, x, card_y, card_w, card_h, SLATE, stroke=LINE, radius=4 * mm)
        c.setFillColor(TEAL); c.setFont("Helvetica-Bold", 6.8); c.drawString(x + 6 * mm, card_y + card_h - 8 * mm, eyebrow)
        ptext(c, head, x + 6 * mm, card_y + card_h - 11 * mm, card_w - 12 * mm, section)
        ptext(c, copy, x + 6 * mm, card_y + card_h - 18 * mm, card_w - 12 * mm, body)

    # Left: what it does
    left_x, left_w = 12 * mm, 104 * mm
    base_y = 18 * mm
    ptext(c, "What Kaizen does", left_x, 97 * mm, left_w, section)
    ptext(c, "Reads the files reviewers already download - JDE BOMs, product labels, packaging drawings and PCOs - from PDF, Excel and CSV. No change to JDE, MasterControl or the approval workflow.",
          left_x, 92 * mm, left_w, body)
    ptext(c, "Its comparison engine checks:", left_x, 75 * mm, left_w, section)
    checks = ["BOM ↔ Label", "BOM ↔ Drawing", "Label ↔ Drawing", "PCO ↔ BOM", "Old ↔ New label", "PCO coverage"]
    x = left_x
    for i, label in enumerate(checks):
        if i == 3: x = left_x
        row = 0 if i < 3 else 1
        x = left_x + (i % 3) * 35 * mm
        pill(c, label, x, 64 * mm - row * 10 * mm, TEAL)

    # Centre flow
    flow_x, flow_w = 123 * mm, 91 * mm
    ptext(c, "From files to a defensible decision", flow_x, 97 * mm, flow_w, section)
    steps = [("1", "Extract", "items, quantities and page-level evidence"), ("2", "Match", "exact, approved terminology, or potential"),
             ("3", "Review", "two independent reviewers; blind mode supported"), ("4", "Act", "Excel, annotated BOM, actions and rerun closure")]
    sx = flow_x
    for i, (n, h, d) in enumerate(steps):
        y = 80 * mm - i * 16 * mm
        c.setFillColor(TEAL); c.circle(sx + 4 * mm, y + 3 * mm, 4 * mm, fill=1, stroke=0)
        c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 7); c.drawCentredString(sx + 4 * mm, y + .6 * mm, n)
        ptext(c, "<b>%s</b> - %s" % (h, d), sx + 11 * mm, y + 7 * mm, flow_w - 11 * mm, small)
        if i < 3:
            c.setStrokeColor(LINE); c.setLineWidth(1); c.line(sx + 4 * mm, y - 5 * mm, sx + 4 * mm, y - 9 * mm)

    # Right impact
    right_x, right_w = 221 * mm, PAGE_W - 233 * mm
    round_rect(c, right_x, 27 * mm, right_w, 70 * mm, INK, radius=5 * mm)
    ptext(c, "Showcase impact", right_x + 6 * mm, 91 * mm, right_w - 12 * mm,
          ParagraphStyle("white_sec", parent=section, textColor=WHITE))
    metrics = [("~1,100", "comparisons across five checks in the demo"), ("27% → 73%", "projected review-effort reduction as approved terminology is reused"), ("100%", "precision and recall on the seeded golden test set")]
    yy = 82 * mm
    for n, d in metrics:
        ptext(c, n, right_x + 6 * mm, yy, right_w - 12 * mm,
              ParagraphStyle("metric", parent=title, fontSize=16, leading=17, textColor=HexColor("#68D5D0")))
        ptext(c, d, right_x + 6 * mm, yy - 7 * mm, right_w - 12 * mm,
              ParagraphStyle("metric_copy", parent=small, textColor=WHITE))
        yy -= 18 * mm

    # footer safeguards
    c.setStrokeColor(LINE); c.setLineWidth(.7); c.line(12 * mm, 14 * mm, PAGE_W - 12 * mm, 14 * mm)
    ptext(c, "Designed for trust: deterministic and offline by default; every finding includes source file, hash, page and bounding box. AI is optional, labelled, and can only suggest - never approve or change a classification.",
          12 * mm, 11 * mm, PAGE_W - 24 * mm, small)
    c.showPage(); c.save()


if __name__ == "__main__":
    main()
