"""ingest → group → check → Run. Shared by the CLI and the tests; no I/O beyond reading inputs."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from kaizen import __version__
from kaizen.ai.matcher import AiAdjudicationMatcher
from kaizen.ai.providers import AdjudicationProvider, NullProvider, get_provider
from kaizen.checks.bom_drawing import CHECK_VERSION as BOM_DRAWING_VERSION
from kaizen.checks.bom_drawing import run_bom_drawing_check
from kaizen.checks.bom_label import CHECK_VERSION, run_bom_label_check
from kaizen.checks.label_drawing import CHECK_VERSION as LABEL_DRAWING_VERSION
from kaizen.checks.label_drawing import run_label_drawing_check
from kaizen.checks.label_revision import CHECK_VERSION as LABEL_REVISION_VERSION
from kaizen.checks.label_revision import expected_changes_from_pcos, run_label_revision_check
from kaizen.checks.pco_bom import CHECK_VERSION as PCO_CHECK_VERSION
from kaizen.checks.pco_bom import run_pco_bom_check
from kaizen.ingest import bom_pdf, bom_table, drawing_pdf, label_pdf
from kaizen.ingest import pco as pco_parser
from kaizen.ingest.bom_categorize import CATEGORIZER_VERSION
from kaizen.ingest.detect import parse_document
from kaizen.ingest.grouping import group_by_sku, identity_key
from kaizen.ingest.hashing import sha256_file
from kaizen.matching.ladder import MatchLadder
from kaizen.matching.normalize import NORMALIZER_VERSION
from kaizen.models import AuditEvent, CoverageFinding, DiscrepancyType, DocType, InputFile, Run, RunMetadata, Thresholds
from kaizen.terminology.store import RelationshipStore

SUPPORTED_SUFFIXES = {".pdf", ".xlsx", ".xlsm", ".csv"}

CAPABILITIES = {
    "BOM parsing (JDE print PDF)": "IMPLEMENTED",
    "BOM parsing (XLSX/CSV export)": "IMPLEMENTED",
    "Label parsing (text PDF, multi-column kit contents)": "IMPLEMENTED",
    "Check: BOM ↔ Label": "IMPLEMENTED",
    "Duplicate BOM rows for one item merged before comparison": "IMPLEMENTED",
    "Non-physical / zero-qty / inactive BOM lines excluded (listed on Documents sheet)": "IMPLEMENTED",
    "Match ladder L1 exact / L2 relationship / L3 fuzzy": "IMPLEMENTED",
    "Redlines: PDF FreeText annotations": "IMPLEMENTED (captured into row attributes and used by the PCO ↔ BOM check)",
    "Redlines: hand-drawn or scanned": "NOT IMPLEMENTED",
    "OCR for scanned / image-only BOM and drawing pages": "NOT IMPLEMENTED",
    "PCO parsing (FM00835 form, XLSX/CSV/PDF)": "IMPLEMENTED",
    "Check: PCO ↔ BOM (ADD / DELETE / SUBSTITUTE / MODIFY, redline-aware)": "IMPLEMENTED",
    "Coverage: BOM present for every PCO affected code": "IMPLEMENTED",
    "Packaging drawing parsing (vector PDF; EN/ES callouts, conditional callouts, title block)": "IMPLEMENTED",
    "Checks: BOM ↔ Drawing, Label ↔ Drawing (presence/identity, drawing rev)": "IMPLEMENTED",
    "Check: Old ↔ New label (semantic change report, PCO-derived expected changes)": "IMPLEMENTED",
    "Label revision roles by filename token (old/prev vs new/current)": "IMPLEMENTED",
    "Semantic (embedding) matching L4": "IMPLEMENTED as an opt-in rung (needs a local embedding model; can only yield POTENTIAL)",
    "OCR for image-only label pages": "IMPLEMENTED when rapidocr-onnxruntime is installed; otherwise reported as NOT AVAILABLE",
    "Reviewer workflow: two reviewers, server-side blind mode, decisions, action items, mining, Excel round-trip": "IMPLEMENTED",
    "Reviewer UI (local React app served by `kaizen serve`)": "IMPLEMENTED",
}


def discover_files(root: Path | str) -> list[Path]:
    root = Path(root)
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES and not p.name.startswith("~$"))


_OLD_TOKENS = {"old", "prev", "previous", "superseded", "before", "current-release"}
_NEW_TOKENS = {"new", "proposed", "unreleased", "revised", "after", "draft"}


def revision_role(path: Path) -> str:
    tokens = set(re.split(r"[^a-z0-9]+", path.stem.lower()))
    if tokens & _OLD_TOKENS:
        return "old"
    if tokens & _NEW_TOKENS:
        return "new"
    return "current"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


@dataclass
class Ingested:
    root: Path
    documents: list = field(default_factory=list)
    inputs: list[InputFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    audit: list[AuditEvent] = field(default_factory=list)


def ingest_folder(root: Path | str) -> Ingested:
    root = Path(root)
    ing = Ingested(root=root, audit=[AuditEvent(action="run.started", detail=f"input root {root}")])
    inputs, documents, warnings, audit = ing.inputs, ing.documents, ing.warnings, ing.audit
    for f in discover_files(root):
        outcome = parse_document(f)
        rel = _rel(f, root)
        inputs.append(InputFile(path=rel, sha256=sha256_file(f), size_bytes=f.stat().st_size, doc_type=outcome.doc_type.value if outcome.doc_type else None))
        if outcome.document is not None:
            if outcome.document.doc_type is DocType.LABEL:
                outcome.document.header["revision_role"] = revision_role(f)
            documents.append(outcome.document)
            audit.append(AuditEvent(action="document.parsed", detail=f"{rel} → {outcome.doc_type.value} ({outcome.document.parser_name} v{outcome.document.parser_version}), {len(outcome.document.items)} items"))
        else:
            warnings.append(f"{rel}: {outcome.reason}")
            audit.append(AuditEvent(action="document.skipped", detail=f"{rel}: {outcome.reason}"))
    _infer_unreadable_label_refs(documents, audit)
    return ing


def _infer_unreadable_label_refs(documents: list, audit: list[AuditEvent]) -> None:
    """Use one sibling BOM only as a review-required identity hint when a label REF is unreadable."""
    for label in (d for d in documents if d.doc_type is DocType.LABEL and not d.sku):
        siblings = [d for d in documents if d.doc_type is DocType.BOM and Path(d.path).parent == Path(label.path).parent and d.sku]
        if len(siblings) != 1:
            continue
        parent = siblings[0].sku
        family = identity_key(parent)
        if not family:
            continue
        inferred = f"{family}D"
        label.sku = inferred
        label.header["ref"] = inferred
        label.header["ref_inferred_from"] = "paired_bom"
        label.header["ref_confidence"] = "inferred"
        label.warnings.append(f"REF number not readable; inferred {inferred} from paired BOM parent {parent} — verify against the label")
        audit.append(AuditEvent(action="document.identity_inferred", detail=f"{label.path}: label REF inferred as {inferred} from BOM parent {parent}"))


def run_checks(ing: Ingested, store: RelationshipStore, thresholds: Thresholds = Thresholds(), provider: AdjudicationProvider | None = None) -> Run:
    root, documents, inputs = ing.root, list(ing.documents), list(ing.inputs)
    warnings, audit = list(ing.warnings), list(ing.audit)
    provider = provider or get_provider()
    extra = [] if isinstance(provider, NullProvider) else [AiAdjudicationMatcher(provider)]
    groups = group_by_sku(documents)
    docs_by_id = {d.id: d for d in documents}
    ladder = MatchLadder(store, thresholds, extra_matchers=extra)
    results = []
    for g in groups:
        boms = [docs_by_id[i] for i in g.document_ids if docs_by_id[i].doc_type is DocType.BOM]
        all_labels = [docs_by_id[i] for i in g.document_ids if docs_by_id[i].doc_type is DocType.LABEL]
        old_labels = [d for d in all_labels if d.header.get("revision_role") == "old"]
        labels = [d for d in all_labels if d.header.get("revision_role") != "old"]
        drawings = [docs_by_id[i] for i in g.document_ids if docs_by_id[i].doc_type is DocType.DRAWING]
        audit.append(AuditEvent(action="group.formed", detail=f"{g.sku}: {len(boms)} BOM, {len(labels)} label, {len(drawings)} drawing; " + ("; ".join(g.warnings) if g.warnings else "no warnings")))
        if not boms or not labels:
            warnings.append(f"{g.sku}: BOM ↔ Label check skipped ({'no BOM' if not boms else 'no label'})")
        for bom in boms:
            for label in labels:
                res = run_bom_label_check(bom, label, ladder, thresholds)
                results.extend(res)
                audit.append(AuditEvent(action="check.completed", detail=f"BOM_LABEL {g.sku}: {len(res)} rows ({_rel(Path(bom.path), root)} vs {_rel(Path(label.path), root)})"))
            for drawing in drawings:
                res = run_bom_drawing_check(bom, drawing, ladder, thresholds)
                results.extend(res)
                audit.append(AuditEvent(action="check.completed", detail=f"BOM_DRAWING {g.sku}: {len(res)} rows ({_rel(Path(bom.path), root)} vs {_rel(Path(drawing.path), root)})"))
        for label in labels:
            for drawing in drawings:
                res = run_label_drawing_check(label, drawing, ladder, thresholds, sku=g.sku)
                results.extend(res)
                audit.append(AuditEvent(action="check.completed", detail=f"LABEL_DRAWING {g.sku}: {len(res)} rows ({_rel(Path(label.path), root)} vs {_rel(Path(drawing.path), root)})"))
        if old_labels and labels:
            pcos_for_sku = [d for d in documents if d.doc_type is DocType.PCO]
            for old in old_labels:
                for label in labels:
                    exp = expected_changes_from_pcos(pcos_for_sku, g.sku, boms=boms)
                    res = run_label_revision_check(old, label, exp, ladder, thresholds, sku=g.sku)
                    results.extend(res)
                    audit.append(AuditEvent(action="check.completed", detail=f"LABEL_REVISION {g.sku}: {len(res)} rows, {len(exp)} expected change(s) from PCOs ({_rel(Path(old.path), root)} → {_rel(Path(label.path), root)})"))
        elif old_labels:
            warnings.append(f"{g.sku}: an old label was found but no current/new label to compare it with")
    coverage: list[CoverageFinding] = []
    for g in groups:
        has_bom = any(docs_by_id[i].doc_type is DocType.BOM for i in g.document_ids)
        has_label = any(docs_by_id[i].doc_type is DocType.LABEL for i in g.document_ids)
        has_drawing = any(docs_by_id[i].doc_type is DocType.DRAWING for i in g.document_ids)
        status = "OK" if has_bom and has_label else ("MISSING_BOM" if not has_bom else "MISSING_LABEL")
        coverage.append(CoverageFinding(kind="sku_set", sku=g.sku, status=status, detail=f"BOM {'present' if has_bom else 'MISSING'}, label {'present' if has_label else 'MISSING'}, drawing {'present' if has_drawing else 'absent (drawing checks skipped)'}", source=", ".join(_rel(Path(docs_by_id[i].path), root) for i in g.document_ids)))
    pcos = [d for d in documents if d.doc_type is DocType.PCO]
    boms = [d for d in documents if d.doc_type is DocType.BOM]
    for pco in pcos:
        res = run_pco_bom_check(pco, boms, ladder, thresholds)
        results.extend(res)
        number = pco.header.get("pco_number", pco.id)
        for r in res:
            if r.source_a is not None and r.source_a.attributes.get("kind") == "affected_code":
                missing = any(d.type is DiscrepancyType.BOM_MISSING_FOR_AFFECTED_CODE for d in r.discrepancies)
                coverage.append(CoverageFinding(kind="pco_affected_code", sku=r.sku, status="MISSING_BOM" if missing else "OK", detail=r.explanation, source=_rel(Path(pco.path), root)))
                if missing:
                    warnings.append(f"{number}: no BOM for affected code {r.sku} — BLOCKER")
        audit.append(AuditEvent(action="check.completed", detail=f"PCO_BOM {number}: {len(res)} rows against {len(boms)} BOM(s)"))
    snap = store.snapshot()
    parser_versions = {
        "bom_pdf": bom_pdf.PARSER_VERSION,
        "bom_table": bom_table.PARSER_VERSION,
        "label_pdf": label_pdf.PARSER_VERSION,
        "normalizer": NORMALIZER_VERSION,
        "categorizer_rules": CATEGORIZER_VERSION,
        "check_bom_label": CHECK_VERSION,
        "pco": pco_parser.PARSER_VERSION,
        "check_pco_bom": PCO_CHECK_VERSION,
        "drawing_pdf": drawing_pdf.PARSER_VERSION,
        "check_bom_drawing": BOM_DRAWING_VERSION,
        "check_label_drawing": LABEL_DRAWING_VERSION,
        "check_label_revision": LABEL_REVISION_VERSION,
    }
    seed = json.dumps({"inputs": sorted(i.sha256 for i in inputs), "terminology": snap.version, "thresholds": thresholds.model_dump(), "tool": __version__, "parsers": parser_versions}, sort_keys=True)
    run_id = "run-" + hashlib.sha256(seed.encode()).hexdigest()[:12]
    metadata = RunMetadata(
        run_id=run_id,
        tool_version=__version__,
        parser_versions=parser_versions,
        thresholds=thresholds,
        terminology_version=snap.version,
        terminology_count=snap.count,
        input_root=str(root),
        inputs=inputs,
        capabilities={**CAPABILITIES, "Optional AI adjudication (L5)": ("DISABLED (NullProvider; no external calls)" if isinstance(provider, NullProvider) else f"ENABLED ({provider.describe().get('provider')} / {provider.describe().get('model')}) — suggestions only, never authoritative")},
        ai_provider=provider.describe(),
    )
    usage: dict[str, int] = {}
    for r in results:
        if r.relationship_id:
            usage[r.relationship_id] = usage.get(r.relationship_id, 0) + 1
    audit.append(AuditEvent(action="run.completed", detail=f"{run_id}: {len(documents)} documents, {len(groups)} SKU sets, {len(results)} rows"))
    if not isinstance(provider, NullProvider):
        audit.append(AuditEvent(action="ai.provider", detail=f"{provider.describe()}; {getattr(extra[0], 'calls', 0)} adjudication call(s)"))
    return Run(
        metadata=metadata,
        documents=documents,
        groups=groups,
        coverage=coverage,
        results=results,
        relationships_used=sorted(usage),
        relationship_usage=usage,
        terminology_snapshot=snap.relationships,
        audit_log=audit,
        warnings=warnings,
    )


def save_run(run: Run, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_run(path: Path | str) -> Run:
    return Run.model_validate_json(Path(path).read_text(encoding="utf-8"))


def run_folder(root: Path | str, store: RelationshipStore, thresholds: Thresholds = Thresholds(), provider: AdjudicationProvider | None = None) -> Run:
    return run_checks(ingest_folder(root), store, thresholds, provider)
