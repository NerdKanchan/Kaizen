"""Check 2: BOM ↔ Packaging drawing — presence/identity only (the drawing is not a quantity source), plus a
drawing-number / revision row when the BOM references the drawing."""

import re
from collections import defaultdict

from kaizen.checks.base import RowIdFactory, header_item, pair_token, unparsed_bom_rows
from kaizen.checks.bom_label import comparable_bom_items
from kaizen.checks.pairing import CheckPolicy, disc, run_pairing_check
from kaizen.matching.ladder import MatchLadder
from kaizen.matching.normalize import normalize
from kaizen.models import CheckResult, CheckType, Classification, DiscrepancyType, DocType, Document, ItemCategory, MatchLevel, Severity, Thresholds

CHECK_VERSION = "2"
POLICY = CheckPolicy(check_type=CheckType.BOM_DRAWING, row_letter="D", quantity_relevant=False, missing_a=DiscrepancyType.MISSING_IN_DRAWING, missing_b=DiscrepancyType.EXTRA_ON_DRAWING, a_label="BOM component", b_label="drawing callout", conditional_b_exempt=True, soft_a_categories=(ItemCategory.PACKAGING,), exempt_b_categories=(ItemCategory.LABEL, ItemCategory.DOCUMENT))


def drawing_relevant_bom_items(bom: Document):
    """Physical components plus packaging lines (tray, lid): packaging is shown on a tray drawing but a BOM
    packaging line without a callout is not a finding (soft)."""
    physical = comparable_bom_items(bom)
    packaging = [i for i in bom.items if i.category is ItemCategory.PACKAGING and i.is_active and (i.quantity is None or i.quantity > 0)]
    return physical + packaging
_REV_RE = re.compile(r"\bREV\.?\s*([A-Z0-9]{1,3})\b", re.IGNORECASE)


def callouts(drawing: Document):
    # Drawings repeat the same component on multiple assembly/packing sheets. Presence
    # comparisons consume one identity while preserving every occurrence for inspection.
    groups = defaultdict(list)
    for item in drawing.items:
        if item.attributes.get("kind") == "callout":
            groups[normalize(item.description).sorted_key].append(item)
    out = []
    for occurrences in groups.values():
        first = occurrences[0]
        if len(occurrences) == 1:
            out.append(first)
        else:
            out.append(first.model_copy(update={
                "extraction_confidence": min(i.extraction_confidence for i in occurrences),
                "attributes": {**first.attributes, "conditional": all(i.attributes.get("conditional") for i in occurrences), "occurrences": [i.evidence.model_dump(mode="json") for i in occurrences]},
            }))
    return out


def extraction_blocker(doc: Document, check: CheckType, sku: str, ids: RowIdFactory) -> CheckResult:
    detail = f"{doc.doc_type.value.lower()} could not be extracted completely ({doc.path}); component presence cannot be checked reliably; " + "; ".join(doc.warnings)
    item = header_item(doc, doc.doc_type.value.lower())
    return CheckResult(row_id=ids.next(), sku=sku, check=check, role="header", source_a=item if doc.doc_type in (DocType.BOM, DocType.LABEL) else None, source_b=item if doc.doc_type is DocType.DRAWING else None, classification=Classification.MISSING, match_level=MatchLevel.NONE, score=0.0, explanation="EXTRACTION INCOMPLETE: " + detail, discrepancies=[disc(DiscrepancyType.LOW_EXTRACTION_CONFIDENCE, Severity.BLOCKER, detail)], requires_validation=True)


def reference_only_rows(rows: list[CheckResult], drawing: Document) -> list[CheckResult]:
    if drawing.header.get("reference_only"):
        for row in rows:
            if row.role == "item" and row.source_a is None and row.source_b is not None and row.classification is Classification.MISSING:
                row.classification = Classification.POTENTIAL
                row.explanation = "APPLICABILITY NOT CONFIRMED: the drawing says images are for reference and components can differ. " + row.explanation
                row.discrepancies = [d for d in row.discrepancies if d.type is not DiscrepancyType.EXTRA_ON_DRAWING] + [disc(DiscrepancyType.EXTRA_ON_DRAWING, Severity.INFO, "Confirm this illustrated component applies to this SKU before treating it as extra: " + row.source_b.description)]
    return rows


def run_bom_drawing_check(bom: Document, drawing: Document, ladder: MatchLadder, thresholds: Thresholds) -> list[CheckResult]:
    sku = bom.sku or "UNKNOWN"
    ids = RowIdFactory(sku, "D", pair_token(bom.id, drawing.id))
    results = [_reference_row(bom, drawing, sku, ids)]
    drawing_callouts = callouts(drawing)
    if not drawing_callouts or drawing.header.get("unreadable_pages"):
        results.append(extraction_blocker(drawing, CheckType.BOM_DRAWING, sku, ids))
        return results
    if not bom.items or bom.header.get("unreadable_pages"):
        results.append(extraction_blocker(bom, CheckType.BOM_DRAWING, sku, ids))
        return results
    results.extend(unparsed_bom_rows(bom, CheckType.BOM_DRAWING, sku, ids))
    results.extend(run_pairing_check(bom, drawing_relevant_bom_items(bom), drawing, drawing_callouts, POLICY, ladder, thresholds, sku, ids))
    return reference_only_rows(results, drawing)


def _reference_row(bom: Document, drawing: Document, sku: str, ids: RowIdFactory) -> CheckResult:
    number = (drawing.header.get("drawing_number") or "").upper()
    rev = str(drawing.header.get("revision") or "")
    a_hdr, b_hdr = header_item(bom, "BOM"), header_item(drawing, "drawing")
    ref_rows = [i for i in bom.items if number and (number in i.description.upper() or number == (i.attributes.get("drawing_number") or "").upper() or number == (i.item_number or "").upper())]
    if not number:
        detail = "drawing number could not be read from the title block; the drawing cannot be tied to the BOM"
        return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_DRAWING, role="reference", source_a=a_hdr, source_b=b_hdr, classification=Classification.MISSING, match_level=MatchLevel.NONE, score=0.0, explanation=detail, discrepancies=[disc(DiscrepancyType.DRAWING_REV_MISMATCH, Severity.MAJOR, detail)], requires_validation=True)
    if not ref_rows:
        return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_DRAWING, role="reference", source_a=a_hdr, source_b=b_hdr, normalized_a=None, normalized_b=f"{number} REV {rev}", classification=Classification.POTENTIAL, match_level=MatchLevel.NONE, score=0.0, explanation=f"drawing {number} rev {rev} ({drawing.header.get('title', '')}); no BOM line references this drawing number — confirm the drawing applies to {sku}", requires_validation=True)
    row = ref_rows[0]
    m = _REV_RE.search(row.description)
    bom_rev = m.group(1) if m else ""
    uncertain_revision = drawing.header.get("revision_confidence", 1.0) < 0.7 or b_hdr.extraction_confidence < 0.7
    if uncertain_revision:
        detail = f"BOM line {row.item_number} references {number}; drawing number/revision OCR has low confidence — verify the title block before judging revision {rev or 'unreadable'} against {bom_rev or 'unstated'}"
        return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_DRAWING, role="reference", source_a=row, source_b=b_hdr, classification=Classification.POTENTIAL, match_level=MatchLevel.NONE, score=0.0, explanation=detail, discrepancies=[disc(DiscrepancyType.LOW_EXTRACTION_CONFIDENCE, Severity.MAJOR, detail)], requires_validation=True)
    if not rev:
        detail = f"BOM line references {number}, but the drawing revision could not be read — verify the released revision"
        return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_DRAWING, role="reference", source_a=row, source_b=b_hdr, classification=Classification.POTENTIAL, match_level=MatchLevel.NONE, score=0.0, explanation=detail, requires_validation=True)
    if bom_rev and rev and bom_rev.upper() != rev.upper():
        detail = f"BOM line {row.item_number} references {number} REV {bom_rev} but the drawing is REV {rev}"
        return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_DRAWING, role="reference", source_a=row, source_b=b_hdr, normalized_a=f"{number} REV {bom_rev}", normalized_b=f"{number} REV {rev}", classification=Classification.MISMATCH, match_level=MatchLevel.NONE, score=0.0, explanation=detail, discrepancies=[disc(DiscrepancyType.DRAWING_REV_MISMATCH, Severity.MAJOR, detail)], requires_validation=True)
    rev_note = f"REV {rev}" if bom_rev else f"(BOM line does not state a revision; drawing is REV {rev})"
    return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_DRAWING, role="reference", source_a=row, source_b=b_hdr, normalized_a=f"{number} REV {bom_rev}", normalized_b=f"{number} REV {rev}", classification=Classification.EXACT, match_level=MatchLevel.EXACT, score=1.0, explanation=f"BOM line {row.item_number} references drawing {number} {rev_note}", requires_validation=not bom_rev)
