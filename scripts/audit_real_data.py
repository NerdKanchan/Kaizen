"""Reproduce real-data extraction validation and write a reviewable run and workbook.

Usage: .venv/bin/python scripts/audit_real_data.py trainingdataset --out out/real-bd
Customer documents remain local. Outputs are ignored by Git.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from kaizen.ai.providers import NullProvider
from kaizen.checks.bom_drawing import callouts
from kaizen.evaluation.source_validation import compare_bom_sources
from kaizen.models import DocType
from kaizen.pipeline import run_folder, save_run
from kaizen.reporting.excel import write_report
from kaizen.terminology.store import RelationshipStore


def audit(root: Path, out: Path, relationships: Path | None = None) -> dict:
    root, out = root.resolve(), out.resolve()
    store = RelationshipStore.load(relationships) if relationships else RelationshipStore.default()
    run = run_folder(root, store, provider=NullProvider())
    out.mkdir(parents=True, exist_ok=True)
    save_run(run, out / "run.json")
    write_report(run, out / "report.xlsx")
    pdf_boms = {d.sku: d for d in run.documents if d.doc_type is DocType.BOM and d.path.lower().endswith(".pdf")}
    exports = {d.sku: d for d in run.documents if d.doc_type is DocType.BOM and d.path.lower().endswith(".xlsx")}
    parity = [compare_bom_sources(pdf_boms[sku], exports[sku]) for sku in sorted(pdf_boms.keys() & exports.keys())]
    unique = {d.sha256: d for d in run.documents}
    docs = [{"file": d.path, "type": d.doc_type.value, "sku": d.sku, "items": len(d.items), "callout_identities": len(callouts(d)) if d.doc_type is DocType.DRAWING else None, "header": d.header, "warnings": d.warnings} for d in unique.values()]
    counts = {}
    for check in sorted({r.check.value for r in run.results}):
        rows = [r for r in run.results if r.check.value == check]
        compared = [r for r in rows if r.role != "exempt"]
        counts[check] = {"rows": len(rows), "exempt": len(rows) - len(compared), "classifications_of_reviewable_rows": dict(Counter(r.classification.value for r in compared)), "needs_review": sum(r.requires_validation for r in compared)}
    data = {"run_id": run.metadata.run_id, "input_files": len(run.metadata.inputs), "parsed_documents": len(run.documents), "unique_parsed_files": len(unique), "sku_sets": len(run.groups), "bom_export_parity": parity, "documents": docs, "groups": [g.model_dump(mode="json") for g in run.groups], "checks": counts, "warnings": run.warnings,
            "limitations": ["PDF/export parity validates extraction, not document approval or matching accuracy.", "Label counts alone do not prove every OCR word or number is correct.", "Drawing OCR reads callout text; it does not verify leader endpoints, cavity occupancy, placement, or visual component identity.", "No reviewer-approved real-data pairing/discrepancy ground truth was supplied.", "PCO and old/new label checks cannot be validated on this delivery: those sources are absent."]}
    (out / "validation.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    lines = ["# Real BD data validation", "", f"Run `{run.metadata.run_id}`. {data['input_files']} inputs, {data['parsed_documents']} parsed document copies, {data['sku_sets']} comparison sets.", "", "## BOM PDF versus spreadsheet", "", "Compares every item number, description, quantity, unit, operation sequence, and effective date. Duplicate rows are counted.", "", "| SKU | PDF rows | Export rows | All compared fields equal |", "|---|---:|---:|---|"]
    lines += [f"| {p['sku']} | {p['pdf_rows']} | {p['export_rows']} | {'Yes' if p['equal'] else 'NO'} |" for p in parity]
    lines += ["", "## Cross-check status", "", "Exempt rows are omitted from the classification counts below. MISSING means the engine could not establish a pairing; these are not verified product defects.", ""]
    lines += [f"- {check}: {info['classifications_of_reviewable_rows']}; {info['needs_review']} rows need review; {info['exempt']} exemptions." for check, info in counts.items()]
    lines += ["", "## Input and extraction warnings", ""] + [f"- {w}" for w in run.warnings]
    lines += ["", "## Comparison grouping", "", "Mirrored sources remain in run.json. Identical copies and matching export references are compared once; each explicit SKU set keeps its supplied drawing.", ""]
    for group in run.groups:
        lines += [f"- {group.sku}: {len(group.document_ids)} comparison documents."] + [f"  - {w}" for w in group.warnings if "identical copy" in w or "matching spreadsheet" in w or "shared drawing" in w]
    for doc in docs:
        lines += ["", f"### {Path(doc['file']).name}", "", f"{doc['type']}: {doc['items']} extracted items; identity {doc['sku']}. All per-item page boxes, raw text and confidence are in run.json."]
        lines += [f"- {w}" for w in doc['warnings']]
    lines += ["", "## Remaining validation limits", ""] + [f"- {w}" for w in data['limitations']]
    (out / "validation.md").write_text("\n".join(lines) + "\n")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, default=Path("out/real-bd"))
    parser.add_argument("--relationships", type=Path)
    args = parser.parse_args()
    result = audit(args.root, args.out, args.relationships)
    print(json.dumps({k: result[k] for k in ("run_id", "input_files", "parsed_documents", "sku_sets", "checks", "warnings")}, indent=2))
    raise SystemExit(0 if result["bom_export_parity"] and all(p["equal"] for p in result["bom_export_parity"]) else 1)
