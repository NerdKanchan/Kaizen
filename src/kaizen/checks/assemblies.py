"""Apply independently verified component membership with explicit per-unit allocations."""

from decimal import Decimal

from kaizen.checks.pairing import disc
from kaizen.matching.normalize import normalize
from kaizen.models import CheckResult, CheckType, Classification, DiscrepancyType, MatchLevel, Severity


def apply_assemblies(a_items, b_items, rules, sku, ids, thresholds):
    claimed_a, claimed_b, results = set(), set(), []
    # Conflicting/overlapping rules never choose a winner silently.
    proposals = []
    for rule in rules:
        if rule["sku"] != sku:
            continue
        labels = [b for b in b_items if normalize(b.description).sorted_key == rule["label_key"]]
        members = []
        missing = []
        for member in rule["members"]:
            hits = [a for a in a_items if a.item_number == member["item_number"] and normalize(a.description).sorted_key == member["description_key"]]
            if len(hits) != 1:
                missing.append(member['item_number'])
            else:
                members.append((hits[0], Decimal(str(member["quantity_per_unit"]))))
        if len(labels) == 1:
            proposals.append((rule, members, labels[0], missing))
    for rule, members, label, missing in proposals:
        member_ids = {a.id for a, _ in members}
        overlap = any(other is not rule and (label.id == other_label.id or member_ids & {a.id for a, _ in other_members}) for other, other_members, other_label, _ in proposals)
        if overlap or member_ids & claimed_a or label.id in claimed_b:
            continue
        for component, per_unit in members:
            expected = label.quantity * per_unit if label.quantity is not None else None
            equal = expected is not None and component.quantity == expected
            differences = []
            cls = Classification.EQUIVALENT if equal else Classification.MISMATCH
            if missing and equal:
                cls = Classification.POTENTIAL
                differences.append(disc(DiscrepancyType.MISSING_IN_BOM, Severity.MAJOR, f"Verified assembly members absent or changed: {', '.join(missing)}."))
            if not equal:
                differences.append(disc(DiscrepancyType.QTY_MISMATCH, Severity.MAJOR, f"Assembly member requires {per_unit} per label unit: BOM {component.quantity}, expected {expected}."))
            if min(component.extraction_confidence, label.extraction_confidence) < thresholds.low_confidence:
                differences.append(disc(DiscrepancyType.LOW_EXTRACTION_CONFIDENCE, Severity.INFO, "Assembly source extraction needs review."))
            results.append(CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_LABEL,
                source_a=component.model_copy(update={"attributes": {**component.attributes, "assembly_rule": rule["id"], "assembly_quantity_per_unit": str(per_unit), "assembly_member_ids": sorted(member_ids)}}),
                source_b=label, classification=cls, match_level=MatchLevel.RELATIONSHIP, score=1.0,
                explanation=f"Verified assembly {rule['id']}: '{label.description}' includes item {component.item_number}; allocation {per_unit} per label unit. BOM quantity {component.quantity}, required {expected}.",
                discrepancies=differences, requires_validation=bool(differences)))
        if missing:
            detail = f"Verified assembly {rule['id']} requires BOM members {', '.join(missing)}; these items are absent or their descriptions changed."
            results.append(CheckResult(row_id=ids.next(), sku=sku, check=CheckType.BOM_LABEL, source_b=label,
                classification=Classification.MISSING, match_level=MatchLevel.NONE, explanation=detail,
                discrepancies=[disc(DiscrepancyType.MISSING_IN_BOM, Severity.MAJOR, detail)], requires_validation=True))
        claimed_a.update(member_ids)
        claimed_b.add(label.id)
    return [a for a in a_items if a.id not in claimed_a], [b for b in b_items if b.id not in claimed_b], results
