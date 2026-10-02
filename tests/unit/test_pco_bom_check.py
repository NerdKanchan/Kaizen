from decimal import Decimal

from kaizen.checks.pco_bom import run_pco_bom_check
from kaizen.matching.ladder import MatchLadder
from kaizen.models import CheckType, Classification, DiscrepancyType, DocType, Document, DocumentItem, Evidence, ItemCategory, Severity, Thresholds
from kaizen.terminology.store import RelationshipStore
from tests.unit.test_bom_label_check import SHA, bom_doc

TH = Thresholds()


def test_applied_pco_change_with_low_confidence_bom_still_needs_review():
    pco = pco_doc(["A"], [("ADD", "", "RM0737876", "CATHETER TRIMMING DEVICE", "1", "")])
    bom = bom_doc([("RM0737876", "CATHETER TRIMMING DEVICE", "1")], parent="A")
    bom.items[0].extraction_confidence = 0.3
    row = by_key(run(pco, [bom]))[("A", "ADD:RM0737876")]
    assert row.requires_validation
    assert any(d.type is DiscrepancyType.LOW_EXTRACTION_CONFIDENCE for d in row.discrepancies)


def pco_doc(codes, rows, number="PCO34590"):
    items = []
    for n, code in enumerate(codes, start=1):
        items.append(DocumentItem(id=f"pco:1:code{n}", doc_id="pco:1", doc_type=DocType.PCO, item_number=code, description=f"affected code {code}", category=ItemCategory.ADMINISTRATIVE, category_reason="pco", attributes={"kind": "affected_code"}, evidence=Evidence(file="pco/pco.xlsx", file_sha256=SHA, raw_text=code, locator=f"sheet 'PCO', row {n + 10}")))
    for n, (kind, actual, proposed, desc, qty, seq) in enumerate(rows, start=1):
        items.append(
            DocumentItem(
                id=f"pco:1:chg{n}", doc_id="pco:1", doc_type=DocType.PCO, item_number=proposed or actual, description=desc, quantity=Decimal(qty) if qty else None, oper_seq=seq or None,
                category=ItemCategory.ADMINISTRATIVE, category_reason="pco change",
                attributes={"kind": "change", "change_kind": kind, "item_actual": actual, "item_proposed": proposed, "qty_actual": "", "qty_proposed": qty, "seq_actual": "", "seq_proposed": seq},
                evidence=Evidence(file="pco/pco.xlsx", file_sha256=SHA, raw_text=f"{actual} {proposed} {desc}", locator=f"sheet 'PCO', row {n + 20}"),
            )
        )
    return Document(id="pco:1", doc_type=DocType.PCO, path="pco/pco.xlsx", sha256=SHA, sku=None, header={"pco_number": number, "affected_codes": list(codes)}, items=items, parser_name="t", parser_version="1")


def run(pco, boms):
    return run_pco_bom_check(pco, boms, MatchLadder(RelationshipStore.default(), TH), TH)


def by_key(results):
    return {(r.sku, r.source_a.attributes.get("change_key")): r for r in results if r.source_a is not None and r.source_a.attributes.get("kind") == "change"}


def test_delete_applied_and_not_applied():
    pco = pco_doc(["1295108NS", "1395108QNS"], [("DELETE", "RM5002565", "", "SCISSORS WITH PROTECTOR TUBING", "", "")])
    applied = bom_doc([("0396447", "ABSORBENT TOWEL", "1")], parent="1295108NS")
    not_applied = bom_doc([("RM5002565", "SCISSORS WITH PROTECTOR TUBING", "1")], parent="1395108QNS")
    res = by_key(run(pco, [applied, not_applied]))
    ok = res[("1295108NS", "DELETE:RM5002565")]
    assert ok.classification is Classification.EXACT and ok.discrepancies == [] and ok.check is CheckType.PCO_BOM
    bad = res[("1395108QNS", "DELETE:RM5002565")]
    assert bad.classification is Classification.MISMATCH
    assert bad.discrepancies[0].type is DiscrepancyType.PCO_CHANGE_NOT_APPLIED and bad.discrepancies[0].severity is Severity.MAJOR
    assert bad.source_b is not None and bad.source_b.item_number == "RM5002565"  # evidence: the BOM row that should be gone


def test_add_applied_missing_and_qty_seq_mismatch():
    pco = pco_doc(["A", "B", "C"], [("ADD", "", "RM0737876", "CATHETER TRIMMING DEVICE", "1", "7")])
    good = bom_doc([("RM0737876", "CATHETER TRIMMING DEVICE", "1")], parent="A")
    good.items[0].oper_seq = "7.00"
    missing = bom_doc([("0396447", "ABSORBENT TOWEL", "1")], parent="B")
    wrong = bom_doc([("RM0737876", "CATHETER TRIMMING DEVICE", "2")], parent="C")
    wrong.items[0].oper_seq = "9.00"
    res = by_key(run(pco, [good, missing, wrong]))
    assert res[("A", "ADD:RM0737876")].classification is Classification.EXACT
    assert res[("B", "ADD:RM0737876")].discrepancies[0].type is DiscrepancyType.PCO_CHANGE_NOT_APPLIED
    w = res[("C", "ADD:RM0737876")]
    assert w.classification is Classification.MISMATCH
    assert w.discrepancies[0].type is DiscrepancyType.PCO_QTY_SEQ_MISMATCH
    assert "2" in w.discrepancies[0].detail and "9" in w.discrepancies[0].detail


def test_substitute_and_modify():
    pco = pco_doc(["A", "B"], [("SUBSTITUTE", "0396447", "0396448", "ABSORBENT TOWEL LARGE", "1", "7"), ("MODIFY", "2260001", "2260001", "END CAP", "3", "7")])
    a = bom_doc([("0396448", "ABSORBENT TOWEL LARGE", "1"), ("2260001", "END CAP", "3")], parent="A")
    for i in a.items:
        i.oper_seq = "7.00"
    b = bom_doc([("0396447", "ABSORBENT TOWEL", "1"), ("0396448", "ABSORBENT TOWEL LARGE", "1"), ("2260001", "END CAP", "2")], parent="B")
    for i in b.items:
        i.oper_seq = "7.00"
    res = by_key(run(pco, [a, b]))
    assert res[("A", "SUBSTITUTE:0396447>0396448")].classification is Classification.EXACT
    assert res[("A", "MODIFY:2260001")].classification is Classification.EXACT
    sub_b = res[("B", "SUBSTITUTE:0396447>0396448")]
    assert sub_b.classification is Classification.MISMATCH and sub_b.discrepancies[0].type is DiscrepancyType.PCO_CHANGE_NOT_APPLIED
    assert "0396447" in sub_b.discrepancies[0].detail and "still present" in sub_b.discrepancies[0].detail
    mod_b = res[("B", "MODIFY:2260001")]
    assert mod_b.discrepancies[0].type is DiscrepancyType.PCO_QTY_SEQ_MISMATCH


def test_redline_annotation_counts_as_applied_with_note():
    pco = pco_doc(["A"], [("SUBSTITUTE", "PK0726442", "PK0722294", "CASE LABEL, BLANK", "0.4", "5")])
    bom = bom_doc([("PK0726442", "CASE LABEL, BLANK", "0.4", ItemCategory.LABEL)], parent="A")
    bom.items[0].oper_seq = "5.00"
    bom.items[0].attributes["redlines"] = [{"field": "component_item", "text": "PK0722294"}]
    r = by_key(run(pco, [bom]))[("A", "SUBSTITUTE:PK0726442>PK0722294")]
    assert r.classification is Classification.POTENTIAL
    assert "redline" in r.explanation.lower()
    assert r.requires_validation is True


def test_coverage_missing_bom_for_affected_code_is_a_blocker_row():
    pco = pco_doc(["1295108NS", "1495108NS"], [("DELETE", "RM5002565", "", "SCISSORS", "", "")])
    results = run(pco, [bom_doc([("0396447", "ABSORBENT TOWEL", "1")], parent="1295108NS")])
    cov = [r for r in results if r.source_a is not None and r.source_a.attributes.get("kind") == "affected_code"]
    assert len(cov) == 2
    missing = next(r for r in cov if r.sku == "1495108NS")
    assert missing.classification is Classification.MISSING
    assert missing.discrepancies[0].type is DiscrepancyType.BOM_MISSING_FOR_AFFECTED_CODE and missing.discrepancies[0].severity is Severity.BLOCKER
    present = next(r for r in cov if r.sku == "1295108NS")
    assert present.classification is Classification.EXACT
    assert results.index(missing) < min(results.index(r) for r in results if r.source_a.attributes.get("kind") == "change")
    assert not any(r.sku == "1495108NS" for r in results if r.source_a.attributes.get("kind") == "change")


def test_description_disagreement_is_noted_as_minor():
    pco = pco_doc(["A"], [("ADD", "", "RM0737876", "CATH TRIM DEVICE ASSY", "1", "7")])
    bom = bom_doc([("RM0737876", "SCISSORS CURVED", "1")], parent="A")
    bom.items[0].oper_seq = "7.00"
    r = by_key(run(pco, [bom]))[("A", "ADD:RM0737876")]
    assert r.classification is Classification.EXACT  # the change itself is applied (item, qty, seq)
    assert any(d.type is DiscrepancyType.DESC_MISMATCH and d.severity is Severity.MINOR for d in r.discrepancies)
    assert r.requires_validation is True


def test_row_ids_and_explanations():
    pco = pco_doc(["A"], [("DELETE", "X1", "", "THING", "", ""), ("ADD", "", "Y1", "OTHER", "1", "7")])
    results = run(pco, [bom_doc([("Y1", "OTHER", "1")], parent="A")])
    assert all(r.explanation.strip() for r in results)
    ids = [r.row_id for r in results]
    assert len(ids) == len(set(ids)) and all(i.startswith("P-PCO34590-") for i in ids)
