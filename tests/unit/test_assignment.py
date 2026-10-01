from kaizen.matching.assignment import assign
from kaizen.matching.ladder import MatchContext, MatchLadder
from kaizen.matching.normalize import normalize
from kaizen.models import MatchLevel, Relationship, Thresholds
from kaizen.terminology.store import RelationshipStore

STORE = RelationshipStore([Relationship(id="REL-001", canonical="Surgical Tape", aliases=["TAPE ANCHOR PER-Q-CATH"])])
TH = Thresholds(potential=0.85, floor=0.60, ambiguity_delta=0.05)


def run(a_texts, b_texts):
    lad = MatchLadder(STORE, TH)
    return assign([normalize(t) for t in a_texts], [normalize(t) for t in b_texts], lad, lambda i: MatchContext(), TH)


def test_one_to_one_assignment_prefers_higher_levels():
    res = run(["ABSORBENT TOWEL", "TAPE ANCHOR PER-Q-CATH", "STATLOCK STABILIZATION DEVICE"], ["Surgical Tape", "Towel, Absorbent", "StatLock Stabilization Device Adult"])
    pairs = {p.a_index: (p.b_index, p.outcome.level) for p in res.pairs}
    assert pairs[0] == (1, MatchLevel.EXACT)
    assert pairs[1] == (0, MatchLevel.RELATIONSHIP)
    assert pairs[2] == (2, MatchLevel.FUZZY)
    assert res.unmatched_a == [] and res.unmatched_b == []


def test_unmatched_sides_and_hint_for_weak_candidate():
    res = run(["ABSORBENT TOWEL", "MASK"], ["Drape, Absorbent"])
    assert res.pairs == []
    assert res.unmatched_a == [0, 1]
    assert res.unmatched_b == [0]
    assert 0 in res.hints_a and res.hints_a[0].b_index == 0 and res.hints_a[0].outcome.weak is True
    assert 1 not in res.hints_a


def test_numeric_conflict_candidate_is_not_assigned_but_kept_as_hint():
    res = run(["GAUZE 4X4"], ["Gauze, 5 cm x 5 cm (2 in. x 2 in.)"])
    assert res.pairs == []
    assert res.hints_a[0].outcome.numeric_conflict is True


def test_numeric_guard_steers_similar_descriptions_to_the_right_lines():
    res = run(["GAUZE 4X4", "GAUZE 2X2"], ["Gauze, 5 cm x 5 cm (2 in. x 2 in.)", "Gauze, 10 cm x 10 cm (4 in. x 4 in.)"])
    pairs = {p.a_index: p.b_index for p in res.pairs}
    assert pairs == {0: 1, 1: 0}


def test_ambiguous_when_top_two_candidates_are_within_delta():
    res = run(["NEEDLE 21G"], ["Needle, Introducer, 21 G", "Needle, Safety Hypodermic, 21 G"])
    assert len(res.pairs) == 1
    assert 0 in res.ambiguous_a
    alts = res.ambiguous_a[0]
    assert len(alts) == 1 and alts[0].b_index != res.pairs[0].b_index


def test_assignment_uses_candidate_score_not_conservative_display_score():
    res = run(
        ["NEEDLE 21G"],
        [
            "Needle, Introducer, 21 G (0.9 mm OD x 0.55 mm ID x 70 mm Length)",
            "Needle, Safety Hypodermic, 21 G (0.8 mm OD x 40 mm Length)",
        ],
    )
    assert res.pairs[0].b_index == 0


def test_unmatched_item_whose_best_candidate_was_taken_is_ambiguous():
    res = run(["NEEDLE INTRODUCER 21G", "NEEDLE 21G"], ["Needle, Introducer, 21 G"])
    assert len(res.pairs) == 1 and res.pairs[0].a_index == 0
    assert res.unmatched_a == [1]
    assert 1 in res.ambiguous_a
    assert "already assigned" in res.ambiguous_a[1][0].note


def test_duplicate_exact_label_lines_flag_ambiguity():
    res = run(["MASK"], ["Mask", "Mask"])
    assert len(res.pairs) == 1
    assert 0 in res.ambiguous_a


def test_deterministic_order_of_pairs():
    a = ["ABSORBENT TOWEL", "MASK", "END CAP"]
    b = ["End Cap", "Mask", "Towel, Absorbent"]
    first = [(p.a_index, p.b_index) for p in run(a, b).pairs]
    second = [(p.a_index, p.b_index) for p in run(a, b).pairs]
    assert first == second == [(0, 2), (1, 1), (2, 0)]


def test_global_assignment_preserves_two_valid_pairs_when_greedy_would_collide():
    """A high-scoring shared candidate must not hide a second feasible pairing."""

    class MatrixLadder:
        def match(self, a, b, ctx=MatchContext()):
            scores = {
                ("A0", "B0"): 0.90,
                ("A0", "B1"): 0.80,
                ("A1", "B0"): 0.85,
            }
            score = scores.get((a.raw, b.raw))
            if score is None:
                from kaizen.matching.ladder import MatchOutcome

                return MatchOutcome(MatchLevel.NONE, 0.0, "none")
            from kaizen.matching.ladder import MatchOutcome

            return MatchOutcome(MatchLevel.FUZZY, score, "candidate", candidate_score=score)

    result = assign(
        [normalize("A0"), normalize("A1")],
        [normalize("B0"), normalize("B1")],
        MatrixLadder(),
        lambda i: MatchContext(),
        TH,
    )
    assert {(p.a_index, p.b_index) for p in result.pairs} == {(0, 1), (1, 0)}
    assert result.unmatched_a == [] and result.unmatched_b == []
