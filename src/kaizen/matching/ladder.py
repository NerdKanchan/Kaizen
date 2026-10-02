"""The match ladder: staged matchers, each producing an explained outcome or nothing.

L1 exact → L2 relationship → L3 fuzzy. L4 semantic and L5 LLM are PLANNED and plug in as extra matchers.
"""

from dataclasses import dataclass, replace
from typing import Protocol

from kaizen.matching.attributes import DIMENSION, Attributes, attribute_conflicts, extract_attributes
from kaizen.matching.fuzzy import similarity
from kaizen.matching.normalize import NormalizedText, normalize
from kaizen.models import DocType, MatchLevel, Thresholds
from kaizen.terminology.store import RelationshipStore


@dataclass(frozen=True)
class MatchContext:
    sku: str | None = None
    doc_types: tuple[DocType, ...] = ()
    item_number: str | None = None


@dataclass(frozen=True)
class MatchOutcome:
    level: MatchLevel
    score: float
    reason: str
    relationship_id: str | None = None
    numeric_conflict: bool = False
    weak: bool = False  # above the candidate floor but below the POTENTIAL threshold
    needs_confirmation: bool = False  # pairing is justified but must be shown as POTENTIAL (e.g. anchor with unknown wording)
    candidate_score: float | None = None

    @property
    def matched(self) -> bool:
        return self.level is not MatchLevel.NONE

    @property
    def assignable(self) -> bool:
        return self.matched and not self.weak and not self.numeric_conflict


class Matcher(Protocol):
    name: str

    def try_match(self, a: NormalizedText, b: NormalizedText, ctx: MatchContext) -> MatchOutcome | None: ...


class ExactMatcher:
    name = "L1_exact"

    def try_match(self, a: NormalizedText, b: NormalizedText, ctx: MatchContext) -> MatchOutcome | None:
        if a.sorted_key and a.sorted_key == b.sorted_key:
            return MatchOutcome(MatchLevel.EXACT, 1.0, f'EXACT: "{a.normalized}" == "{b.normalized}" after normalization')
        return None


class RelationshipMatcher:
    name = "L2_relationship"

    def __init__(self, store: RelationshipStore):
        self.store = store

    def try_match(self, a: NormalizedText, b: NormalizedText, ctx: MatchContext) -> MatchOutcome | None:
        hit = self.store.lookup(a, b, sku=ctx.sku, item_number=ctx.item_number, doc_types=ctx.doc_types)
        if hit is None:
            return None
        rel = hit.relationship
        terms = " = ".join(rel.terms())
        if hit.kind == "anchor":
            # the item number is anchored to this relationship, but the BOM wording is not one of its terms:
            # JDE may have re-described the item, so the pairing is shown as POTENTIAL for the reviewer
            return MatchOutcome(
                MatchLevel.RELATIONSHIP,
                1.0,
                f'ANCHORED: item {ctx.item_number} is anchored to {rel.id} [{rel.scope}] ({terms}) and "{b.raw}" is one of its terms, but the BOM wording "{a.raw}" is not a known term — reviewer to confirm',
                relationship_id=rel.id,
                needs_confirmation=True,
            )
        return MatchOutcome(
            MatchLevel.RELATIONSHIP,
            1.0,
            f'EQUIVALENT: "{a.raw}" ≡ "{b.raw}" via {rel.id} [{rel.scope}] ({terms}); matched on terms',
            relationship_id=rel.id,
        )


class FuzzyMatcher:
    name = "L3_fuzzy"

    def __init__(self, thresholds: Thresholds):
        self.thresholds = thresholds

    def try_match(self, a: NormalizedText, b: NormalizedText, ctx: MatchContext) -> MatchOutcome | None:
        s = similarity(a, b)
        if s.candidate_score < self.thresholds.floor:
            return None
        weak = s.candidate_score < self.thresholds.potential
        label = "WEAK" if weak else "POTENTIAL"
        reason = (
            f'{label}: "{a.raw}" ↔ "{b.raw}"; {s.detail}; threshold {self.thresholds.potential:.2f}'
            f" (floor {self.thresholds.floor:.2f})"
        )
        if s.numeric_conflict:
            reason += "; not auto-paired because numeric tokens disagree"
        return MatchOutcome(MatchLevel.FUZZY, s.score, reason, numeric_conflict=s.numeric_conflict, weak=weak, candidate_score=s.candidate_score)


class MatchLadder:
    def __init__(
        self,
        store: RelationshipStore,
        thresholds: Thresholds,
        matchers: list[Matcher] | None = None,
        extra_matchers: list[Matcher] | tuple[Matcher, ...] = (),
        structured: bool = False,
        attribute_overrides: dict | None = None,
    ):
        self.thresholds = thresholds
        self.structured = structured
        self.attribute_overrides = attribute_overrides or {}
        built_in: list[Matcher] = [ExactMatcher(), RelationshipMatcher(store), FuzzyMatcher(thresholds)]
        self.matchers: list[Matcher] = list(matchers) if matchers is not None else built_in
        self.matchers.extend(extra_matchers)

    def match(self, a: NormalizedText | str, b: NormalizedText | str, ctx: MatchContext = MatchContext()) -> MatchOutcome:
        na = a if isinstance(a, NormalizedText) else normalize(a)
        nb = b if isinstance(b, NormalizedText) else normalize(b)
        aa, ab = extract_attributes(na.raw), extract_attributes(nb.raw)
        if self.structured and len(ctx.doc_types) == 2:
            aa = Attributes(**self.attribute_overrides.get((ctx.doc_types[0].value, na.sorted_key), aa.to_dict()))
            ab = Attributes(**self.attribute_overrides.get((ctx.doc_types[1].value, nb.sorted_key), ab.to_dict()))
        conflicts = attribute_conflicts(aa, ab) if self.structured else []
        for m in self.matchers:
            out = m.try_match(na, nb, ctx)
            if out is not None:
                if conflicts:
                    return replace(out, numeric_conflict=True, reason=out.reason + "; incompatible structured attributes: " + "; ".join(conflicts))
                if self.structured and aa.dimensions_mm and ab.dimensions_mm and sorted(aa.dimensions_mm) != sorted(ab.dimensions_mm) and out.level in (MatchLevel.EXACT, MatchLevel.RELATIONSHIP):
                    return replace(out, needs_confirmation=True, reason=out.reason + "; dimensions are approximate equivalents after unit conversion; reviewer confirmation required")
                if self.structured and out.numeric_conflict and aa.dimensions_mm and ab.dimensions_mm:
                    remaining_a = normalize(DIMENSION.sub('DIMENSION', na.raw)).numbers
                    remaining_b = normalize(DIMENSION.sub('DIMENSION', nb.raw)).numbers
                    if (remaining_a <= remaining_b or remaining_b <= remaining_a) and DIMENSION.search(na.raw) and DIMENSION.search(nb.raw):
                        return replace(out, numeric_conflict=False, weak=False, needs_confirmation=True, score=self.thresholds.potential,
                                       reason=out.reason + f"; explicit dimensions agree after unit conversion: {aa.dimensions_mm} vs {ab.dimensions_mm} mm; reviewer confirmation required")
                if self.structured and out.weak and aa.component_type and aa.component_type == ab.component_type:
                    return replace(out, score=self.thresholds.potential, weak=False, needs_confirmation=True, reason=out.reason + f"; shared component type {aa.component_type}; reviewer confirmation required")
                return out
        if self.structured and aa.component_type and aa.component_type == ab.component_type:
            return MatchOutcome(MatchLevel.FUZZY, self.thresholds.potential, f"POTENTIAL: shared component type {aa.component_type}; short wording needs reviewer confirmation" + ("; incompatible attributes: " + "; ".join(conflicts) if conflicts else ""), numeric_conflict=bool(conflicts), needs_confirmation=True)
        return MatchOutcome(MatchLevel.NONE, 0.0, f'NO MATCH: "{na.raw}" vs "{nb.raw}" scored below the candidate floor at every level')
