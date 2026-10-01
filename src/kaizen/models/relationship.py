"""Explicit, auditable terminology relationships. Never opaque weights."""

import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import DocType

_SCOPE_RE = re.compile(r"^(global|family:[A-Za-z0-9\-]+|sku:[A-Za-z0-9\-]+)$")


class Relationship(BaseModel):
    id: str
    canonical: str
    aliases: list[str] = Field(default_factory=list)
    scope: str = Field(default="global", description="'global' | 'family:<prefix>' | 'sku:<code>'")
    doc_types: list[DocType] = Field(default_factory=list, description="Empty means applies to all document types")
    item_anchors: list[str] = Field(default_factory=list, description="BOM item numbers this relationship is bound to")
    provenance: str = Field(default="manual", description="manual | learned | imported")
    created_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    active: bool = True
    notes: str = ""
    version: int = Field(default=1, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _default_updated_at(cls, data):
        # A relationship that has never been edited was last updated when it was created; never "now",
        # otherwise loading the same file twice would hash differently.
        if isinstance(data, dict) and data.get("updated_at") is None and data.get("created_at") is not None:
            data = {**data, "updated_at": data["created_at"]}
        return data

    @field_validator("scope")
    @classmethod
    def _scope_format(cls, v: str) -> str:
        if not _SCOPE_RE.match(v):
            raise ValueError("scope must be 'global', 'family:<prefix>' or 'sku:<code>'")
        return v

    @field_validator("canonical")
    @classmethod
    def nonempty_canonical(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("canonical wording must not be empty")
        return value

    def terms(self) -> list[str]:
        return [self.canonical, *self.aliases]
