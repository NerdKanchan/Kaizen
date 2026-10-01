"""Check 5: Old ↔ New label — a semantic change report, not a visual diff.

Lines of the two revisions are paired with the shared ladder; each difference (added, removed, description
changed, quantity changed, REF changed) is classified EXPECTED when a PCO-derived expectation explains it,
otherwise UNEXPECTED_LABEL_CHANGE. Expectations that nothing on the new label satisfies are
EXPECTED_CHANGE_ABSENT. Unchanged lines are auto-cleared."""

from dataclasses import dataclass, replace
from decimal import Decimal

from kaizen.checks.base import RowIdFactory, header_item, pair_token
from kaizen.checks.pairing import disc
from kaizen.ingest.bom_categorize import categorize
from kaizen.ingest.quantity import parse_decimal
from kaizen.matching.assignment import assign
from kaizen.matching.ladder import MatchContext, MatchLadder
from kaizen.matching.normalize import normalize
from kaizen.models import CheckResult, CheckType, Classification, DiscrepancyType, DocType, Document, DocumentItem, ItemCategory, MatchLevel, Severity, Thresholds

CHECK_VERSION = "1"


@dataclass
class ExpectedChange:
    kind: str  # ADD | REMOVE | SUBSTITUTE | QTY
    description: str
    quantity: str | None = None
    old_description: str | None = None
    source: str = ""
    source_item: DocumentItem | None = None
    consumed: bool = False

    @property
    def key(self) -> str:
        return f"{self.kind}:{normalize(self.description).normalized}"


def expected_changes_from_pcos(pcos: list[Document], sku: str, boms: list[Document] | None = None) -> list[ExpectedChange]:
    """PCO change rows that should be visible on a product label (physical components only). For substitutions
    the outgoing item's wording is looked up on the BOM (the PCO only names the incoming item)."""
    out: list[ExpectedChange] = []

    def bom_description(item_number: str) -> str | None:
        for doc in sorted(boms or [], key=lambda d: 0 if d.sku == sku else 1):
            for it in doc.items:
                if it.item_number == item_number and it.description:
                    return it.description
        return None
    for pco in pcos:
        if sku not in (pco.header.get("affected_codes") or []):
            continue
        number = pco.header.get("pco_number", pco.id)
        for chg in pco.items:
            if chg.attributes.get("kind") != "change":
                continue
            kind = chg.attributes.get("change_kind")
            qty = chg.attributes.get("qty_proposed") or None
            q = parse_decimal(qty)
            if categorize(chg.item_number, chg.description or "", q)[0] is not ItemCategory.PHYSICAL_COMPONENT:
                continue
            src = f"{number} {chg.attributes.get('change_key', kind)}"
            if kind == "DELETE":
                out.append(ExpectedChange("REMOVE", chg.description, source=src, source_item=chg))
            elif kind == "ADD":
                out.append(ExpectedChange("ADD", chg.description, quantity=qty, source=src, source_item=chg))
            elif kind == "SUBSTITUTE":
                out.append(ExpectedChange("SUBSTITUTE", chg.description, quantity=qty, old_description=bom_description(chg.attributes.get("item_actual", "")), source=src, source_item=chg))
            elif kind == "MODIFY":
                out.append(ExpectedChange("QTY", chg.description, quantity=qty, source=src, source_item=chg))
    return out


def _q(q: Decimal | None) -> str:
    return "?" if q is None else format(q.normalize(), "f")


def _same_qty(a: Decimal | None, b: str | Decimal | None) -> bool:
    if a is None or b is None:
        return False
    value = parse_decimal(str(b))
    return a.is_finite() and value is not None and a == value


class _Matcher:
    def __init__(self, ladder: MatchLadder, sku: str):
        self.ladder, self.sku = ladder, sku

    def strict(self, description: str | None, item: DocumentItem | None) -> bool:
        return self.fits(description, item, strict=True)

    def fits(self, description: str | None, item: DocumentItem | None, strict: bool = False) -> bool:
        """Does a PCO description fit a label line? `strict` (used to declare an expectation already satisfied
        without a visible change) accepts exact and relationship matches only — a fuzzy resemblance must not
        silently mark a substitution as applied."""
        if not description or item is None:
            return False
        out = self.ladder.match(description, item.description, MatchContext(sku=self.sku, doc_types=(DocType.PCO, DocType.LABEL)))
        if strict:
            return out.level in (MatchLevel.EXACT, MatchLevel.RELATIONSHIP)
        return out.assignable


def run_label_revision_check(old: Document, new: Document, expected: list[ExpectedChange], ladder: MatchLadder, thresholds: Thresholds, sku: str | None = None) -> list[CheckResult]:
    expected = [replace(e, consumed=False) for e in expected]
    sku = sku or new.sku or old.sku or "UNKNOWN"
    ids = RowIdFactory(sku, "V", pair_token(old.id, new.id))
    fit = _Matcher(ladder, sku)
    results: list[CheckResult] = [_header_row(old, new, sku, ids)]
    for doc in (old, new):
        if not doc.items or doc.header.get('unreadable_pages'):
            detail = f"Label revision extraction incomplete ({doc.path}); changes cannot be confirmed against the source. " + "; ".join(doc.warnings)
            results.append(CheckResult(row_id=ids.next(), sku=sku, check=CheckType.LABEL_REVISION, role='header', source_a=header_item(doc, 'label'), classification=Classification.MISSING, match_level=MatchLevel.NONE, score=0.0, explanation=detail, discrepancies=[disc(DiscrepancyType.LOW_EXTRACTION_CONFIDENCE, Severity.BLOCKER, detail)], requires_validation=True))
    if len(results) > 1:
        return results
    old_items, new_items = list(old.items), list(new.items)
    na = [normalize(i.description) for i in old_items]
    nb = [normalize(i.description) for i in new_items]
    asg = assign(na, nb, ladder, lambda i: MatchContext(sku=sku, doc_types=(DocType.LABEL, DocType.LABEL)), thresholds)
    pair_by_a = {p.a_index: p for p in asg.pairs}

    def mk(role, a, b, cls, explanation, discrepancies=(), level=MatchLevel.NONE, score=0.0):
        return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.LABEL_REVISION, role=role, source_a=a, source_b=b, normalized_a=normalize(a.description).normalized if a else None, normalized_b=normalize(b.description).normalized if b else None, classification=cls, match_level=level, score=score, explanation=explanation, discrepancies=list(discrepancies), requires_validation=cls is not Classification.EXACT or bool(discrepancies))

    def unexpected(detail: str):
        return disc(DiscrepancyType.UNEXPECTED_LABEL_CHANGE, Severity.MAJOR, detail)

    def confirm_note(e, strict_ok: bool) -> tuple[Classification, str]:
        return (Classification.EXACT, f"per {e.source}") if strict_ok else (Classification.POTENTIAL, f"probably per {e.source} (wording only resembles the PCO description — reviewer to confirm)")

    for i, o in enumerate(old_items):
        p = pair_by_a.get(i)
        if p is None:
            exp = next((e for e in expected if not e.consumed and ((e.kind == "REMOVE" and fit.fits(e.description, o)) or (e.kind == "SUBSTITUTE" and e.old_description and fit.fits(e.old_description, o)))), None)
            if exp is not None and exp.kind == "REMOVE":
                exp.consumed = True
                cls, note = confirm_note(exp, fit.strict(exp.description, o))
                results.append(mk("change", o, None, cls, f"EXPECTED REMOVED: '{o.description}' (qty {_q(o.quantity)}) is no longer on the new label, {note}"))
            elif exp is not None and exp.kind == "SUBSTITUTE" and any(fit.fits(exp.description, n) for n in new_items):
                cls, note = confirm_note(exp, fit.strict(exp.old_description, o))
                results.append(mk("change", o, None, cls, f"EXPECTED REMOVED for substitution: '{o.description}' replaced on the new label, {note}"))
            else:
                detail = f"REMOVED: '{o.description}' (qty {_q(o.quantity)}) is on the old label but not on the new label, and no PCO change explains it"
                results.append(mk("change", o, None, Classification.MISMATCH, detail, [unexpected(detail)]))
            continue
        n = new_items[p.b_index]
        desc_same = p.outcome.level is MatchLevel.EXACT
        qty_same = o.quantity is not None and o.quantity == n.quantity
        sub_same = o.sub_quantity == n.sub_quantity
        uom_same = (o.uom or "EACH").upper() == (n.uom or "EACH").upper()
        if desc_same and qty_same and sub_same and uom_same:
            results.append(mk("item", o, n, Classification.EXACT, f"UNCHANGED: '{n.description}' qty {_q(n.quantity)} on both revisions", level=MatchLevel.EXACT, score=1.0))
            continue
        parts: list[str] = []
        discrepancies = []
        cls = Classification.EXACT
        substitution = None
        if not desc_same:
            exp = next((e for e in expected if not e.consumed and e.kind == "SUBSTITUTE" and fit.fits(e.description, n) and (not e.old_description or fit.fits(e.old_description, o))), None)
            if exp is not None:
                substitution = exp
                exp.consumed = True
                c, note = confirm_note(exp, fit.strict(exp.description, n))
                cls = c if c is Classification.POTENTIAL else cls
                parts.append(f"EXPECTED DESCRIPTION CHANGED: '{o.description}' → '{n.description}' {note}")
                if exp.quantity is not None and not _same_qty(n.quantity, exp.quantity):
                    detail = f"Substitution quantity {_q(n.quantity)} does not match PCO quantity {exp.quantity} ({exp.source})"
                    discrepancies.append(disc(DiscrepancyType.EXPECTED_CHANGE_ABSENT, Severity.MAJOR, detail))
            else:
                detail = f"DESCRIPTION CHANGED: '{o.description}' → '{n.description}' ({p.outcome.reason}); no PCO change explains it"
                parts.append(detail)
                discrepancies.append(unexpected(detail))
        if not qty_same:
            exp = substitution if substitution is not None and _same_qty(n.quantity, substitution.quantity) else next((e for e in expected if not e.consumed and e.kind == "QTY" and fit.fits(e.description, n) and _same_qty(n.quantity, e.quantity)), None)
            if exp is not None:
                exp.consumed = True
                c, note = confirm_note(exp, fit.strict(exp.description, n))
                cls = c if c is Classification.POTENTIAL else cls
                parts.append(f"EXPECTED QUANTITY CHANGED: '{n.description}' {_q(o.quantity)} → {_q(n.quantity)} {note}")
            else:
                detail = f"QUANTITY CHANGED: '{n.description}' {_q(o.quantity)} → {_q(n.quantity)}; no PCO change explains it"
                parts.append(detail)
                discrepancies.append(unexpected(detail))
        if not sub_same:
            detail = f"SUB-QUANTITY CHANGED: '{n.description}' {o.sub_quantity.raw if o.sub_quantity else '(none)'} → {n.sub_quantity.raw if n.sub_quantity else '(none)'}; no PCO change explains it"
            parts.append(detail)
            discrepancies.append(unexpected(detail))
        if not uom_same:
            detail = f"UOM CHANGED: '{n.description}' {(o.uom or 'EACH').upper()} → {(n.uom or 'EACH').upper()}; no PCO change explains it"
            parts.append(detail)
            discrepancies.append(unexpected(detail))
        if discrepancies:
            cls = Classification.MISMATCH
        results.append(mk("change", o, n, cls, "; ".join(parts), discrepancies, level=p.outcome.level, score=p.outcome.score))

    for j in asg.unmatched_b:
        n = new_items[j]
        exp = next((e for e in expected if not e.consumed and e.kind in ("ADD", "SUBSTITUTE") and fit.fits(e.description, n)), None)
        if exp is not None:
            exp.consumed = True
            cls, note = confirm_note(exp, fit.strict(exp.description, n))
            qty_note = "" if exp.quantity is None or _same_qty(n.quantity, exp.quantity) else f" (label qty {_q(n.quantity)} vs PCO qty {exp.quantity} — reviewer to confirm)"
            if qty_note:
                cls = Classification.POTENTIAL
            results.append(mk("change", None, n, cls, f"EXPECTED ADDED: '{n.description}' (qty {_q(n.quantity)}) {note}{qty_note}"))
        else:
            detail = f"ADDED: '{n.description}' (qty {_q(n.quantity)}) is on the new label but not on the old label, and no PCO change explains it"
            results.append(mk("change", None, n, Classification.MISMATCH, detail, [unexpected(detail)]))

    for e in expected:
        if e.consumed:
            continue
        present_new = next((n for n in new_items if fit.fits(e.description, n, strict=True)), None)
        qty_applied = e.quantity is None or (present_new is not None and _same_qty(present_new.quantity, e.quantity))
        if e.kind == "ADD" and present_new is not None and qty_applied:
            results.append(mk("change", e.source_item, present_new, Classification.EXACT, f"EXPECTED ADD already present: '{present_new.description}' is on both revisions ({e.source})"))
        elif e.kind == "REMOVE" and present_new is None:
            results.append(mk("change", e.source_item, None, Classification.EXACT, f"EXPECTED REMOVE already absent: '{e.description}' is on neither revision ({e.source})"))
        elif e.kind == "QTY" and present_new is not None and _same_qty(present_new.quantity, e.quantity):
            results.append(mk("change", e.source_item, present_new, Classification.EXACT, f"EXPECTED QUANTITY already applied: '{present_new.description}' qty {_q(present_new.quantity)} ({e.source})"))
        elif e.kind == "SUBSTITUTE" and present_new is not None and qty_applied and (not e.old_description or not any(fit.fits(e.old_description, o, strict=True) for o in new_items)):
            results.append(mk("change", e.source_item, present_new, Classification.EXACT, f"EXPECTED SUBSTITUTE already applied: '{present_new.description}' on the new label ({e.source})"))
        else:
            what = {"ADD": f"'{e.description}' should have been added", "REMOVE": f"'{e.description}' should have been removed but is still on the new label", "QTY": f"'{e.description}' should show quantity {e.quantity}", "SUBSTITUTE": f"'{e.description}' should replace '{e.old_description or 'the previous item'}'"}[e.kind]
            detail = f"EXPECTED CHANGE ABSENT: {what} per {e.source}; the new label does not reflect it"
            results.append(mk("change", e.source_item, present_new if e.kind in ("REMOVE", "QTY") else header_item(new, "new label"), Classification.MISSING, detail, [disc(DiscrepancyType.EXPECTED_CHANGE_ABSENT, Severity.MAJOR, detail)]))
    return results


def _header_row(old: Document, new: Document, sku: str, ids: RowIdFactory) -> CheckResult:
    a, b = header_item(old, "old label"), header_item(new, "new label")
    if not old.sku or not new.sku:
        detail = "One or both label REF identities could not be extracted; verify the source labels."
        return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.LABEL_REVISION, role='header', source_a=a, source_b=b, classification=Classification.MISSING, match_level=MatchLevel.NONE, score=0.0, explanation=detail, discrepancies=[disc(DiscrepancyType.LOW_EXTRACTION_CONFIDENCE, Severity.BLOCKER, detail)], requires_validation=True)
    problems = []
    if (old.sku or "") != (new.sku or ""):
        problems.append(f"REF changed from {old.sku} to {new.sku}")
    if (old.header.get("product_name") or "") != (new.header.get("product_name") or ""):
        problems.append(f"product name changed from '{old.header.get('product_name', '')}' to '{new.header.get('product_name', '')}'")
    if problems:
        detail = "; ".join(problems) + "; no PCO change explains a header change"
        return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.LABEL_REVISION, role="header", source_a=a, source_b=b, normalized_a=old.sku, normalized_b=new.sku, classification=Classification.MISMATCH, match_level=MatchLevel.NONE, score=0.0, explanation=f"HEADER CHANGED: {detail}", discrepancies=[disc(DiscrepancyType.UNEXPECTED_LABEL_CHANGE, Severity.MAJOR, detail)], requires_validation=True)
    return CheckResult(row_id=ids.next(), sku=sku, check=CheckType.LABEL_REVISION, role="header", source_a=a, source_b=b, normalized_a=old.sku, normalized_b=new.sku, classification=Classification.EXACT, match_level=MatchLevel.EXACT, score=1.0, explanation=f"HEADER UNCHANGED: REF {new.sku} and product name identical on both revisions")
