import pymupdf
import pytest

from kaizen.datasets.pdf_bom import BomRowSpec, BomSpec, render_bom_pdf
from kaizen.datasets.pdf_label import LabelSpec, render_label_pdf
from kaizen.models import Classification, Thresholds
from kaizen.pipeline import discover_files, load_run, run_folder, save_run
from kaizen.ingest.grouping import identity_key
from kaizen.terminology.store import RelationshipStore


@pytest.fixture
def dataset(tmp_path):
    render_bom_pdf(
        BomSpec(parent_item="1295108NS", parent_description="KIT A", rows=[BomRowSpec(item="0396447", description="ABSORBENT TOWEL"), BomRowSpec(item="5167473", description="TAPE ANCHOR PER-Q-CATH"), BomRowSpec(item="BAW0724416", description="EN LOD, UNIT LABEL")]),
        tmp_path / "sku-001" / "bom.pdf",
    )
    render_label_pdf(LabelSpec(ref="1295108", product_name="Kit A", contents=["1 Each - Towel, Absorbent", "1 Each - Surgical Tape"]), tmp_path / "sku-001" / "label.pdf")
    render_bom_pdf(BomSpec(parent_item="1395108QNS", parent_description="KIT B", rows=[BomRowSpec(item="0396447", description="ABSORBENT TOWEL", qty_per="2.0000")]), tmp_path / "sku-002" / "bom.pdf")
    render_label_pdf(LabelSpec(ref="1395108", product_name="Kit B", contents=["1 Each - Towel, Absorbent"]), tmp_path / "sku-002" / "label.pdf")
    (tmp_path / "notes.txt").write_text("not a document")
    d = pymupdf.open()
    d.new_page()
    d.save(tmp_path / "sku-002" / "pco_form.pdf")
    return tmp_path


def test_identity_key_matches_label_ref_and_bom_parent():
    assert identity_key("1175108D") == identity_key("1175108DNS") == "1175108"


def test_unreadable_label_ref_is_inferred_and_requires_validation(tmp_path):
    render_bom_pdf(BomSpec(parent_item="1295108DNS", parent_description="KIT", rows=[BomRowSpec(item="0396447", description="ABSORBENT TOWEL")]), tmp_path / "sku" / "bom.pdf")
    render_label_pdf(LabelSpec(ref="", product_name="Kit", contents=["1 Each - Towel, Absorbent"]), tmp_path / "sku" / "label.pdf")

    run = run_folder(tmp_path, RelationshipStore.default(), Thresholds())
    label = next(d for d in run.documents if d.doc_type.value == "LABEL")
    header = next(r for r in run.results if r.role == "header" and r.check.value == "BOM_LABEL")
    assert label.sku == "1295108D"
    assert label.header["ref_confidence"] == "inferred"
    assert header.classification is Classification.POTENTIAL
    assert header.requires_validation


def test_discover_files_is_sorted_and_filtered(dataset):
    files = discover_files(dataset)
    names = [f.relative_to(dataset).as_posix() for f in files]
    assert names == ["sku-001/bom.pdf", "sku-001/label.pdf", "sku-002/bom.pdf", "sku-002/label.pdf", "sku-002/pco_form.pdf"]


def test_run_folder_end_to_end(dataset):
    run = run_folder(dataset, RelationshipStore.default(), Thresholds())
    assert len(run.documents) == 5  # the blank pco_form.pdf parses as an empty PCO (with warnings)
    assert [g.sku for g in run.groups] == ["1295108NS", "1395108QNS"]  # the PCO is batch-level, not a SKU-set member
    by_sku = {}
    for r in run.results:
        if r.role != "exempt":
            by_sku.setdefault(r.sku, []).append(r)
    cls_001 = [r.classification for r in by_sku["1295108NS"]]
    assert cls_001 == [Classification.EXACT, Classification.EXACT, Classification.EQUIVALENT]
    assert by_sku["1395108QNS"][1].classification is Classification.MISMATCH
    assert any(r.role == "exempt" and r.source_a.item_number == "BAW0724416" for r in run.results)
    assert "REL-001" in run.relationships_used
    pco = next(d for d in run.documents if d.doc_type.value == "PCO")
    assert any("affected" in w.lower() for w in pco.warnings)
    assert {i.doc_type for i in run.metadata.inputs} >= {"BOM", "LABEL", "PCO"}
    assert all(len(i.sha256) == 64 and i.size_bytes > 0 for i in run.metadata.inputs)
    assert run.metadata.terminology_version and run.metadata.terminology_count >= 2
    assert "NOT IMPLEMENTED" in " ".join(run.metadata.capabilities.values())
    assert any(e.action == "run.completed" for e in run.audit_log)


def test_run_id_is_deterministic_for_same_inputs(dataset):
    a = run_folder(dataset, RelationshipStore.default(), Thresholds())
    b = run_folder(dataset, RelationshipStore.default(), Thresholds())
    assert a.metadata.run_id == b.metadata.run_id
    c = run_folder(dataset, RelationshipStore.default(), Thresholds(potential=0.9))
    assert c.metadata.run_id != a.metadata.run_id


def test_run_round_trips_through_json(dataset, tmp_path):
    run = run_folder(dataset, RelationshipStore.default(), Thresholds())
    path = save_run(run, tmp_path / "out" / "run.json")
    loaded = load_run(path)
    assert loaded.metadata.run_id == run.metadata.run_id
    assert len(loaded.results) == len(run.results)
    assert loaded.results[1].source_a.evidence.bbox is not None


def test_identical_files_in_different_folders_get_distinct_document_ids(tmp_path):
    # Two SKUs can legitimately share a byte-identical label (same REF). IDs must not collide.
    for folder, parent in (("sku-a", "3131910NS"), ("sku-b", "3131910FNS")):
        render_bom_pdf(BomSpec(parent_item=parent, parent_description="KIT", rows=[BomRowSpec(item="0396447", description="ABSORBENT TOWEL")]), tmp_path / folder / "bom.pdf")
        render_label_pdf(LabelSpec(ref="3131910", product_name="Kit", contents=["1 Each - Towel, Absorbent"]), tmp_path / folder / "label.pdf")
    run = run_folder(tmp_path, RelationshipStore.default(), Thresholds())
    ids = [d.id for d in run.documents]
    assert len(ids) == len(set(ids)) == 4
    docs = {d.id: d for d in run.documents}
    for g in run.groups:
        paths = {docs[i].path for i in g.document_ids}
        folder = "sku-a" if g.sku == "3131910NS" else "sku-b"
        assert all(f"/{folder}/" in p for p in paths), paths
