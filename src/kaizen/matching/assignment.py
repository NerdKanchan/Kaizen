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

ASSIGNMENT_VERSION = "2"


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


def _hungarian_min(cost: list[list[float]]) -> list[int]:
    """Return the minimum-cost column selected for each row.

    This is the rectangular Hungarian algorithm. The caller supplies enough
    dummy columns for every row to remain unmatched, so the result is a
    maximum-weight matching over only eligible candidates.
    """
    n = len(cost)
    m = len(cost[0]) if n else 0
    if not n:
        return []
    if n > m:
        raise ValueError("Hungarian assignment requires at least as many columns as rows")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                current = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if current < minv[j]:
                    minv[j] = current
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    selected = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            selected[p[j] - 1] = j - 1
    return selected


def _maximum_weight_pairs(assignable: list[Candidate], n_a: int, n_b: int) -> list[Candidate]:
    """Maximise cardinality first, then ladder level, then candidate score."""
    by_edge = {(c.a_index, c.b_index): c for c in assignable}
    max_matches = min(n_a, n_b)
    score_weight = 1000.0
    max_secondary = max_matches * (max(LEVEL_RANK.values()) * score_weight + score_weight)
    match_bonus = max_secondary + 1.0
    invalid_weight = -(match_bonus * 2.0)
    # Dummy columns let every A item be assigned without forcing an invalid
    # edge. Actual B columns come first for deterministic tie-breaking.
    columns = n_b + n_a
    weights: list[list[float]] = []
    for i in range(n_a):
        row: list[float] = []
        for j in range(n_b):
            c = by_edge.get((i, j))
            if c is None:
                row.append(invalid_weight)
                continue
            level, score = _rank(c)
            row.append(match_bonus + level * score_weight + score)
        row.extend([0.0] * n_a)
        assert len(row) == columns
        weights.append(row)
    selected = _hungarian_min([[-weight for weight in row] for row in weights])
    pairs = []
    for i, j in enumerate(selected):
        if 0 <= j < n_b and (i, j) in by_edge:
            pairs.append(by_edge[(i, j)])
    return pairs


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
    # Candidate score controls eligibility. Assignment is global: resolve all
    # collisions together instead of letting an early high score consume a B
    # item that would have enabled two valid pairings.
    pairs = sorted(_maximum_weight_pairs(assignable, len(a_items), len(b_items)), key=lambda c: c.a_index)
    taken_a = {c.a_index: c for c in pairs}
    taken_b = {c.b_index: c for c in pairs}
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
