from kaizen.matching.fuzzy import similarity
from kaizen.matching.normalize import normalize


def sim(a, b):
    return similarity(normalize(a), normalize(b))


def test_reordered_words_score_one():
    assert sim("Towel, Absorbent", "ABSORBENT TOWEL").score == 1.0


def test_numeric_disagreement_is_flagged():
    s = sim("Gauze, 10 cm x 10 cm (4 in. x 4 in.)", "Gauze, 5 cm x 5 cm (2 in. x 2 in.)")
    assert s.numeric_conflict is True
    assert "numeric" in s.detail.lower()


def test_shared_number_is_not_a_conflict():
    assert sim("GAUZE 4X4", "Gauze, 10 cm x 10 cm (4 in. x 4 in.)").numeric_conflict is False


def test_no_numbers_no_conflict():
    assert sim("ABSORBENT TOWEL", "Towel, Absorbent").numeric_conflict is False


def test_unrelated_descriptions_score_low():
    assert sim("ABSORBENT TOWEL", "Drape, Absorbent").score < 0.85
    assert sim("MASK", "Measuring Tape").score < 0.5


def test_extra_trailing_word_still_scores_high():
    assert sim("STATLOCK STABILIZATION DEVICE", "StatLock™ Stabilization Device Adult").score >= 0.85


def test_token_set_does_not_hide_omitted_attributes():
    assert sim("NEEDLE, 0.5MM", "Needle, Safety Hypodermic, 25 G (0.5 mm OD x 16 mm Length)").score < 0.85
    assert sim("DRAPE, ABSORBENT, 24IN X 24IN", "Drape, Absorbent").score < 0.85
    assert sim("SYRINGE, LUER LOCK, 5ML", "Syringe, 5 mL").score < 0.85
    assert sim("FUNNEL STYLET", "PICC assembly with Stylet and Stylet Funnel").score < 0.85


def test_composite_detail_reports_coverage():
    assert "token_coverage=" in sim("NEEDLE", "Needle Safety Hypodermic").detail


def test_single_generic_token_does_not_score_high():
    assert sim("TAPE", "Surgical Tape").score < 0.85


def test_stopwords_are_ignored():
    assert sim("CATHETER WITH SHERLOCK", "Catheter Sherlock").score == 1.0


def test_detail_explains_method():
    s = sim("STATLOCK STABILIZATION DEVICE", "StatLock™ Stabilization Device Adult")
    assert "token" in s.detail
    assert s.method
