"""The shared pairing engine: candidate generation, ladder matching, one-to-one assignment, quantity policy,
missing rows with hints, conditional exemptions, evidence and explanations. Every presence/identity check
(BOM ↔ Label, BOM ↔ Drawing, Label ↔ Drawing, Old ↔ New label) is this engine plus a policy."""

from dataclasses import dataclass
from decimal import Decimal

from kaizen.checks.base import CLASSIFICATION_BY_LEVEL, RECOMMENDED_ACTION, RowIdFactory
from kaizen.checks.quantity_compare import compare_quantities
from kaizen.ingest.bom_categorize import categorize
from kaizen.matching.assignment import Candidate, assign
from kaizen.matching.ladder import MatchContext, MatchLadder
from kaizen.matching.normalize import normalize
from kaizen.models import CheckResult, CheckType, Classification, Discrepancy, DiscrepancyType, Document, DocumentItem, ItemCategory, MatchLevel, Severity, Thresholds


@dataclass(frozen=True)
class CheckPolicy:
    check_type: CheckType
    row_letter: str
    quantity_relevant: bool
    missing_a: DiscrepancyType
    missing_b: DiscrepancyType
    a_label: str
    b_label: str
    conditional_b_exempt: bool = False
    missing_severity: Severity = Severity.MAJOR
    soft_a_categories: tuple[ItemCategory, ...] = ()  # unmatched A items of these categories are not findings
    exempt_b_categories: tuple[ItemCategory, ...] = ()  # unmatched B items whose text categorises like these are not findings


def disc(dtype: DiscrepancyType, severity: Severity, detail: str) -> Discrepancy:
    return Discrepancy(type=dtype, severity=severity, detail=detail, recommended_action=RECOMMENDED_ACTION.get(dtype, ""))


def merge_duplicate_items(items: list[DocumentItem]) -> list[DocumentItem]:
    """Rows sharing an item number are merged (quantities summed, every source row kept in the evidence)."""
    by_item: dict[str, list[DocumentItem]] = {}
    order: list[str] = []
    for it in items:
        key = it.item_number or it.id
        if key not in by_item:
            order.append(key)
        by_item.setdefault(key, []).append(it)
    merged: list[DocumentItem] = []
    for key in order:
        rows = by_item[key]
        if len(rows) == 1:
            merged.append(rows[0])
            continue
        first = rows[0]
        qty = sum((r.quantity for r in rows), Decimal(0)) if all(r.quantity is not None for r in rows) else None
        locators = [r.evidence.locator or f"row {r.evidence.line_index}" for r in rows]
        merged.append(
            first.model_copy(
                update={
                    "quantity": qty,
                    "attributes": {**first.attributes, "merged_rows": len(rows), "merged_locators": locators, "merged_quantities": [str(r.quantity) for r in rows]},
                    "extraction_confidence": min(r.extraction_confidence for r in rows),
                    "evidence": first.evidence.model_copy(update={"raw_text": " | ".join(r.evidence.raw_text for r in rows), "locator": " + ".join(locators)}),
                }
            )
        )
    return merged


def merge_note(a: DocumentItem) -> str:
    n = a.attributes.get("merged_rows", 1)
    if n <= 1:
        return ""
    return f"merged {n} BOM rows for item {a.item_number} (quantities {' + '.join(a.attributes.get('merged_quantities', []))}; {a.evidence.locator}); "


def _ident(item: DocumentItem) -> str:
    return f"{item.item_number} '{item.description}'" if item.item_number else f"'{item.description}'"


def _q(q: Decimal | None) -> str:
    return "?" if q is None else format(q.normalize(), "f")


def _hint(c: Candidate | None, other_desc: str, other_label: str) -> str:
    if c is None:
        return f"no {other_label} scored above the candidate floor"
    o = c.outcome
    qual = "numeric tokens disagree" if o.numeric_conflict else "weak" if o.weak else "candidate already used"
    return f"closest {other_label}: '{other_desc}' (score {o.score:.2f}, {qual})"


def run_pairing_check(
    a_doc: Document,
    a_items: list[DocumentItem],
    b_doc: Document,
    b_items: list[DocumentItem],
    policy: CheckPolicy,
    ladder: MatchLadder,
    thresholds: Thresholds,
    sku: str,
    ids: RowIdFactory | None = None,
) -> list[CheckResult]:
    ids = ids or RowIdFactory(sku, policy.row_letter)
    na = [normalize(i.description) for i in a_items]
    nb = [normalize(i.description) for i in b_items]
    ctx = lambda i: MatchContext(sku=sku, doc_types=(a_doc.doc_type, b_doc.doc_type), item_number=a_items[i].item_number)  # noqa: E731
    asg = assign(na, nb, ladder, ctx, thresholds)
    pair_by_a = {p.a_index: p for p in asg.pairs}
    results: list[CheckResult] = []
    for i, a in enumerate(a_items):
        p = pair_by_a.get(i)
        if p is None:
            results.append(_missing_a_row(a, asg.hints_a.get(i), asg.ambiguous_a.get(i, []), b_items, policy, sku, ids, na[i]))
            continue
        results.append(_pair_row(a, b_items[p.b_index], p, asg.ambiguous_a.get(i, []), b_items, policy, thresholds, sku, ids, na[i], nb[p.b_index]))
    for j in asg.unmatched_b:
        results.append(_missing_b_row(b_items[j], asg.hints_b.get(j), a_items, policy, sku, ids, nb[j]))
    return results


def _pair_row(a, b, p: Candidate, alternatives: list[Candidate], b_items, policy: CheckPolicy, thresholds: Thresholds, sku, ids, norm_a, norm_b) -> CheckResult:
    out = p.outcome
    classification = CLASSIFICATION_BY_LEVEL[out.level]
    if out.needs_confirmation and classification is not Classification.MISMATCH:
        classification = Classification.POTENTIAL
    discrepancies: list[Discrepancy] = []
    qty_text = ""
    if policy.quantity_relevant:
        verdict = compare_quantities(a.quantity, b.quantity, b.sub_quantity, a.uom, b.uom)
        qty_text = f"; quantity: {verdict.detail}"
        if not verdict.equal:
            if classification in (Classification.EXACT, Classification.EQUIVALENT) and not verdict.explainable_by_idiom:
                classification = Classification.MISMATCH
                discrepancies.append(disc(DiscrepancyType.QTY_MISMATCH, Severity.MAJOR, verdict.detail))
            elif verdict.explainable_by_idiom:
                classification = Classification.POTENTIAL
                discrepancies.append(disc(DiscrepancyType.QTY_MISMATCH, Severity.MINOR, verdict.detail))
            else:
                discrepancies.append(disc(DiscrepancyType.QTY_MISMATCH, Severity.MINOR, f"if this pairing is confirmed, quantities differ: {verdict.detail}"))
    if alternatives:
        if classification is not Classification.MISMATCH:
            classification = Classification.POTENTIAL
        alts = "; ".join(f"'{b_items[c.b_index].description}' (score {c.outcome.score:.2f})" for c in alternatives)
        discrepancies.append(disc(DiscrepancyType.AMBIGUOUS_MATCH, Severity.MAJOR, f"more than one {policy.b_label} fits this {policy.a_label}: {alts}"))
    low = [x for x in (a, b) if x.extraction_confidence < thresholds.low_confidence]
    if low:
        who = " and ".join(f"{x.doc_type.value.lower()} ({x.extraction_confidence:.2f})" for x in low)
        discrepancies.append(disc(DiscrepancyType.LOW_EXTRACTION_CONFIDENCE, Severity.INFO, f"extraction confidence below {thresholds.low_confidence:.2f} for {who}"))
    requires = classification in (Classification.POTENTIAL, Classification.MISMATCH, Classification.MISSING) or bool(discrepancies)
    return CheckResult(
        row_id=ids.next(), sku=sku, check=policy.check_type, source_a=a, source_b=b, normalized_a=norm_a.normalized, normalized_b=norm_b.normalized,
        classification=classification, match_level=out.level, score=out.score, candidate_score=out.candidate_score, relationship_id=out.relationship_id,
        explanation=f"{merge_note(a)}{out.reason}{qty_text}", discrepancies=discrepancies, requires_validation=requires,
    )


def _missing_a_row(a, hint: Candidate | None, ambiguous: list[Candidate], b_items, policy: CheckPolicy, sku, ids, norm_a) -> CheckResult:
    if a.category in policy.soft_a_categories:
        detail = f"{a.category.value.lower()} line {_ident(a)} has no {policy.b_label}; {a.category.value.lower()} is not required on this document type"
        return CheckResult(row_id=ids.next(), sku=sku, check=policy.check_type, role="exempt", source_a=a, source_b=None, normalized_a=norm_a.normalized, classification=Classification.EXACT, match_level=MatchLevel.NONE, score=0.0, explanation=f"NOT REQUIRED: {detail}", requires_validation=False)
    hint_desc = b_items[hint.b_index].description if hint else ""
    qty = f" (qty {_q(a.quantity)})" if policy.quantity_relevant else ""
    detail = f"{policy.a_label} {_ident(a)}{qty} has no matching {policy.b_label}; {_hint(hint, hint_desc, policy.b_label)}"
    discrepancies = [disc(policy.missing_a, policy.missing_severity, detail)]
    for c in ambiguous:
        discrepancies.append(disc(DiscrepancyType.AMBIGUOUS_MATCH, Severity.MAJOR, f"'{b_items[c.b_index].description}' (score {c.outcome.score:.2f}): {c.note}"))
    if a.extraction_confidence < 0.7:
        discrepancies.append(disc(DiscrepancyType.LOW_EXTRACTION_CONFIDENCE, Severity.INFO, f"{a.doc_type.value.lower()} extraction confidence {a.extraction_confidence:.2f}"))
    return CheckResult(
        row_id=ids.next(), sku=sku, check=policy.check_type, source_a=a, source_b=None, normalized_a=norm_a.normalized, normalized_b=None,
        classification=Classification.MISSING, match_level=MatchLevel.NONE, score=hint.outcome.score if hint else 0.0,
        explanation=f"{merge_note(a)}MISSING: {detail}", discrepancies=discrepancies, requires_validation=True,
    )


def _missing_b_row(b, hint: Candidate | None, a_items, policy: CheckPolicy, sku, ids, norm_b) -> CheckResult:
    if policy.conditional_b_exempt and b.attributes.get("conditional"):
        detail = f"conditional {policy.b_label} '{b.description}' (IF APPLICABLE PER BOM) has no matching {policy.a_label} — not required for this SKU"
        return CheckResult(row_id=ids.next(), sku=sku, check=policy.check_type, role="exempt", source_a=None, source_b=b, normalized_a=None, normalized_b=norm_b.normalized, classification=Classification.EXACT, match_level=MatchLevel.NONE, score=0.0, explanation=f"CONDITIONAL: {detail}", requires_validation=False)
    if policy.exempt_b_categories:
        cat, reason = categorize(None, b.description, None)
        if cat in policy.exempt_b_categories:
            detail = f"{policy.b_label} '{b.description}' is {cat.value.lower()} ({reason}); not expected as a {policy.a_label}"
            return CheckResult(row_id=ids.next(), sku=sku, check=policy.check_type, role="exempt", source_a=None, source_b=b, normalized_a=None, normalized_b=norm_b.normalized, classification=Classification.EXACT, match_level=MatchLevel.NONE, score=0.0, explanation=f"NOT REQUIRED: {detail}", requires_validation=False)
    hint_desc = a_items[hint.a_index].description if hint else ""
    qty = f" (qty {_q(b.quantity)})" if policy.quantity_relevant else ""
    detail = f"{policy.b_label} {_ident(b)}{qty} could not be mapped to any {policy.a_label}; {_hint(hint, hint_desc, policy.a_label)}"
    discrepancies = [disc(policy.missing_b, policy.missing_severity, detail)]
    if b.extraction_confidence < 0.7:
        discrepancies.append(disc(DiscrepancyType.LOW_EXTRACTION_CONFIDENCE, Severity.INFO, f"{b.doc_type.value.lower()} extraction confidence {b.extraction_confidence:.2f}"))
    return CheckResult(
        row_id=ids.next(), sku=sku, check=policy.check_type, source_a=None, source_b=b, normalized_a=None, normalized_b=norm_b.normalized,
        classification=Classification.MISSING, match_level=MatchLevel.NONE, score=hint.outcome.score if hint else 0.0,
        explanation=f"MISSING: {detail}", discrepancies=discrepancies, requires_validation=True,
    )
