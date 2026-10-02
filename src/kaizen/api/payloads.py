"""Typed mutation inputs. Invalid client data must never reach SQLite or become a 500."""

from pydantic import BaseModel, ConfigDict, Field


class Payload(BaseModel):
    model_config = ConfigDict(strict=True)


class Credentials(Payload):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class RunPath(Payload):
    path: str = Field(min_length=1)
    name: str = ""


class RunName(Payload):
    name: str = Field(min_length=1, max_length=120)


class UserUpdate(Payload):
    status: str = "pending"
    is_admin: bool = False


class RunShare(Payload):
    email: str
    permission: str | None = None


class RowAction(Payload):
    row_id: str = Field(min_length=1)


class DecisionInput(RowAction):
    decision: str
    comment: str = ""
    override_classification: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)


class ApprovalInput(RowAction):
    final_decision: str
    note: str = ""
    expected_revision: int | None = Field(default=None, ge=0)
    confirm_self_approval: bool = False


class RowRelationship(RowAction):
    canonical: str = ""
    aliases: list[str] = Field(default_factory=list)
    scope: str = "global"
    doc_types: list[str] = Field(default_factory=list)
    anchor: bool = False
    notes: str = ""


class MiningInput(Payload):
    a_key: str
    b_key: str
    scope: str = "global"
    anchor: bool = False
    notes: str = ""
    note: str = ""


class ActionInput(RowAction):
    owner: str = ""


class ActionUpdate(Payload):
    status: str = "OPEN"
    owner: str = ""
    note: str = ""


class RelationshipInput(Payload):
    canonical: str
    aliases: list[str] = Field(default_factory=list)
    scope: str = "global"
    doc_types: list[str] = Field(default_factory=list)
    item_anchors: list[str] = Field(default_factory=list)
    provenance: str = "manual"
    notes: str = ""


class RelationshipUpdate(RelationshipInput):
    canonical: str = ""
    note: str = ""


class ChangeNote(Payload):
    note: str = ""
