"""Regressions for failure modes found in the BD delivery; no customer files needed."""

import copy
from datetime import datetime
from types import SimpleNamespace

import openpyxl
import pymupdf
import pytest

from kaizen.checks.base import header_item
from kaizen.checks.bom_drawing import callouts, run_bom_drawing_check
from kaizen.checks.bom_label import run_bom_label_check
from kaizen.checks.label_drawing import run_label_drawing_check
from kaizen.datasets.pdf_bom import BomRowSpec, BomSpec, render_bom_pdf
from kaizen.datasets.pdf_label import LabelSpec, render_label_pdf
from kaizen.evaluation.source_validation import compare_bom_sources
from kaizen.ingest import ocr
from kaizen.ingest.bom_categorize import categorize
from kaizen.ingest.bom_pdf import parse_bom_pdf
from kaizen.ingest.bom_table import parse_bom_table
from kaizen.ingest.detect import detect_doc_type, parse_document
from kaizen.ingest.drawing_pdf import parse_drawing_pdf
from kaizen.ingest.grouping import group_by_sku
from kaizen.ingest.label_pdf import _expand_fused_tokens, parse_label_pdf
from kaizen.ingest.ocr import OcrResult
from kaizen.ingest.pdf_words import Word, extract_words
from kaizen.matching.ladder import MatchLadder
from kaizen.models import Classification, DocType, ItemCategory, Severity, Thresholds
from kaizen.pipeline import ingest_folder, run_checks
from kaizen.reporting.annotated_bom import write_annotated_bom
from kaizen.terminology.store import RelationshipStore
from tests.unit.test_bom_label_check import bom_doc, label_doc
from tests.unit.test_pairing_engine import drawing_doc


def blank_pdf(path, width=792, height=612):
    with pymupdf.open() as pdf:
        pdf.new_page(width=width, height=height)
        pdf.save(path)
    return path


@pytest.mark.parametrize("name,kind", [("DWG1234567 (1).pdf", DocType.DRAWING), ("LAB1234567.pdf", DocType.LABEL)])
def test_bd_identifiers_route_scans(name, kind, tmp_path):
    assert detect_doc_type(blank_pdf(tmp_path / name)) is kind


def test_encrypted_workbook_reports_actionable_reason(tmp_path):
    path = tmp_path / "Relationship Input Workbook.xlsx"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + "EncryptedPackage".encode("utf-16le"))
    result = parse_document(path)
    assert result.document is None and "encrypted" in result.reason


def test_one_corrupt_file_does_not_abort_other_documents(tmp_path):
    render_label_pdf(LabelSpec(ref="1295108", product_name="Kit", contents=["1 Each - Mask"]), tmp_path / "label.pdf")
    (tmp_path / "bom.pdf").write_bytes(b"not a PDF")
    ing = ingest_folder(tmp_path)
    assert len(ing.documents) == 1 and len(ing.inputs) == 2
    assert any("parsing failed" in w for w in ing.warnings)


def test_indented_jde_headings_do_not_drop_short_items(tmp_path):
    path = tmp_path / "bom.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=792, height=612)
        page.insert_text((20, 30), "Parent Item 1295108DNS")
        for x, text in [(26, "Level"), (76, "Component Item"), (172, "Component Description"), (284, "Branch/Plant"), (349, "Quantity Per"), (451, "Ext Qty"), (558, "UM")]:
            page.insert_text((x, 70), text, fontsize=6)
        for n, (item, desc, qty) in enumerate([("0703450", "THERMAL TRANSFER RIBBON", "0.0000"), ("LAB1234567", "EN LOD, UNIT LABEL", "1.0000"), ("RM1234567", "CAP DEAD END", "2.0000")]):
            for x, text in [(18, "1"), (60, item), (162, desc), (296, "5150"), (382, qty), (479, qty), (558, "EA")]:
                page.insert_text((x, 95 + 20 * n), text, fontsize=6)
        pdf.save(path)
    parsed = parse_bom_pdf(path)
    assert [(i.item_number, i.description, str(i.quantity)) for i in parsed.items] == [("0703450", "THERMAL TRANSFER RIBBON", "0.0000"), ("LAB1234567", "EN LOD, UNIT LABEL", "1.0000"), ("RM1234567", "CAP DEAD END", "2.0000")]
    assert not parsed.warnings


def test_jde_export_fields_and_inferred_identity_remain_reviewable(tmp_path):
    path = tmp_path / "1295108DNS.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["Item Number", "Description", "Quantity", "UM", "Oper Seq#", "Drawing Number"])
    wb.active.append(["PK1234567", "TAPE, MEASUARING PAPER", 2, "EA", 5, "DWG1234567"])
    wb.save(path)
    bom = parse_bom_table(path)
    assert bom.sku == "1295108DNS" and bom.header["parent_confidence"] == "inferred"
    assert bom.items[0].oper_seq == "5" and bom.items[0].attributes["drawing_number"] == "DWG1234567"
    assert bom.items[0].category is ItemCategory.PHYSICAL_COMPONENT
    th = Thresholds()
    rows = run_bom_label_check(bom, label_doc([("Measuring Tape", "2")]), MatchLadder(RelationshipStore.default(), th), th)
    assert rows[0].classification is Classification.POTENTIAL and rows[0].requires_validation


def test_explicit_export_parent_wins_over_filename(tmp_path):
    path = tmp_path / "1295108DNS.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["Parent Item", "1175108DNS"])
    wb.active.append(["Item Number", "Description", "Quantity"])
    wb.active.append(["123", "Mask", 1])
    wb.save(path)
    bom = parse_bom_table(path)
    assert bom.sku == bom.items[0].sku == "1175108DNS"
    assert "parent_confidence" not in bom.header


def test_bom_parity_detects_duplicates_quantity_and_operation_changes():
    pdf = bom_doc([("1", "MASK", "1"), ("1", "MASK", "1")])
    export = copy.deepcopy(pdf)
    export.items.pop()
    parity = compare_bom_sources(pdf, export)
    assert not parity["equal"] and parity["extra_in_pdf"][0]["occurrences"] == 1
    export = copy.deepcopy(pdf)
    export.items[0].quantity *= 2
    export.items[1].oper_seq = "2"
    parity = compare_bom_sources(pdf, export)
    assert not parity["equal"] and len(parity["missing_from_pdf"]) == 2


def test_bom_parity_normalizes_export_numbers_and_dates():
    pdf = bom_doc([("1", "MASK", "1")])
    export = copy.deepcopy(pdf)
    pdf.items[0].oper_seq, export.items[0].oper_seq = "5", "5.0"
    pdf.items[0].attributes["effective_from"] = "09/30/26"
    export.items[0].attributes["effective_from"] = "2026-09-30"
    assert compare_bom_sources(pdf, export)["equal"]


@pytest.mark.parametrize("text", ["1Each", "1Each-Drape,Fenestrated", "2Each.BlueElasticBand", "1EachDrape,Fenestrated", "Each-Gloves"])
def test_starter_expansion_is_idempotent_and_keeps_original_text(text):
    words = [Word(text, 10, 10, 120, 20, 0, 0, 0, .9)]
    once = _expand_fused_tokens(words)
    assert _expand_fused_tokens(once) == once
    assert " ".join(w.source_text if w.source_text is not None else w.text for w in once).strip() == text


def test_ocr_label_splits_missing_separators_and_keeps_sub_quantities(tmp_path, monkeypatch):
    path = tmp_path / "LAB1234567.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
        pdf.save(path)
    tokens = [("REF", 10, 10), ("1295108D", 45, 10), ("Contents:", 10, 50), ("1EachECGElectrodes,3perpouch", 10, 70), ("1Each-Gloves", 10, 90), ("(1 pair)", 130, 90), ("2Each.BlueElasticBand", 10, 110)]
    result = OcrResult(words=[(x, y, x + len(t) * 3, y + 7, t, .88) for t, x, y in tokens], engine="fake")
    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_available", lambda: True)
    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_page", lambda page: result)
    doc = parse_label_pdf(path)
    assert [i.description for i in doc.items] == ["ECG Electrodes", "Gloves", "Blue Elastic Band"]
    assert [i.sub_quantity.value if i.sub_quantity else None for i in doc.items] == [3, 1, None]
    assert doc.items[0].evidence.raw_text == "1EachECGElectrodes,3perpouch"


def test_tesseract_tsv_keeps_real_word_boxes_and_confidence(monkeypatch):
    tsv = "level\tleft\ttop\twidth\theight\tconf\ttext\n5\t10\t20\t30\t8\t87.5\tNeedle\n5\t50\t20\t15\t8\t-1\tHolder\n"
    calls = []
    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=tsv.encode())
    monkeypatch.setattr(ocr.subprocess, "run", fake_run)
    assert ocr._recognize(b"png", "tesseract", False) == [(10, 20, 40, 28, "Needle", .875), (50, 20, 65, 28, "Holder", 0)]
    assert calls[0][0][-1] == "tsv" and calls[0][1]["timeout"] == 120


def test_ocr_rotation_and_cache_use_displayed_coordinates(tmp_path, monkeypatch):
    path = blank_pdf(tmp_path / "scan.pdf", width=600, height=800)
    monkeypatch.setattr(ocr, "available_engines", lambda: ["fake"])
    calls = []
    def recognize(*args):
        calls.append(1)
        return [(30, 60, 90, 90, "MASK", .8)]
    monkeypatch.setattr(ocr, "_recognize", recognize)
    ocr._CACHE.clear()
    with pymupdf.open(path) as pdf:
        pdf[0].set_rotation(270)
        first = ocr.ocr_page(pdf[0], dpi=144)
        second = ocr.ocr_page(pdf[0], dpi=144)
    assert first.words == [(15, 30, 45, 45, "MASK", .8)] and second.words == first.words
    assert len(calls) == 1
    second.words.clear()
    assert first.words
    ocr._CACHE.clear()


def test_native_words_follow_displayed_rotation(tmp_path):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.insert_text((30, 60), "MASK")
        unrotated = pymupdf.Rect(page.get_text("words")[0][:4])
        page.set_rotation(270)
        word = extract_words(page)[0]
        expected = unrotated * page.rotation_matrix
        assert (word.x0, word.y0, word.x1, word.y1) == tuple(expected)


def test_drawing_ocr_failure_is_a_blocker_not_a_list_of_missing_components(tmp_path, monkeypatch):
    path = blank_pdf(tmp_path / "DWG1234567.pdf")
    monkeypatch.setattr("kaizen.ingest.drawing_pdf.ocr_available", lambda: True)
    def fail(page):
        raise RuntimeError("bad engine")
    monkeypatch.setattr("kaizen.ingest.drawing_pdf.ocr_page", fail)
    drawing = parse_drawing_pdf(path)
    th = Thresholds()
    ladder = MatchLadder(RelationshipStore.default(), th)
    rows = run_bom_drawing_check(bom_doc([("1", "MASK", "2"), ("2", "GOWN", "1")]), drawing, ladder, th)
    assert len(rows) == 2 and rows[-1].discrepancies[0].severity is Severity.BLOCKER
    assert "EXTRACTION INCOMPLETE" in rows[-1].explanation
    label_rows = run_label_drawing_check(label_doc([("Mask", "2")]), drawing, ladder, th)
    assert len(label_rows) == 1 and label_rows[0].discrepancies[0].severity is Severity.BLOCKER


def test_partial_bom_is_not_compared_as_complete():
    bom = bom_doc([("1", "MASK", "2")])
    bom.header["unreadable_pages"] = [2]
    th = Thresholds()
    rows = run_bom_label_check(bom, label_doc([("Mask", "2")]), MatchLadder(RelationshipStore.default(), th), th)
    assert len(rows) == 2 and rows[-1].discrepancies[0].severity is Severity.BLOCKER


def test_empty_ocr_result_on_second_label_page_blocks_partial_comparison(tmp_path, monkeypatch):
    path = tmp_path / "label.pdf"
    render_label_pdf(LabelSpec(ref="1295108", product_name="Kit", contents=["1 Each - Mask"]), path)
    with pymupdf.open(path) as pdf:
        page = pdf.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
        pdf.save(tmp_path / "two-pages.pdf")
    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_available", lambda: True)
    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_page", lambda page: OcrResult(engine="fake"))
    label = parse_label_pdf(tmp_path / "two-pages.pdf")
    assert len(label.items) == 1 and label.header["unreadable_pages"] == [2]
    th = Thresholds()
    rows = run_bom_label_check(bom_doc([("1", "MASK", "1")]), label, MatchLadder(RelationshipStore.default(), th), th)
    assert rows[-1].discrepancies[0].severity is Severity.BLOCKER


def test_low_confidence_revision_is_review_required_before_claiming_mismatch():
    bom, drawing = bom_doc([("1", "DWG3173108 REV 11", "0")]), drawing_doc(["MASK"], rev="12")
    drawing.header["revision_confidence"] = .45
    th = Thresholds()
    row = run_bom_drawing_check(bom, drawing, MatchLadder(RelationshipStore.default(), th), th)[0]
    assert row.classification is Classification.POTENTIAL and row.requires_validation


def test_repeated_callouts_merge_evidence_and_do_not_clear_required_occurrence():
    drawing = drawing_doc([("MASK", True), ("MASK", False)])
    drawing.items[1].evidence.page = 2
    merged = callouts(drawing)
    assert len(merged) == 1 and not merged[0].attributes["conditional"]
    assert [ev["page"] for ev in merged[0].attributes["occurrences"]] == [1, 2]
    assert len(drawing.items) == 2


def test_reference_only_drawing_needs_applicability_review():
    drawing = drawing_doc(["BIOPATCH"])
    drawing.header["reference_only"] = True
    th = Thresholds()
    rows = run_label_drawing_check(label_doc([("Mask", "2")]), drawing, MatchLadder(RelationshipStore.default(), th), th)
    extra = next(r for r in rows if r.source_a is None)
    assert extra.classification is Classification.POTENTIAL and extra.requires_validation
    assert extra.discrepancies[0].severity is Severity.INFO


def test_header_item_retains_actual_header_evidence():
    drawing = drawing_doc(["MASK"])
    drawing.header["identity_evidence"] = {"page": 3, "bbox": {"x0": 10, "y0": 20, "x1": 50, "y1": 30}, "raw_text": "DWG3173108", "extraction_method": "ocr"}
    header = header_item(drawing, "drawing")
    assert header.evidence.page == 3 and header.evidence.bbox.x0 == 10 and header.evidence.extraction_method == "ocr"


def test_matching_identity_with_low_ocr_confidence_needs_review():
    bom, label = bom_doc([("1", "MASK", "1")]), label_doc([("Mask", "1")])
    label.header["identity_confidence"] = .45
    th = Thresholds()
    row = run_bom_label_check(bom, label, MatchLadder(RelationshipStore.default(), th), th)[0]
    assert row.classification is Classification.POTENTIAL and row.requires_validation


def test_run_id_changes_when_ocr_output_changes_even_with_same_source(tmp_path):
    render_bom_pdf(BomSpec(parent_item="1295108DNS", parent_description="Kit", rows=[BomRowSpec(item="1", description="MASK")]), tmp_path / "bom.pdf")
    ing = ingest_folder(tmp_path)
    original = run_checks(ing, RelationshipStore.default())
    changed = copy.deepcopy(ing)
    changed.documents[0].items[0].extraction_confidence = .6
    rerun = run_checks(changed, RelationshipStore.default())
    assert original.metadata.run_id != rerun.metadata.run_id
    assert len(original.metadata.extraction_signature) == 64


def test_shared_drawing_and_mirrors_are_grouped_without_duplicate_checks():
    bom = bom_doc([("1", "MASK", "2")])
    bom.path = "files/boms/one.pdf"
    lab = label_doc([("Mask", "2")])
    lab.path = "files/labels/one.pdf"
    drawing = drawing_doc(["MASK"])
    drawing.path = "files/drawings/shared.pdf"
    groups = group_by_sku([bom, lab, drawing])
    assert len(groups) == 1 and set(groups[0].document_ids) == {bom.id, lab.id, drawing.id}
    assert any("shared drawing" in w for w in groups[0].warnings)


def test_distinct_orphan_drawing_is_not_discarded_when_set_already_has_one():
    bom, label, drawing = bom_doc([("1", "MASK", "1")]), label_doc([("Mask", "1")]), drawing_doc(["MASK"])
    orphan = copy.deepcopy(drawing)
    orphan.id, orphan.sha256, orphan.path, orphan.sku = "dwg:other", "ff" * 32, "other/another.pdf", "DWG1234567"
    groups = group_by_sku([bom, label, drawing, orphan])
    assert len(groups) == 2 and any(g.document_ids == [orphan.id] for g in groups)


def test_rotated_bom_marks_follow_displayed_evidence(tmp_path):
    from kaizen.models import BBox
    path = blank_pdf(tmp_path / "bom.pdf", width=600, height=800)
    with pymupdf.open(path) as pdf:
        pdf[0].set_rotation(270)
        pdf.save(tmp_path / "rotated.pdf")
    bom = bom_doc([("1", "MASK", "1")])
    bom.path = str(tmp_path / "rotated.pdf")
    bom.items[0].evidence.bbox = BBox(x0=50, y0=100, x1=90, y1=110)
    th = Thresholds()
    rows = run_bom_label_check(bom, label_doc([("Mask", "1")]), MatchLadder(RelationshipStore.default(), th), th)
    run = SimpleNamespace(results=rows, metadata=SimpleNamespace(run_id="test", timestamp=datetime.now()))
    outcome = write_annotated_bom(run, bom, tmp_path / "marked.pdf")
    with pymupdf.open(outcome.path) as pdf:
        mark = outcome.mark_list[0]
        drawn = pdf[0].get_drawings()[0]["rect"] * pdf[0].rotation_matrix
        assert drawn.x0 == pytest.approx(mark.x) and (drawn.y0 + drawn.y1) / 2 == pytest.approx(105)


@pytest.mark.parametrize("desc,expected", [("TAPE, MEASUARING PAPER", ItemCategory.PHYSICAL_COMPONENT), ("CSR WRAP 40IN. X 40IN.", ItemCategory.PACKAGING), ("FFS POUCH", ItemCategory.PACKAGING), ("GUIDEWIRE HANG TAG", ItemCategory.LABEL)])
def test_real_category_variants(desc, expected):
    from decimal import Decimal
    assert categorize("PK1234567", desc, Decimal(1))[0] is expected
