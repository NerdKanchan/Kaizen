"""Extraction method and confidence are recorded; OCR is attempted only when needed and only if available."""

import pymupdf
import pytest

from kaizen.datasets.pdf_label import LabelSpec, render_label_pdf
from kaizen.ingest.label_pdf import parse_label_pdf
from kaizen.ingest.ocr import OcrResult, correct_ocr_text, ocr_available


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Statlockr'·' Stabilization Device", "StatLock Stabilization Device"),
        ("ChloraPrepm Solution", "ChloraPrep Solution"),
        ("ChloraPrepTl.I Solution", "ChloraPrepTM Solution"),
        ("Flexuram Guidewire", "FlexuraTM Guidewire"),
        ("70% lsopropyl Alcohol", "70% Isopropyl Alcohol"),
        ("V1ith Sherlock", "with Sherlock"),
        ("Style! Funnel", "Stylet Funnel"),
        ("SherlockTMSensorHolder", "Sherlock TM Sensor Holder"),
        ("BlueElastic Band", "Blue Elastic Band"),
        ("ECGLeadsAssembly", "ECG Leads Assembly"),
        ("Wipe70%IsopropylAlcohol", "Wipe 70% Isopropyl Alcohol"),
        ("AspirationDevice", "Aspiration Device"),
        ("MicroEZTMMicrointroducer", "MicroEZTM Microintroducer"),
        ("GAUZE 10CMX10CM", "GAUZE 10 CM X 10 CM"),
        ("GAUZE 5CM X5CM", "GAUZE 5 CM X 5 CM"),
        ("Sherlock3CGTMSensor", "Sherlock3CGTM Sensor"),
    ],
)
def test_correct_ocr_text(raw, expected):
    assert correct_ocr_text(raw) == expected


def test_text_pdf_records_pdf_text_method(tmp_path):
    doc = parse_label_pdf(render_label_pdf(LabelSpec(ref="1295108", product_name="Kit", contents=["1 Each - Towel, Absorbent"]), tmp_path / "l.pdf"))
    assert doc.items[0].evidence.extraction_method == "pdf_text"
    assert doc.header["extraction_method"] == "pdf_text"


def test_image_only_pdf_is_detected_and_reported_honestly(tmp_path, monkeypatch):
    src = render_label_pdf(LabelSpec(ref="1295108", product_name="Kit", contents=["1 Each - Towel, Absorbent", "2 Each - Mask"]), tmp_path / "l.pdf")
    pix = pymupdf.open(src)[0].get_pixmap(dpi=120)
    scan = pymupdf.open()
    page = scan.new_page(width=420, height=640)
    page.insert_image(page.rect, pixmap=pix)
    scan_path = tmp_path / "label_scan.pdf"
    scan.save(scan_path)
    monkeypatch.setattr("kaizen.ingest.ocr.ocr_available", lambda: False)
    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_available", lambda: False)
    doc = parse_label_pdf(scan_path)
    assert doc.items == []
    assert doc.header["extraction_method"] == "none"
    assert any("image-only" in w.lower() and "ocr" in w.lower() for w in doc.warnings)


def test_ocr_fallback_used_when_engine_available(tmp_path, monkeypatch):
    src = render_label_pdf(LabelSpec(ref="1295108", product_name="Kit", contents=["1 Each - Towel, Absorbent", "2 Each - Mask"]), tmp_path / "l.pdf")
    words = pymupdf.open(src)[0].get_text("words")
    pix = pymupdf.open(src)[0].get_pixmap(dpi=120)
    scan = pymupdf.open()
    page = scan.new_page(width=420, height=640)
    page.insert_image(page.rect, pixmap=pix)
    scan_path = tmp_path / "label_scan.pdf"
    scan.save(scan_path)

    def fake_ocr(page, dpi=200):  # pretend an OCR engine read the words back, with confidences
        return OcrResult(words=[(w[0], w[1], w[2], w[3], w[4], 0.88) for w in words], engine="fake-ocr", dpi=dpi)

    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_available", lambda: True)
    monkeypatch.setattr("kaizen.ingest.label_pdf.ocr_page", fake_ocr)
    doc = parse_label_pdf(scan_path)
    assert [i.description for i in doc.items] == ["Towel, Absorbent", "Mask"]
    assert doc.header["extraction_method"] == "ocr" and doc.header["ocr_engine"] == "fake-ocr"
    assert all(i.evidence.extraction_method == "ocr" for i in doc.items)
    assert all(i.extraction_confidence <= 0.88 for i in doc.items)
    assert any("ocr" in w.lower() for w in doc.warnings)


def test_ocr_availability_is_a_plain_boolean():
    assert ocr_available() in (True, False)
