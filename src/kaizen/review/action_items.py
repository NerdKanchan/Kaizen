"""Action items from confirmed discrepancies, linked to the originating result, with verify & close across runs
via a stable comparison key (never file names or timestamps)."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from kaizen.matching.normalize import normalize
from kaizen.models import CheckResult, Discrepancy, Run, Severity
from kaizen.storage.db import Database

STATUSES = ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED", "REJECTED")


def comparison_key(r: CheckResult) -> str:
    """Semantic identity of a comparison: check, SKU and the A-side identity (item number or normalised text),
    or the B-side text for B-only rows. Stable across runs and independent of row ids."""
    if r.role in ("header", "reference"):
        return f"{r.check.value}|{r.sku}|{r.role}"
    if r.source_a is not None:
        att = r.source_a.attributes
        if att.get("kind") == "change":
            return f"{r.check.value}|{r.sku}|A:{att.get('change_key')}"
        if att.get("kind") == "affected_code":
            return f"{r.check.value}|{r.sku}|coverage"
        ident = r.source_a.item_number or normalize(r.source_a.description).sorted_key
        return f"{r.check.value}|{r.sku}|A:{ident}"
    if r.source_b is not None:
        return f"{r.check.value}|{r.sku}|B:{normalize(r.source_b.description).sorted_key}"
    return f"{r.check.value}|{r.sku}|{r.row_id}"


@dataclass
class ActionItem:
    id: str
    run_id: str
    row_id: str
    sku: str
    check_type: str
    discrepancy_type: str
    severity: str
    detail: str
    recommended_action: str
    owner: str
    status: str
    reviewer: str
    created_at: str
    updated_at: str
    resolved_in_run: str = ""
    resolved_at: str = ""
    comparison_key: str = ""


@dataclass
class VerifyOutcome:
    run_id: str
    resolved: list[str] = field(default_factory=list)
    still_open: list[str] = field(default_factory=list)
    not_covered: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ActionItemStore:
    def __init__(self, db: Database):
        self.db = db
        self.conn = db.conn

    def next_id(self) -> str:
        ids = [r[0] for r in self.conn.execute("SELECT id FROM action_items")]
        nums = [int(i.split("-")[1]) for i in ids if i.startswith("AI-") and i.split("-")[1].isdigit()]
        return f"AI-{(max(nums) + 1 if nums else 1):03d}"

    def create_from_result(self, run: Run, result: CheckResult, reviewer: str, owner: str = "", discrepancy: Discrepancy | None = None) -> ActionItem:
        disc = discrepancy or next((d for d in result.discrepancies if d.severity is not Severity.INFO), None) or (result.discrepancies[0] if result.discrepancies else None)
        if disc is None:
            raise ValueError("the result has no discrepancy to act on")
        now = _now()
        ai = ActionItem(self.next_id(), run.metadata.run_id, result.row_id, result.sku, result.check.value, disc.type.value, disc.severity.value, disc.detail, disc.recommended_action, owner, "OPEN", reviewer, now, now, comparison_key=comparison_key(result))
        with self.db.lock:
            return self._insert(ai, reviewer)

    def _insert(self, ai: ActionItem, reviewer: str) -> ActionItem:
        self.conn.execute("INSERT INTO action_items (id, run_id, row_id, sku, check_type, discrepancy_type, severity, detail, recommended_action, owner, status, reviewer, created_at, updated_at, resolved_in_run, comparison_key, resolved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (ai.id, ai.run_id, ai.row_id, ai.sku, ai.check_type, ai.discrepancy_type, ai.severity, ai.detail, ai.recommended_action, ai.owner, ai.status, ai.reviewer, ai.created_at, ai.updated_at, "", ai.comparison_key, ""))
        self.db.audit(reviewer, "action_item.created", f"{ai.id} from {ai.run_id} {ai.row_id}: {ai.discrepancy_type} ({ai.severity})")
        self.conn.commit()
        return ai

    def _row(self, r) -> ActionItem:
        return ActionItem(r["id"], r["run_id"], r["row_id"], r["sku"], r["check_type"], r["discrepancy_type"], r["severity"], r["detail"], r["recommended_action"], r["owner"], r["status"], r["reviewer"], r["created_at"], r["updated_at"], r["resolved_in_run"], r["resolved_at"], r["comparison_key"])

    def get(self, ai_id: str) -> ActionItem | None:
        r = self.conn.execute("SELECT * FROM action_items WHERE id = ?", (ai_id,)).fetchone()
        return self._row(r) if r else None

    def for_run(self, run_id: str) -> list[ActionItem]:
        return [self._row(r) for r in self.conn.execute("SELECT * FROM action_items WHERE run_id = ? ORDER BY id", (run_id,))]

    def for_row(self, run_id: str, row_id: str) -> list[ActionItem]:
        return [self._row(r) for r in self.conn.execute("SELECT * FROM action_items WHERE run_id = ? AND row_id = ? ORDER BY id", (run_id, row_id))]

    def list(self, status: str | None = None) -> list[ActionItem]:
        q = "SELECT * FROM action_items" + (" WHERE status = ?" if status else "") + " ORDER BY id"
        return [self._row(r) for r in self.conn.execute(q, (status,) if status else ())]

    def update(self, ai_id: str, by: str, status: str | None = None, owner: str | None = None, note: str = "") -> ActionItem:
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        current = self.get(ai_id)
        if current is None:
            raise KeyError(ai_id)
        new_status = status or current.status
        new_owner = owner if owner is not None else current.owner
        with self.db.lock:
            self.conn.execute("UPDATE action_items SET status = ?, owner = ?, updated_at = ? WHERE id = ?", (new_status, new_owner, _now(), ai_id))
            self.db.audit(by, "action_item.updated", f"{ai_id}: status {new_status}, owner {new_owner} {note}".strip())
            self.conn.commit()
        return self.get(ai_id)

    def verify_and_close(self, run: Run, by: str = "system", allowed_run_ids: set[str] | None = None) -> VerifyOutcome:
        """After a corrective rerun: an open item is RESOLVED when the run covers its SKU and no row with the
        same comparison key still carries a non-informational discrepancy."""
        outcome = VerifyOutcome(run.metadata.run_id)
        covered = {g.sku for g in run.groups} | {r.sku for r in run.results}
        open_keys: dict[str, bool] = {}
        for r in run.results:
            k = comparison_key(r)
            open_keys[k] = open_keys.get(k, False) or any(d.severity is not Severity.INFO for d in r.discrepancies)
        for ai in self.list():
            if allowed_run_ids is not None and ai.run_id not in allowed_run_ids:
                continue
            if ai.status not in ("OPEN", "IN_PROGRESS"):
                continue
            if ai.sku not in covered:
                outcome.not_covered.append(ai.id)
                continue
            if open_keys.get(ai.comparison_key, False):
                outcome.still_open.append(ai.id)
                continue
            now = _now()
            self.conn.execute("UPDATE action_items SET status = 'RESOLVED', resolved_in_run = ?, resolved_at = ?, updated_at = ? WHERE id = ?", (run.metadata.run_id, now, now, ai.id))
            self.db.audit(by, "action_item.resolved", f"{ai.id} resolved by run {run.metadata.run_id} (comparison {ai.comparison_key} no longer shows a discrepancy)")
            outcome.resolved.append(ai.id)
        self.conn.commit()
        return outcome
