"""One-to-one assignment of A items to B items using ladder outcomes, with explicit ambiguity and hints."""

from collections.abc import Callable
from dataclasses import dataclass, field

from kaizen.matching.ladder import MatchContext, MatchLadder, MatchOutcome
from kaizen.matching.normalize import NormalizedText
from kaizen.models import MatchLevel, Thresholds

LEVEL_RANK = {
    MatchLevel.EXACT: 3,
    MatchLevel.RELATIONSHIP: 2,
    MatchLevel.FUZZY: 1,
    MatchLevel.SEMANTIC: 1,
    MatchLevel.LLM: 1,
    MatchLevel.NONE: 0,
}


@dataclass(frozen=True)
class Candidate:
    a_index: int
    b_index: int
    outcome: MatchOutcome
    note: str = ""


@dataclass
class Assignment:
    pairs: list[Candidate] = field(default_factory=list)
    unmatched_a: list[int] = field(default_factory=list)
    unmatched_b: list[int] = field(default_factory=list)
    ambiguous_a: dict[int, list[Candidate]] = field(default_factory=dict)
    hints_a: dict[int, Candidate] = field(default_factory=dict)
    hints_b: dict[int, Candidate] = field(default_factory=dict)
    candidates: list[Candidate] = field(default_factory=list)


def _rank(c: Candidate) -> tuple[int, float]:
    return (LEVEL_RANK[c.outcome.level], c.outcome.candidate_score if c.outcome.candidate_score is not None else c.outcome.score)


def assign(
    a_items: list[NormalizedText],
    b_items: list[NormalizedText],
    ladder: MatchLadder,
    ctx_for_a: Callable[[int], MatchContext],
    thresholds: Thresholds,
) -> Assignment:
    candidates: list[Candidate] = []
    for i, a in enumerate(a_items):
        ctx = ctx_for_a(i)
        for j, b in enumerate(b_items):
            out = ladder.match(a, b, ctx)
            if out.matched:
                candidates.append(Candidate(i, j, out))
    assignable = [c for c in candidates if c.outcome.assignable]
    order = sorted(assignable, key=lambda c: (-LEVEL_RANK[c.outcome.level], -c.outcome.score, c.a_index, c.b_index))
    taken_a: dict[int, Candidate] = {}
    taken_b: dict[int, Candidate] = {}
    for c in order:
        if c.a_index in taken_a or c.b_index in taken_b:
            continue
        taken_a[c.a_index] = c
        taken_b[c.b_index] = c
    pairs = sorted(taken_a.values(), key=lambda c: c.a_index)
    unmatched_a = [i for i in range(len(a_items)) if i not in taken_a]
    unmatched_b = [j for j in range(len(b_items)) if j not in taken_b]

    delta = thresholds.ambiguity_delta
    ambiguous: dict[int, list[Candidate]] = {}
    for p in pairs:
        alts = [
            Candidate(c.a_index, c.b_index, c.outcome, note=f"alternative candidate at the same level with score {c.outcome.score:.2f}")
            for c in assignable
            if c.a_index == p.a_index
            and c.b_index != p.b_index
            and LEVEL_RANK[c.outcome.level] == LEVEL_RANK[p.outcome.level]
            and (c.outcome.candidate_score if c.outcome.candidate_score is not None else c.outcome.score) >= (p.outcome.candidate_score if p.outcome.candidate_score is not None else p.outcome.score) - delta
        ]
        if alts:
            ambiguous[p.a_index] = alts
    for i in unmatched_a:
        mine = [c for c in assignable if c.a_index == i]
        if mine:
            best = max(mine, key=_rank)
            holder = taken_b.get(best.b_index)
            note = f"best candidate already assigned to item {holder.a_index}" if holder else "best candidate could not be assigned"
            ambiguous[i] = [Candidate(i, best.b_index, best.outcome, note=note)]

    hints_a: dict[int, Candidate] = {}
    for i in unmatched_a:
        mine = [c for c in candidates if c.a_index == i]
        if mine:
            hints_a[i] = max(mine, key=_rank)
    hints_b: dict[int, Candidate] = {}
    for j in unmatched_b:
        mine = [c for c in candidates if c.b_index == j]
        if mine:
            hints_b[j] = max(mine, key=_rank)
    return Assignment(pairs, unmatched_a, unmatched_b, ambiguous, hints_a, hints_b, candidates)
