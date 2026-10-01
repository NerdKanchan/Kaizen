"""Relationship mining: repeated fuzzy pairings across SKUs become SUGGESTIONS with evidence. A human approves
or rejects; nothing is created automatically."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from kaizen.matching.normalize import normalize
from kaizen.models import MatchLevel, Relationship, Run
from kaizen.review.store import ReviewStore
from kaizen.storage.db import Database
from kaizen.terminology.repository import TerminologyRepository


@dataclass
class Suggestion:
    a_text: str
    b_text: str
    a_key: str
    b_key: str
    sku_count: int
    skus: list[str]
    check_types: list[str]
    row_ids: list[str]
    confirmed: int = 0
    contradicted: int = 0
    item_anchors: list[str] = field(default_factory=list)
    relationship_id: str | None = None
    would_clear: int = 0  # rows with no discrepancy: confirmed as a relationship they auto-clear on the next run
    still_review: int = 0  # rows that carry a discrepancy (e.g. a quantity mismatch) and need a reviewer regardless
    cumulative_clear: int = 0  # running total down the ranked worklist
    cumulative_pct: float = 0.0  # ... as a share of all rows needing validation
    mean_score: float = 0.0
    minimum_score: float = 0.0
    mean_candidate_score: float = 0.0
    confidence: float = 0.0  # conservative: the weakest reviewer-facing score in the group

    @property
    def pair_key(self) -> str:
        return f"{self.a_key}|{self.b_key}"

    @property
    def evidence(self) -> str:
        parts = [f"seen in {self.sku_count} SKU(s)", f"checks: {', '.join(self.check_types)}"]
        parts.append(f"confidence floor {self.confidence:.2f}")
        parts.append(f"confirmed by reviewers in {self.confirmed} comparison(s)" if self.confirmed else "not yet confirmed by a reviewer")
        parts.append(f"contradicted in {self.contradicted} comparison(s)" if self.contradicted else "never contradicted")
        return "; ".join(parts)


def mine_suggestions(run: Run, review: ReviewStore, repo: TerminologyRepository, min_skus: int = 2) -> list[Suggestion]:
    store = repo.store()
    rejected = {r[0] for r in repo.conn.execute("SELECT pair_key FROM mining_rejections")}
    decisions = review.all_decisions(run.metadata.run_id)
    groups: dict[tuple[str, str], Suggestion] = {}
    metrics: dict[tuple[str, str], list[float]] = {}
    for r in run.results:
        if r.match_level is not MatchLevel.FUZZY or r.source_a is None or r.source_b is None:
            continue
        na, nb = normalize(r.source_a.description), normalize(r.source_b.description)
        key = (na.sorted_key, nb.sorted_key)
        if store.lookup(na, nb, sku=r.sku, item_number=r.source_a.item_number) is not None:
            continue
        s = groups.get(key)
        if s is None:
            s = Suggestion(r.source_a.description, r.source_b.description, na.sorted_key, nb.sorted_key, 0, [], [], [])
            groups[key] = s
        if r.sku not in s.skus:
            s.skus.append(r.sku)
        if r.check.value not in s.check_types:
            s.check_types.append(r.check.value)
        s.row_ids.append(r.row_id)
        if r.discrepancies:
            s.still_review += 1
        else:
            s.would_clear += 1
        metrics.setdefault(key, []).append(r.score)
        if r.source_a.item_number and r.source_a.item_number not in s.item_anchors:
            s.item_anchors.append(r.source_a.item_number)
        for d in decisions.get(r.row_id, {}).values():
            if d.decision == "ACCEPT" or (d.decision == "OVERRIDE" and d.override_classification in ("EQUIVALENT", "EXACT")):
                s.confirmed += 1
            elif d.decision == "CONFIRM_DISCREPANCY" or (d.decision == "OVERRIDE" and d.override_classification in ("MISMATCH", "MISSING")):
                s.contradicted += 1
    out = []
    for s in groups.values():
        s.sku_count = len(s.skus)
        scores = metrics[s.a_key, s.b_key]
        if scores:
            s.mean_score = round(sum(scores) / len(scores), 4)
            s.minimum_score = round(min(scores), 4)
            s.confidence = s.minimum_score
            candidate_scores = [
                r.candidate_score if r.candidate_score is not None else r.score
                for r in run.results
                if r.row_id in s.row_ids
            ]
            s.mean_candidate_score = round(sum(candidate_scores) / len(candidate_scores), 4) if candidate_scores else 0.0
        if s.sku_count >= min_skus and s.pair_key not in rejected:
            out.append(s)
    out.sort(key=lambda s: (-s.confidence, -s.sku_count, -s.would_clear, -s.confirmed, s.contradicted, s.a_text))
    return out


def approve_suggestion(repo: TerminologyRepository, s: Suggestion, by: str, scope: str = "global", anchor: bool = False, notes: str = "") -> Relationship:
    rel = repo.create(canonical=s.b_text, aliases=[s.a_text], scope=scope, item_anchors=s.item_anchors if anchor else [], provenance="learned", created_by=by, notes=notes or f"Approved from mining suggestion: {s.evidence}")
    s.relationship_id = rel.id
    return rel


def reject_suggestion(db: Database, s: Suggestion, by: str, note: str = "") -> None:
    db.conn.execute("INSERT OR REPLACE INTO mining_rejections VALUES (?,?,?,?)", (s.pair_key, by, datetime.now(timezone.utc).isoformat(timespec="seconds"), note))
    db.audit(by, "mining.rejected", f"{s.a_text} = {s.b_text}: {note}".strip())
    db.conn.commit()


@dataclass
class Worklist:
    """Unconfirmed fuzzy pairings ranked by the rows they would auto-clear once approved as relationships."""

    needs_validation: int  # reviewable rows needing validation in this run (the denominator)
    potential_rows: int  # rows behind an unconfirmed pairing
    items: list[Suggestion]

    def top(self, n: int) -> dict:
        rows = sum(i.would_clear for i in self.items[:n])
        return {"n": min(n, len(self.items)) if n > 0 else 0, "rows": rows, "pct": round(100 * rows / self.needs_validation, 1) if self.needs_validation and n > 0 else 0.0}

    def to_dict(self) -> dict:
        return {"needs_validation": self.needs_validation, "potential_rows": self.potential_rows, "items": [asdict(i) | {"pair_key": i.pair_key, "evidence": i.evidence} for i in self.items], "top5": self.top(5), "top10": self.top(10)}


def terminology_worklist(run: Run, review: ReviewStore, repo: TerminologyRepository) -> Worklist:
    """The business-case projection as a to-do list: approve these, in this order, and this many rows clear."""
    from kaizen.review.business import reviewable

    items = mine_suggestions(run, review, repo, min_skus=1)
    # Impact remains the primary rank. Confidence breaks ties so the reviewer
    # sees the strongest repeated wording before weaker candidates with the
    # same projected impact.
    items.sort(key=lambda s: (-s.would_clear, -s.confidence, -s.sku_count, -s.confirmed, s.a_text))
    needs = sum(1 for r in reviewable(run) if r.requires_validation)
    total = 0
    for s in items:
        total += s.would_clear
        s.cumulative_clear = total
        s.cumulative_pct = round(100 * total / needs, 1) if needs else 0.0
    return Worklist(needs, sum(len(s.row_ids) for s in items), items)
