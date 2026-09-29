"""Outputs of a check: typed, explained, evidence-bearing."""

from pydantic import BaseModel, Field, field_validator

from .document import DocumentItem
from .enums import CheckType, Classification, DiscrepancyType, MatchLevel, Severity


class Discrepancy(BaseModel):
    type: DiscrepancyType
    severity: Severity
    detail: str = Field(min_length=1)
    recommended_action: str = ""


class CheckResult(BaseModel):
    row_id: str
    sku: str
    check: CheckType
    role: str = Field(default="item", description="item | header | reference | coverage | exempt")
    source_a: DocumentItem | None = None
    source_b: DocumentItem | None = None
    normalized_a: str | None = None
    normalized_b: str | None = None
    classification: Classification
    match_level: MatchLevel
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_score: float | None = Field(default=None, ge=0.0, le=1.0)
    relationship_id: str | None = None
    explanation: str
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    requires_validation: bool = False
    reviewer_decision: str | None = None
    reviewer_comment: str | None = None
    final_status: str = "OPEN"

    @field_validator("explanation")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("every result must carry a non-empty explanation")
        return v

    @property
    def severity(self) -> Severity | None:
        order = [Severity.BLOCKER, Severity.MAJOR, Severity.MINOR, Severity.INFO]
        present = {d.severity for d in self.discrepancies}
        for s in order:
            if s in present:
                return s
        return None
