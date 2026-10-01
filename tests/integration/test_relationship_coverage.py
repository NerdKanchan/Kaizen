"""An approved source import changes future coverage, with a comparable baseline."""

import runpy
from pathlib import Path

import pytest

from kaizen.datasets.pdf_bom import BomRowSpec, BomSpec, render_bom_pdf
from kaizen.datasets.pdf_label import LabelSpec, render_label_pdf
from kaizen.pipeline import load_run, run_folder, save_run
from kaizen.terminology.source_import import import_source
from kaizen.workspace import Workspace

audit_script = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "audit_real_data.py"))


def test_approved_import_reduces_review_rows_and_preserves_baseline(tmp_path):
    root = tmp_path / "inputs"
    render_bom_pdf(BomSpec(parent_item="1175108DNS", parent_description="KIT", rows=[BomRowSpec(item="0000123", description="CAP DEAD END")]), root / "bom.pdf")
    render_label_pdf(LabelSpec(ref="1175108", product_name="Kit", contents=["1 Each - Closure"]), root / "label.pdf")
    ws = Workspace(tmp_path / "workspace")
    before = run_folder(root, ws.repository.store())
    baseline = save_run(before, tmp_path / "before.json")
    source = tmp_path / "authorized.csv"
    source.write_text("ERP,Customer,Item\nCAP DEAD END,Closure,0000123\n")
    result = import_source(ws.repository, source, "quality", column_map={"Canonical": "Customer", "Aliases": "ERP", "Item Anchors": "Item"})
    assert result.applied and result.created == 1
    after = run_folder(root, ws.repository.store())
    comparison = audit_script["compare_coverage"](load_run(baseline), after)
    assert comparison["checks"]["BOM_LABEL"]["review_rows_reduced"] > 0
    assert comparison["checks"]["BOM_LABEL"]["auto_cleared_added"] > 0
    assert after.metadata.terminology_version != before.metadata.terminology_version
    assert load_run(baseline).metadata.terminology_version == before.metadata.terminology_version
    assert result.rows[0]["id"] not in before.relationships_used
    assert result.rows[0]["id"] in after.relationships_used
    assert "not accuracy" in comparison["limitation"]
    audited = audit_script["audit"](root, tmp_path / "audited", workspace=ws.path, baseline=baseline)
    assert audited["coverage_comparison"]["review_rows_reduced"] > 0
    assert ws.runs.get(audited["run_id"]) is not None
    render_label_pdf(LabelSpec(ref="1175108", product_name="Kit", contents=["2 Each - Closure"]), root / "label.pdf")
    with pytest.raises(ValueError, match="same input paths and file hashes"):
        audit_script["compare_coverage"](before, run_folder(root, ws.repository.store()))
