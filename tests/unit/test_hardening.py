"""Phase-1 hardening: can the engine tell SIMILAR from EQUIVALENT, and does it survive real-world nuisances?"""


from kaizen.checks.bom_label import run_bom_label_check
from kaizen.datasets.pdf_label import LabelSpec, render_label_pdf
from kaizen.ingest.label_pdf import parse_label_pdf
from kaizen.matching.ladder import MatchLadder
from kaizen.models import Classification, DiscrepancyType, Relationship, Severity, Thresholds
from kaizen.terminology.store import RelationshipStore
from tests.unit.test_bom_label_check import bom_doc, label_doc

TH = Thresholds()


def run(bom, label, store=None):
    return run_bom_label_check(bom, label, MatchLadder(store or RelationshipStore.default(), TH), TH)


def rows(results):
    return {r.source_a.item_number: r for r in results if r.source_a is not None and r.role == "item"}


def label_only(results):
    return [r for r in results if r.source_a is None]


# --- similar vs equivalent -------------------------------------------------------------------------------
def test_full_token_containment_is_potential_not_equivalent():
    r = rows(run(bom_doc([("4440003", "CHLORAPREP APPLICATOR 3ML", "1")]), label_doc([("ChloraPrep™ Solution One-Step Applicator, 3 mL", "1")])))["4440003"]
    assert r.classification is Classification.POTENTIAL
    assert r.score < 0.85 and r.candidate_score == 1.0
    assert r.requires_validation is True


def test_same_pair_becomes_equivalent_only_with_a_relationship():
    store = RelationshipStore([Relationship(id="REL-900", canonical="ChloraPrep Solution One-Step Applicator, 3 mL", aliases=["CHLORAPREP APPLICATOR 3ML"], provenance="learned")])
    r = rows(run(bom_doc([("4440003", "CHLORAPREP APPLICATOR 3ML", "1")]), label_doc([("ChloraPrep™ Solution One-Step Applicator, 3 mL", "1")]), store))["4440003"]
    assert r.classification is Classification.EQUIVALENT and r.relationship_id == "REL-900"
    assert r.requires_validation is False


def test_similar_but_different_components_are_not_paired():
    results = run(bom_doc([("4410005", "SYRINGE 5ML", "1"), ("2340001", "DRAPE ABSORBENT", "1")]), label_doc([("Syringe, 10 mL", "1"), ("Towel, Absorbent", "1")]))
    r = rows(results)
    assert r["4410005"].classification is Classification.MISSING and "numeric" in r["4410005"].discrepancies[0].detail
    assert r["2340001"].classification is Classification.MISSING and "Towel, Absorbent" in r["2340001"].discrepancies[0].detail
    assert {x.source_b.description for x in label_only(results)} == {"Syringe, 10 mL", "Towel, Absorbent"}


def test_generic_shared_word_does_not_pair():
    r = rows(run(bom_doc([("2260001", "CAP END LUER", "2")]), label_doc([("Cap, Vial", "2")])))["2260001"]
    assert r.classification is Classification.MISSING


# --- wording nuisances ------------------------------------------------------------------------------------
def test_punctuation_and_trademark_variants_are_exact():
    bom = bom_doc([("1", "TOWEL, ABSORBENT", "1"), ("2", "STATLOCK® STABILIZATION DEVICE", "1"), ("3", "END-CAP", "2"), ("4", "WIPE ALCOHOL 70 %", "1")])
    label = label_doc([("Towel - Absorbent", "1"), ("StatLock™ Stabilization Device", "1"), ("End Cap", "2"), ("Wipe, Alcohol, 70%", "1")])
    r = rows(run(bom, label))
    assert all(r[k].classification is Classification.EXACT for k in ("1", "2", "3", "4")), {k: v.classification for k, v in r.items()}


def test_abbreviation_and_slash_forms():
    r = rows(run(bom_doc([("1", "SYRINGE W/ NEEDLE 5ML", "1"), ("2", "ECG LEADS ASSY", "1")]), label_doc([("Syringe with Needle, 5 mL", "1"), ("ECG Leads Assembly", "1")])))
    assert r["1"].classification is Classification.EXACT and r["2"].classification is Classification.EXACT


# --- quantities -------------------------------------------------------------------------------------------
def test_uom_pair_on_label_explains_double_quantity():
    label = label_doc([("Gloves", "1")])
    label.items[0].uom = "PAIR"
    r = rows(run(bom_doc([("2300001", "GLOVES EXAM", "2")]), label))["2300001"]
    assert r.classification is Classification.POTENTIAL
    assert r.discrepancies[0].type is DiscrepancyType.QTY_MISMATCH and r.discrepancies[0].severity is Severity.MINOR
    assert "pair" in r.discrepancies[0].detail.lower()


def test_fractional_bom_quantity_against_whole_label_quantity_is_mismatch():
    r = rows(run(bom_doc([("2260001", "END CAP", "0.5")]), label_doc([("End Cap", "1")])))["2260001"]
    assert r.classification is Classification.MISMATCH
    assert "0.5" in r.discrepancies[0].detail


def test_trailing_zero_quantities_are_equal():
    r = rows(run(bom_doc([("2260001", "END CAP", "2.0000")]), label_doc([("End Cap", "2")])))["2260001"]
    assert r.classification is Classification.EXACT and r.discrepancies == []


def test_zero_quantity_physical_line_is_not_compared():
    results = run(bom_doc([("9", "OBSOLETE WIDGET", "0")]), label_doc([("Towel, Absorbent", "1")]))
    assert "9" not in rows(results)


# --- repeated content -------------------------------------------------------------------------------------
def test_repeated_label_line_is_flagged_ambiguous_and_the_duplicate_reported():
    results = run(bom_doc([("2240001", "MASK PROCEDURE", "2")]), label_doc([("Mask", "2"), ("Mask", "2")]))
    r = rows(results)["2240001"]
    assert r.classification is Classification.POTENTIAL  # relationship match downgraded because two lines fit
    assert any(d.type is DiscrepancyType.AMBIGUOUS_MATCH for d in r.discrepancies)
    assert len(label_only(results)) == 1


def test_decoy_ref_on_a_sub_label_does_not_win(tmp_path):
    spec = LabelSpec(ref="1295108", product_name="Kit", contents=["1 Each - Towel, Absorbent", "1 Each - Mask"], extra_footer_lines=["Contains: REF 8888888 (sensor holder)"])
    doc = parse_label_pdf(render_label_pdf(spec, tmp_path / "l.pdf"))
    assert doc.sku == "1295108"
    assert doc.header["ref_occurrences"] >= 5
    assert [i.description for i in doc.items] == ["Towel, Absorbent", "Mask"]


def test_three_column_label_does_not_interleave(tmp_path):
    from kaizen.datasets import pdf_label

    pdf_label.COLUMN_X[3] = [30, 160, 290]
    pdf_label.COLUMN_WIDTH[3] = 120
    try:
        contents = [f"1 Each - Item Number {i} Long Name" for i in range(12)]
        spec = LabelSpec(ref="1295108", product_name="Kit", contents=contents, columns=3)
        doc = parse_label_pdf(render_label_pdf(spec, tmp_path / "l3.pdf"))
    finally:
        pdf_label.COLUMN_X.pop(3)
        pdf_label.COLUMN_WIDTH.pop(3)
    assert [i.description for i in doc.items] == [c.split(" - ", 1)[1] for c in contents]
