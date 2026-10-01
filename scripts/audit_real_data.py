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
from kaizen.models import DocType, Run
from kaizen.pipeline import load_run, run_folder, save_run
from kaizen.reporting.excel import write_report
from kaizen.terminology.store import RelationshipStore
from kaizen.workspace import Workspace


def _counts(run: Run) -> dict:
    counts = {}
    for check in sorted({r.check.value for r in run.results}):
        rows = [r for r in run.results if r.check.value == check]
        compared = [r for r in rows if r.role != "exempt"]
        counts[check] = {"rows": len(rows), "exempt": len(rows) - len(compared),
                         "classifications_of_reviewable_rows": dict(Counter(r.classification.value for r in compared)),
                         "needs_review": sum(r.requires_validation for r in compared),
                         "auto_cleared": sum(not r.requires_validation for r in compared)}
    return counts


def compare_coverage(before: Run, after: Run) -> dict:
    before_inputs = sorted((i.path, i.sha256) for i in before.metadata.inputs)
    after_inputs = sorted((i.path, i.sha256) for i in after.metadata.inputs)
    if before_inputs != after_inputs:
        raise ValueError("Baseline and new run must contain the same input paths and file hashes to compare coverage.")
    before_counts, after_counts = _counts(before), _counts(after)
    checks = {}
    for check in sorted(before_counts.keys() | after_counts.keys()):
        old, new = before_counts.get(check, {}), after_counts.get(check, {})
        old_classes, new_classes = old.get("classifications_of_reviewable_rows", {}), new.get("classifications_of_reviewable_rows", {})
        checks[check] = {"before": old, "after": new,
                         "review_rows_reduced": old.get("needs_review", 0) - new.get("needs_review", 0),
                         "auto_cleared_added": new.get("auto_cleared", 0) - old.get("auto_cleared", 0),
                         "classification_delta": {c: new_classes.get(c, 0) - old_classes.get(c, 0) for c in sorted(old_classes.keys() | new_classes.keys())}}
    return {"baseline_run_id": before.metadata.run_id, "baseline_terminology_version": before.metadata.terminology_version,
            "new_terminology_version": after.metadata.terminology_version, "checks": checks,
            "review_rows_reduced": sum(c["review_rows_reduced"] for c in checks.values()),
            "auto_cleared_added": sum(c["auto_cleared_added"] for c in checks.values()),
            "limitation": "This measures matching coverage, not accuracy. Reviewer-approved ground truth is required to measure false clears."}


def audit(root: Path, out: Path, relationships: Path | None = None, workspace: Path | None = None, baseline: Path | None = None) -> dict:
    root, out = root.resolve(), out.resolve()
    if relationships and workspace:
        raise ValueError("Choose either a relationships JSON or the approved workspace terminology.")
    if workspace and not (workspace / "kaizen.db").is_file():
        raise ValueError("Workspace database does not exist. Import the approved relationships into that workspace first.")
    ws = Workspace(workspace) if workspace else None
    store = ws.repository.store() if ws else RelationshipStore.load(relationships) if relationships else RelationshipStore.default()
    before = load_run(baseline) if baseline else None
    run = run_folder(root, store, provider=NullProvider())
    coverage = compare_coverage(before, run) if before else None
    out.mkdir(parents=True, exist_ok=True)
    run_path = save_run(run, out / "run.json")
    if ws:
        ws.register_run(run, run_path)
    write_report(run, out / "report.xlsx")
    pdf_boms = {d.sku: d for d in run.documents if d.doc_type is DocType.BOM and d.path.lower().endswith(".pdf")}
    exports = {d.sku: d for d in run.documents if d.doc_type is DocType.BOM and d.path.lower().endswith(".xlsx")}
    parity = [compare_bom_sources(pdf_boms[sku], exports[sku]) for sku in sorted(pdf_boms.keys() & exports.keys())]
    unique = {d.sha256: d for d in run.documents}
    docs = [{"file": d.path, "type": d.doc_type.value, "sku": d.sku, "items": len(d.items), "callout_identities": len(callouts(d)) if d.doc_type is DocType.DRAWING else None, "header": d.header, "warnings": d.warnings} for d in unique.values()]
    counts = _counts(run)
    data = {"run_id": run.metadata.run_id, "terminology_version": run.metadata.terminology_version, "terminology_count": run.metadata.terminology_count,
            "coverage_comparison": coverage, "input_files": len(run.metadata.inputs), "parsed_documents": len(run.documents), "unique_parsed_files": len(unique), "sku_sets": len(run.groups), "bom_export_parity": parity, "documents": docs, "groups": [g.model_dump(mode="json") for g in run.groups], "checks": counts, "warnings": run.warnings,
            "limitations": ["PDF/export parity validates extraction, not document approval or matching accuracy.", "Label counts alone do not prove every OCR word or number is correct.", "Drawing OCR reads callout text; it does not verify leader endpoints, cavity occupancy, placement, or visual component identity.", "No reviewer-approved real-data pairing/discrepancy ground truth was supplied.", "PCO and old/new label checks cannot be validated on this delivery: those sources are absent."]}
    (out / "validation.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    lines = ["# Real BD data validation", "", f"Run `{run.metadata.run_id}`. {data['input_files']} inputs, {data['parsed_documents']} parsed document copies, {data['sku_sets']} comparison sets.", "", "## BOM PDF versus spreadsheet", "", "Compares every item number, description, quantity, unit, operation sequence, and effective date. Duplicate rows are counted.", "", "| SKU | PDF rows | Export rows | All compared fields equal |", "|---|---:|---:|---|"]
    lines += [f"| {p['sku']} | {p['pdf_rows']} | {p['export_rows']} | {'Yes' if p['equal'] else 'NO'} |" for p in parity]
    lines += ["", "## Cross-check status", "", "Exempt rows are omitted from the classification counts below. MISSING means the engine could not establish a pairing; these are not verified product defects.", ""]
    lines += [f"- {check}: {info['classifications_of_reviewable_rows']}; {info['needs_review']} rows need review; {info['exempt']} exemptions." for check, info in counts.items()]
    lines += ["", f"Terminology: {run.metadata.terminology_count} relationships, snapshot `{run.metadata.terminology_version}`."]
    if coverage:
        lines += ["", "## Coverage change versus baseline", "", f"Baseline `{coverage['baseline_run_id']}` with identical input paths and hashes.", "",
                  "| Check | Review before | Review after | Added auto-cleared rows |", "|---|---:|---:|---:|"]
        lines += [f"| {check} | {c['before'].get('needs_review', 0)} | {c['after'].get('needs_review', 0)} | {c['auto_cleared_added']} |" for check, c in coverage["checks"].items()]
        lines += ["", coverage["limitation"]]
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
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--relationships", type=Path, help="Relationships JSON file.")
    source.add_argument("--workspace", type=Path, help="Existing workspace containing approved imported relationships.")
    parser.add_argument("--baseline", type=Path, help="Previous run.json on the same input files; reports coverage deltas.")
    args = parser.parse_args()
    try:
        result = audit(args.root, args.out, args.relationships, args.workspace, args.baseline)
    except ValueError as e:
        parser.error(str(e))
    print(json.dumps({k: result[k] for k in ("run_id", "terminology_count", "input_files", "parsed_documents", "sku_sets", "checks", "coverage_comparison", "warnings")}, indent=2))
    raise SystemExit(0 if result["bom_export_parity"] and all(p["equal"] for p in result["bom_export_parity"]) else 1)
