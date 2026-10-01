"""A run: inputs, configuration, parsed documents, results. Fully reproducible."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .document import Document
from .result import CheckResult


class InputFile(BaseModel):
    path: str
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    doc_type: str | None = None


class Thresholds(BaseModel):
    """Matching thresholds. Recorded in every run so results are reproducible."""

    potential: float = Field(default=0.85, ge=0.0, le=1.0, description="Min token similarity for POTENTIAL")
    floor: float = Field(default=0.60, ge=0.0, le=1.0, description="Below this a pair is not a candidate at all")
    ambiguity_delta: float = Field(default=0.05, ge=0.0, le=1.0, description="Top-2 candidates closer than this → AMBIGUOUS")
    low_confidence: float = Field(default=0.70, ge=0.0, le=1.0, description="Extraction confidence below this is flagged")

    @model_validator(mode="after")
    def ordered_thresholds(self):
        if self.floor > self.potential:
            raise ValueError("candidate floor must not exceed the potential-match threshold")
        return self


class SkuGroup(BaseModel):
    sku: str
    family: str
    document_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AuditEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str = "system"
    action: str
    detail: str = ""


class RunMetadata(BaseModel):
    run_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tool_version: str
    parser_versions: dict[str, str] = Field(default_factory=dict)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    terminology_version: str = Field(description="SHA-256 of the relationship snapshot used")
    terminology_count: int = 0
    input_root: str
    inputs: list[InputFile] = Field(default_factory=list)
    capabilities: dict[str, str] = Field(
        default_factory=dict, description="Capability → IMPLEMENTED | NOT IMPLEMENTED | PLANNED"
    )
    ai_provider: dict[str, Any] = Field(default_factory=dict, description="Which AI provider (if any) was active; NullProvider by default")
    extraction_signature: str = Field(default="", description="SHA-256 of extracted identities/items/evidence; different OCR output produces a distinct run")


class CoverageFinding(BaseModel):
    kind: str = Field(description="sku_set | pco_affected_code")
    sku: str
    status: str = Field(description="OK | MISSING_BOM | MISSING_LABEL | MISSING_DRAWING | INFO")
    detail: str
    source: str = ""


class Run(BaseModel):
    metadata: RunMetadata
    documents: list[Document] = Field(default_factory=list)
    groups: list[SkuGroup] = Field(default_factory=list)
    coverage: list[CoverageFinding] = Field(default_factory=list)
    results: list[CheckResult] = Field(default_factory=list)
    relationships_used: list[str] = Field(default_factory=list)
    relationship_usage: dict[str, int] = Field(default_factory=dict, description="relationship id → rows that used it")
    terminology_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    audit_log: list[AuditEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
