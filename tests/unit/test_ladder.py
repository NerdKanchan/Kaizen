from kaizen.matching.fuzzy import similarity  # noqa: F401  (ensures module import path is valid)
from kaizen.matching.ladder import ExactMatcher, FuzzyMatcher, MatchContext, MatchLadder, MatchOutcome, RelationshipMatcher
from kaizen.models import MatchLevel, Relationship, Thresholds
from kaizen.terminology.store import RelationshipStore

STORE = RelationshipStore(
    [
        Relationship(id="REL-001", canonical="Surgical Tape", aliases=["TAPE ANCHOR PER-Q-CATH"]),
        Relationship(id="REL-002", canonical="StatLock Stabilization Device", aliases=["STATLOCK STABILIZATION DEVICE ADULT"]),
    ]
)
TH = Thresholds(potential=0.85, floor=0.60, ambiguity_delta=0.05)


def ladder() -> MatchLadder:
    return MatchLadder(STORE, TH)


def test_exact_after_normalization():
    out = ladder().match("Towel, Absorbent", "ABSORBENT TOWEL")
    assert out.level is MatchLevel.EXACT
    assert out.score == 1.0
    assert "EXACT" in out.reason and "TOWEL ABSORBENT" in out.reason and "ABSORBENT TOWEL" in out.reason


def test_relationship_level_carries_id():
    out = ladder().match("TAPE ANCHOR PER-Q-CATH", "Surgical Tape", MatchContext(sku="1295108NS"))
    assert out.level is MatchLevel.RELATIONSHIP
    assert out.relationship_id == "REL-001"
    assert "REL-001" in out.reason and "EQUIVALENT" in out.reason


def test_fuzzy_above_threshold_is_potential_with_score_and_threshold_in_reason():
    out = ladder().match("CHLORAPREP APPLICATOR 3ML", "ChloraPrep™ Solution One-Step Applicator, 3 mL")
    assert out.level is MatchLevel.FUZZY
    assert out.score < 0.85 and out.candidate_score >= 0.85
    assert out.weak is False
    assert "POTENTIAL" in out.reason and "0.85" in out.reason and "token" in out.reason


def test_fuzzy_between_floor_and_threshold_is_weak():
    out = ladder().match("ABSORBENT TOWEL", "Drape, Absorbent")
    assert out.level is MatchLevel.FUZZY
    assert out.weak is True
    assert 0.60 <= out.score < 0.85


def test_below_floor_is_no_match():
    out = ladder().match("MASK", "Measuring Tape")
    assert out.level is MatchLevel.NONE
    assert out.matched is False
    assert out.reason


def test_numeric_conflict_is_reported():
    out = ladder().match("Gauze, 10 cm x 10 cm (4 in. x 4 in.)", "Gauze, 5 cm x 5 cm (2 in. x 2 in.)")
    assert out.level is MatchLevel.FUZZY
    assert out.numeric_conflict is True
    assert out.assignable is False
    assert "numeric" in out.reason.lower()


def test_fuzzy_never_returns_exact():
    fuzzy_only = MatchLadder(STORE, TH, matchers=[FuzzyMatcher(TH)])
    out = fuzzy_only.match("Towel, Absorbent", "ABSORBENT TOWEL")
    assert out.level is MatchLevel.FUZZY
    assert out.score == 1.0


def test_relationship_beats_fuzzy():
    # fuzzy would also score this pair at 1.0; the ladder must report the relationship level and its ID
    out = ladder().match("STATLOCK STABILIZATION DEVICE ADULT", "StatLock Stabilization Device")
    assert out.level is MatchLevel.RELATIONSHIP
    assert out.relationship_id == "REL-002"


def test_custom_matcher_plugs_in_after_built_ins():
    class StubSemantic:
        name = "semantic-stub"

        def try_match(self, a, b, ctx):
            return MatchOutcome(level=MatchLevel.SEMANTIC, score=0.9, reason="SEMANTIC stub")

    lad = MatchLadder(STORE, TH, extra_matchers=[StubSemantic()])
    assert lad.match("MASK", "Measuring Tape").level is MatchLevel.SEMANTIC
    assert lad.match("Towel, Absorbent", "ABSORBENT TOWEL").level is MatchLevel.EXACT
    assert [m.name for m in lad.matchers][:3] == [ExactMatcher.name, RelationshipMatcher.name, FuzzyMatcher.name]
