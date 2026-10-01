"""Optional execution of an installed OCR engine on a rendered, scanned JDE fixture."""

import pymupdf
import pytest

from kaizen.datasets.pdf_bom import BomRowSpec, BomSpec, render_bom_pdf
from kaizen.ingest.bom_pdf import parse_bom_pdf
from kaizen.ingest.ocr import ocr_available


@pytest.mark.skipif(not ocr_available(), reason="offline OCR engine not installed")
def test_scanned_bom_reads_identity_components_quantities_and_evidence(tmp_path):
    original, scan = tmp_path / "native.pdf", tmp_path / "bom.pdf"
    render_bom_pdf(BomSpec(parent_item="1295108DNS", parent_description="KIT", rows=[BomRowSpec(item="RM1234567", description="SURGICAL TAPE", qty_per="2.0000"), BomRowSpec(item="RM1234568", description="GOWN", qty_per="1.0000")]), original)
    with pymupdf.open(original) as source, pymupdf.open() as pdf:
        for page in source:
            target = pdf.new_page(width=page.rect.width, height=page.rect.height)
            target.insert_image(target.rect, stream=page.get_pixmap(dpi=240).tobytes("png"))
        pdf.save(scan)
    bom = parse_bom_pdf(scan)
    assert bom.sku == "1295108DNS"
    assert [(i.item_number, i.description, int(i.quantity)) for i in bom.items] == [("RM1234567", "SURGICAL TAPE", 2), ("RM1234568", "GOWN", 1)]
    assert all(i.evidence.extraction_method == "ocr" and i.evidence.page == 1 and i.evidence.bbox for i in bom.items)
    assert not bom.header["unreadable_pages"] and bom.header["identity_evidence"]["extraction_method"] == "ocr"
