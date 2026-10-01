"""Follow-ups from reviewing the real-data work. Incomplete extraction must stay visible without
throwing away what was read, and heuristics tuned on one scan must not fire on ordinary text."""

from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from kaizen.checks.bom_drawing import callouts, run_bom_drawing_check
from kaizen.checks.bom_label import run_bom_label_check
from kaizen.datasets.pdf_bom import BomRowSpec, BomSpec, render_bom_pdf
from kaizen.datasets.pdf_label import LabelSpec, render_label_pdf
from kaizen.ingest import ocr
from kaizen.ingest.bom_pdf import parse_bom_pdf
from kaizen.ingest.detect import parse_document
from kaizen.ingest.drawing_pdf import parse_drawing_pdf
from kaizen.ingest.label_pdf import _find_ref, parse_label_pdf
from kaizen.ingest.ocr import OcrResult
from kaizen.ingest.pdf_words import Word
from kaizen.matching.ladder import MatchLadder
from kaizen.matching.normalize import normalize
from kaizen.models import MatchLevel, Severity, Thresholds
from kaizen.terminology.store import RelationshipStore
from tests.unit.test_bom_label_check import bom_doc, label_doc
from tests.unit.test_pairing_engine import drawing_doc

TH = Thresholds()
GOLDEN = Path(__file__).resolve().parents[2] / "datasets" / "golden" / "sku-001"


def ladder():
    return MatchLadder(RelationshipStore.default(), TH)


def blockers(rows):
    return [r for r in rows if any(d.severity is Severity.BLOCKER for d in r.discrepancies)]


def compared(rows):
    return [r for r in rows if r.role == "item"]


def add_image(page, rect):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
    pix.clear_with(200)
    page.insert_image(rect, pixmap=pix)


def native_label_without_ref(path):
    """Native contents, a logo image, and a REF printed as artwork (so not in the text layer)."""
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=420, height=300)
        add_image(page, pymupdf.Rect(360, 10, 400, 50))
        for y, text in [(30, "PowerPICC Kit"), (60, "Contents:"), (80, "1 Each - Mask"), (95, "2 Each - Gown")]:
            page.insert_text((20, y), text, fontsize=8)
        pdf.save(path)
    return path


# ---- labels -------------------------------------------------------------------------------------


def test_one_unparsed_label_line_is_reported_but_does_not_block_the_comparison(tmp_path):
    path = tmp_path / "label.pdf"
    render_label_pdf(LabelSpec(ref="1295108", product_name="Kit", contents=["Sterile unless opened", "1 Each - Mask", "2 Each - Gown"]), path)
    label = parse_label_pdf(path)
    assert [i.description for i in label.items] == ["Mask", "Gown"]
    assert any("unparsed text" in w for w in label.warnings)
    assert label.header["unreadable_pages"] == []
    rows = run_bom_label_check(bom_doc([("1", "MASK", "1"), ("2", "GOWN", "2")]), label, ladder(), TH)
    assert len(compared(rows)) == 2 and not blockers(rows)


def test_native_label_text_is_kept_when_the_ref_is_artwork_and_no_ocr_engine_exists(tmp_path, monkeypatch):
    path = native_label_without_ref(tmp_path / "label.pdf")
    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_available", lambda: False)
    label = parse_label_pdf(path)
    assert [i.description for i in label.items] == ["Mask", "Gown"]
    assert label.header["unreadable_pages"] == []
    assert not any("nothing extracted" in w for w in label.warnings)
    assert any("REF" in w for w in label.warnings)


def test_native_label_text_survives_an_empty_ocr_reread(tmp_path, monkeypatch):
    path = native_label_without_ref(tmp_path / "label.pdf")
    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_available", lambda: True)
    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_page", lambda page: OcrResult(engine="fake"))
    label = parse_label_pdf(path)
    assert [i.description for i in label.items] == ["Mask", "Gown"]
    assert label.header["unreadable_pages"] == []


def test_label_continuation_page_keeps_native_text_once_identity_is_known(tmp_path, monkeypatch):
    path = tmp_path / "label.pdf"
    with pymupdf.open() as pdf:
        for n, lines in enumerate([["REF 1295108", "Contents:", "1 Each - Mask"], ["Contents (continued):", "2 Each - Gown"]]):
            page = pdf.new_page(width=420, height=300)
            for k, text in enumerate(lines):
                page.insert_text((20, 30 + 20 * k), text, fontsize=8)
            if n:
                add_image(page, pymupdf.Rect(360, 10, 400, 50))
        pdf.save(path)
    calls = []
    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_available", lambda: True)
    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_page", lambda page: calls.append(page.number) or OcrResult(engine="fake"))
    label = parse_label_pdf(path)
    assert calls == []
    assert [i.description for i in label.items] == ["Mask", "Gown"]
    assert label.header["unreadable_pages"] == []


@pytest.mark.parametrize("tokens", [["REFERENCE", "GUIDE"], ["Do", "not", "REFRIGERATE"], ["REFILLABLE"]])
def test_words_that_start_with_ref_are_not_catalogue_numbers(tokens):
    line = [Word(t, 10 + 60 * i, 10, 60 + 60 * i, 18, 0, 0, i) for i, t in enumerate(tokens)]
    assert _find_ref([line]) == (None, 0, None)


def test_a_fused_ref_with_a_catalogue_number_is_still_found():
    assert _find_ref([[Word("REF:1295108D", 10, 10, 80, 18, 0, 0, 0)]]) == ("1295108D", 1, 0)


# ---- BOMs ---------------------------------------------------------------------------------------


def two_row_bom(path, second_item="RM1234568"):
    render_bom_pdf(BomSpec(parent_item="1295108NS", parent_description="KIT", rows=[BomRowSpec(item="RM1234567", description="MASK"), BomRowSpec(item=second_item, description="GOWN", qty_per="2.0000")]), path)
    return path


def test_a_bom_page_without_a_table_is_ignored_rather_than_unreadable(tmp_path):
    with pymupdf.open(two_row_bom(tmp_path / "bom.pdf")) as pdf:
        page = pdf.new_page(width=pdf[0].rect.width, height=pdf[0].rect.height)
        page.insert_text((40, 60), "*** End of Report ***", fontsize=9)
        pdf.save(tmp_path / "with-end-page.pdf")
    bom = parse_bom_pdf(tmp_path / "with-end-page.pdf")
    assert len(bom.items) == 2 and bom.header["unreadable_pages"] == []
    rows = run_bom_label_check(bom, label_doc([("Mask", "1"), ("Gown", "2")]), ladder(), TH)
    assert len(compared(rows)) == 2 and not blockers(rows)


def test_a_bom_page_with_rows_but_no_column_header_still_blocks(tmp_path):
    with pymupdf.open(two_row_bom(tmp_path / "bom.pdf")) as pdf:
        page = pdf.new_page(width=pdf[0].rect.width, height=pdf[0].rect.height)
        for n, (item, desc) in enumerate([("RM1234569", "GLOVES"), ("RM1234570", "DRAPE")]):
            for x, text in [(18, "1"), (60, item), (162, desc), (296, "5150"), (382, "1.0000"), (479, "1.0000"), (558, "EA")]:
                page.insert_text((x, 95 + 20 * n), text, fontsize=6)
        pdf.save(tmp_path / "continuation.pdf")
    assert parse_bom_pdf(tmp_path / "continuation.pdf").header["unreadable_pages"] == [2]


def test_an_unparseable_bom_row_is_flagged_while_the_rest_is_compared(tmp_path):
    bom = parse_bom_pdf(two_row_bom(tmp_path / "bom.pdf", second_item="RM12/345"))
    assert [i.item_number for i in bom.items] == ["RM1234567"]
    assert bom.header["unreadable_pages"] == [] and len(bom.header["unparsed_rows"]) == 1
    for rows in (run_bom_label_check(bom, label_doc([("Mask", "1")]), ladder(), TH), run_bom_drawing_check(bom, drawing_doc(["MASK"]), ladder(), TH)):
        assert compared(rows)
        flagged = blockers(rows)
        assert len(flagged) == 1 and "RM12/345" in flagged[0].explanation


# ---- drawings -----------------------------------------------------------------------------------


def test_a_notes_block_near_the_top_does_not_hide_callouts_below_it(tmp_path):
    baseline = [c.description for c in callouts(parse_drawing_pdf(GOLDEN / "drawing.pdf"))]
    with pymupdf.open(GOLDEN / "drawing.pdf") as pdf:
        # Clear space at the top of the sheet, above the callout columns.
        pdf[0].insert_text((300, 20), "NOTES:", fontsize=7)
        pdf[0].insert_text((300, 30), "1. ALL DIMENSIONS IN MM", fontsize=7)
        pdf.save(tmp_path / "drawing.pdf")
    drawing = parse_drawing_pdf(tmp_path / "drawing.pdf")
    assert [c.description for c in callouts(drawing)] == baseline
    assert any("ALL DIMENSIONS IN MM" in note["text"] for note in drawing.header["notes"])


def test_an_english_only_scanned_drawing_keeps_its_callouts(tmp_path, monkeypatch):
    path = tmp_path / "DWG1234567.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=792, height=612)
        add_image(page, page.rect)
        pdf.save(path)
    words = [("SURGICAL", 100, 100), ("TAPE", 172, 100), ("MASK", 100, 200), ("ISOLATION", 100, 300), ("GOWN", 180, 300), ("DWG1234567", 600, 560)]
    result = OcrResult(words=[(x, y, x + 8 * len(t), y + 9, t, 0.95) for t, x, y in words], engine="fake")
    monkeypatch.setattr("kaizen.ingest.drawing_pdf.ocr_available", lambda: True)
    monkeypatch.setattr("kaizen.ingest.drawing_pdf.ocr_page", lambda page, **kwargs: result)
    drawing = parse_drawing_pdf(path)
    assert sorted(c.description for c in callouts(drawing)) == ["ISOLATION GOWN", "MASK", "SURGICAL TAPE"]


# ---- OCR ----------------------------------------------------------------------------------------


def test_tesseract_tsv_is_not_split_by_quote_characters(monkeypatch):
    tsv = 'level\tleft\ttop\twidth\theight\tconf\ttext\n5\t10\t20\t30\t8\t90\t"4\n5\t50\t20\t30\t8\t90\tGAUZE\n5\t90\t20\t30\t8\t90\tPAD\n'
    monkeypatch.setattr(ocr.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=tsv.encode()))
    assert [w[4] for w in ocr._recognize(b"png", "tesseract", False)] == ['"4', "GAUZE", "PAD"]


@pytest.mark.parametrize(
    "ocr_text,plain",
    [
        ("SherlockTM Sensor Holder", "Sherlock Sensor Holder"),
        ("Sherlock TM Sensor Holder", "Sherlock Sensor Holder"),
        ("StatLockTM Stabilization Device", "StatLock Stabilization Device"),
        ("MicroEZTM Microintroducer", "MicroEZ Microintroducer"),
        ("Sherlock 3CGTM TPS", "Sherlock 3CG\u2122 TPS"),
    ],
)
def test_a_textual_trademark_is_ignored_like_the_symbol(ocr_text, plain):
    assert normalize(ocr_text).tokens == normalize(plain).tokens


def test_an_all_caps_word_ending_in_tm_is_not_changed():
    assert normalize("ATM CARD").tokens == ["ATM", "CARD"]


def test_the_real_sensor_holder_ocr_line_reaches_its_approved_relationship():
    outcome = ladder().match("SENSOR HOLDER BAG, TLS III", "SherlockTM Sensor Holder")
    assert outcome.level is MatchLevel.RELATIONSHIP


# ---- inputs -------------------------------------------------------------------------------------


def test_a_rights_protected_workbook_says_a_password_will_not_open_it(tmp_path):
    path = tmp_path / "Relationship Input Workbook.xlsx"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + "EncryptedPackage".encode("utf-16le") + "DRMEncryptedTransform".encode("utf-16le"))
    result = parse_document(path)
    assert result.document is None and "sensitivity label" in result.reason and "unprotected copy" in result.reason
