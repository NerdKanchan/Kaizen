"""Where an extracted value came from. Never discarded after extraction."""

from pydantic import BaseModel, Field, model_validator


class BBox(BaseModel):
    """Box in PDF points, origin top-left, in the displayed page orientation."""

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def _ordered(self) -> "BBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bbox must satisfy x0 <= x1 and y0 <= y1")
        return self

    def union(self, other: "BBox") -> "BBox":
        return BBox(
            x0=min(self.x0, other.x0), y0=min(self.y0, other.y0), x1=max(self.x1, other.x1), y1=max(self.y1, other.y1)
        )


class Evidence(BaseModel):
    file: str = Field(description="Path of the source file as given to the tool")
    file_sha256: str = Field(min_length=64, max_length=64)
    page: int | None = Field(default=None, ge=1, description="1-based page number; None for tabular sources")
    bbox: BBox | None = None
    raw_text: str = Field(description="Verbatim source text the value was extracted from")
    line_index: int | None = Field(default=None, ge=0, description="Row/line ordinal within the source")
    sheet: str | None = Field(default=None, description="Worksheet name for XLSX sources")
    locator: str | None = Field(default=None, description="Human-readable pointer, e.g. 'page 2, row 14'")
    extraction_method: str = Field(default="pdf_text", description="pdf_text | table | ocr | ai_vision | none")
