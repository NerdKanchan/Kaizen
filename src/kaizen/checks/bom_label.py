"""Check 1: BOM ↔ Label — the shared pairing engine with the quantity policy, plus a REF/parent row and a
single BLOCKER when the label's contents could not be extracted. Non-physical BOM lines are never compared."""

from kaizen.checks.base import RowIdFactory, header_item, pair_token
from kaizen.checks.pairing import CheckPolicy, disc, merge_duplicate_items, run_pairing_check
from kaizen.ingest.grouping import identity_key
from kaizen.matching.ladder import MatchLadder
from kaizen.models import CheckResult, CheckType, Classification, DiscrepancyType, Document, DocumentItem, ItemCategory, MatchLevel, Severity, Thresholds

CHECK_VERSION = "2"
POLICY = CheckPolicy(check_type=CheckType.BOM_LABEL, row_letter="R", quantity_relevant=True, missing_a=DiscrepancyType.MISSING_IN_LABEL, missing_b=DiscrepancyType.MISSING_IN_BOM, a_label="BOM component", b_label="label line")


def is_comparable_bom_item(item: DocumentItem) -> tuple[bool, str]:
    if item.category is not ItemCategory.PHYSICAL_COMPONENT:
        return False, f"category {item.category.value}: {item.category_reason}"
    if item.quantity is None:
        return True, "quantity unreadable; compared so the reviewer sees it"
    if item.quantity <= 0:
        return False, "zero quantity"
    if not item.is_active:
        return False, f"inactive (effective {item.attributes.get('effective_from', '?')} to {item.attributes.get('effective_thru', '?')})"
    return True, "physical component with positive quantity"


def comparable_bom_items(bom: Document) -> list[DocumentItem]:
    return merge_duplicate_items([i for i in bom.items if is_comparable_bom_item(i)[0]])


def run_bom_label_check(bom: Document, label: Document, ladder: MatchLadder, thresholds: Thresholds) -> list[CheckResult]:
    sku = bom.sku or label.sku or "UNKNOWN"
    ids = RowIdFactory(sku, "R", pair_token(bom.id, label.id))
    results = [_ref_row(bom, label, sku, ids)]
    results.extend(_exempt_rows(bom, sku, ids))
    bom_items = comparable_bom_items(bom)
    if not label.items:
        results.append(_label_unreadable_row(label, len(bom_items), sku, ids))
        return results
    results.extend(run_pairing_check(bom, bom_items, label, list(label.items), POLICY, ladder, thresholds, sku, ids))
    return results


def _exempt_rows(bom: Document, sku: str, ids: RowIdFactory) -> list[CheckResult]:
    """Every BOM line excluded from the comparison is shown, with its reason, so exclusions are never silent."""
    out = []
    for item in bom.items:
        ok, reason = is_comparable_bom_item(item)
        if ok:
            continue
        out.append(CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_LABEL, role="exempt", source_a=item, source_b=None, classification=Classification.EXACT, match_level=MatchLevel.NONE, score=0.0, explanation=f"NOT COMPARED: {item.item_number} '{item.description}' — {reason}", requires_validation=False))
    return out


def _ref_row(bom: Document, label: Document, sku: str, ids: RowIdFactory) -> CheckResult:
    a, b = header_item(bom, "BOM parent"), header_item(label, "label REF")
    parent, ref = bom.sku, label.sku
    if parent and ref and identity_key(parent) == identity_key(ref):
        if label.header.get("ref_confidence") == "inferred":
            detail = f"label REF {ref} was inferred from the paired BOM; verify it belongs to BOM parent item {parent}"
            return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_LABEL, role="header", source_a=a, source_b=b, normalized_a=parent, normalized_b=ref, classification=Classification.POTENTIAL, match_level=MatchLevel.NONE, score=0.0, explanation=detail, discrepancies=[disc(DiscrepancyType.REF_PARENT_MISMATCH, Severity.MAJOR, detail)], requires_validation=True)
        return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_LABEL, role="header", source_a=a, source_b=b, normalized_a=parent, normalized_b=ref, classification=Classification.EXACT, match_level=MatchLevel.EXACT, score=1.0, explanation=f"REF {ref} on the label is the product family of BOM parent item {parent}")
    if parent and ref:
        detail = f"label REF {ref} (identity {identity_key(ref)}) does not match BOM parent item {parent} (identity {identity_key(parent)})"
        cls = Classification.MISMATCH
    else:
        missing = "BOM parent item" if not parent else "label REF"
        detail = f"{missing} could not be extracted, so the label cannot be tied to the SKU"
        cls = Classification.MISSING
    return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_LABEL, role="header", source_a=a, source_b=b, normalized_a=parent, normalized_b=ref, classification=cls, match_level=MatchLevel.NONE, score=0.0, explanation=detail, discrepancies=[disc(DiscrepancyType.REF_PARENT_MISMATCH, Severity.BLOCKER, detail)], requires_validation=True)


def _label_unreadable_row(label: Document, n_components: int, sku: str, ids: RowIdFactory) -> CheckResult:
    detail = f"no kit-contents lines were extracted from the label ({label.path}); {n_components} comparable BOM components could not be checked and are deliberately not listed as MISSING one by one"
    return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_LABEL, role="header", source_a=None, source_b=header_item(label, "label"), classification=Classification.MISSING, match_level=MatchLevel.NONE, score=0.0, explanation=f"LABEL NOT EXTRACTED: {detail}", discrepancies=[disc(DiscrepancyType.LOW_EXTRACTION_CONFIDENCE, Severity.BLOCKER, detail + "; " + ("; ".join(label.warnings) or "no parser warnings"))], requires_validation=True)
