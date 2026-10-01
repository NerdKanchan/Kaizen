import pytest

from kaizen.matching.normalize import normalize


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Towel, Absorbent", "TOWEL ABSORBENT"),
        ("ABSORBENT TOWEL", "ABSORBENT TOWEL"),
        ("ChloraPrep™ Solution One-Step Applicator, 3 mL", "CHLORAPREP SOLUTION ONE STEP APPLICATOR 3ML"),
        ("StatLock® Stabilization Device", "STATLOCK STABILIZATION DEVICE"),
        ("SYRINGE W/ NEEDLE", "SYRINGE WITH NEEDLE"),
        ("KIT W/O TRAY", "KIT WITHOUT TRAY"),
        ("Syringe, 5 mL", "SYRINGE 5ML"),
        ("SYRINGE 5ML", "SYRINGE 5ML"),
        ("Gauze, 10 cm x 10 cm (4 in. x 4 in.)", "GAUZE 10CM X 10CM 4IN X 4IN"),
        ("GAUZE 4X4", "GAUZE 4 X 4"),
        ("Needle, Introducer, 21 G", "NEEDLE INTRODUCER 21G"),
        ("Tape Strips", "TAPE STRIP"),
        ("Gloves (1 pair)", "GLOVE 1 PAIR"),
        ("TAPE ANCHOR PER-Q-CATH", "TAPE ANCHOR PER Q CATH"),
        ("  double   spaced  ", "DOUBLE SPACED"),
        ("Dual-Lumen PICC", "DUAL LUMEN PICC"),
        ("Mask", "MASK"),
        ("Batteries", "BATTERY"),
        ("Dressing, Adhesive", "DRESSING ADHESIVE"),
        ("PICC 5.0 F x 55 cm", "PICC 5F X 55CM"),
        ("Solution 0.9%, 10.0 mL", "SOLUTION 0.9% 10ML"),
        ("WIPE ALCOHOL 70 %", "WIPE ALCOHOL 70%"),
    ],
)
def test_normalized_string(raw, expected):
    assert normalize(raw).normalized == expected


def test_sorted_key_is_order_insensitive():
    assert normalize("Towel, Absorbent").sorted_key == normalize("ABSORBENT TOWEL").sorted_key


def test_sorted_key_distinguishes_different_content():
    assert normalize("Absorbent Towel").sorted_key != normalize("Absorbent Drape").sorted_key


def test_numeric_tokens_extracted_with_units():
    n = normalize("Gauze, 10 cm x 10 cm (4 in. x 4 in.)")
    assert n.numeric_tokens == ["10CM", "10CM", "4IN", "4IN"]
    assert n.numbers == {"10", "4"}


def test_numeric_tokens_absent_when_no_numbers():
    n = normalize("Absorbent Towel")
    assert n.numeric_tokens == []
    assert n.numbers == set()


def test_normalization_is_deterministic_and_idempotent():
    once = normalize("ChloraPrep™ Solution, 3 mL").normalized
    assert normalize(once).normalized == once


def test_short_tokens_and_ss_words_are_not_singularized():
    assert normalize("TPS Stylet").normalized == "TPS STYLET"
    assert normalize("Dressing").normalized == "DRESSING"
    assert normalize("Glass").normalized == "GLASS"


def test_tokens_list():
    assert normalize("Towel, Absorbent").tokens == ["TOWEL", "ABSORBENT"]


def test_curated_abbreviations_expand():
    assert normalize("ECG Leads Assy").normalized == "ECG LEAD ASSEMBLY"


def test_real_delivery_ocr_variants_are_normalized():
    assert normalize("TAPE, MEASUARING PAPER").normalized == "TAPE MEASURING PAPER"
    assert normalize("Lidocaine HCIl 1%").normalized == "LIDOCAINE HCL 1%"


def test_matching_tokens_collapse_metric_and_imperial_dimensions():
    metric = normalize("Gauze, 10 cm x 10 cm (4 in. x 4 in.)")
    terse = normalize("GAUZE PAD, 4X4 12 PLY")
    assert "DIM_4.00X4.00" in metric.matching_tokens
    assert "DIM_4.00X4.00" in terse.matching_tokens
