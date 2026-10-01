"""Persistent, versioned terminology. Every change appends a version; historical runs reconstruct exactly."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaizen.models import DocType, Relationship
from kaizen.storage.db import Database
from kaizen.terminology.store import _DEFAULT_PATH, _ID_RE, RelationshipStore

_FIELDS = ("id", "canonical", "aliases", "scope", "doc_types", "item_anchors", "provenance", "created_by", "created_at", "updated_at", "active", "notes", "version")


@dataclass(frozen=True)
class VersionRecord:
    id: str
    version: int
    change_type: str
    changed_by: str
    changed_at: datetime
    change_note: str
    payload: Relationship


@dataclass(frozen=True)
class RunRelationship:
    relationship: Relationship
    used_count: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_rel(row) -> Relationship:
    return Relationship(
        id=row["id"], canonical=row["canonical"], aliases=json.loads(row["aliases"]), scope=row["scope"],
        doc_types=[DocType(d) for d in json.loads(row["doc_types"])], item_anchors=json.loads(row["item_anchors"]),
        provenance=row["provenance"], created_by=row["created_by"], created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]), active=bool(row["active"]), notes=row["notes"], version=row["version"],
    )


class TerminologyRepository:
    def __init__(self, db: Database | Path | str):
        self.db = db if isinstance(db, Database) else Database(db)
        self.conn = self.db.conn

    # ---- seeding ---------------------------------------------------------------------------------
    def initialize(self, seed: Path | None = None) -> int:
        """Seed packaged defaults into an empty database. Returns the number of relationships seeded."""
        n = self.conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        v = self.conn.execute("SELECT COUNT(*) FROM relationship_versions").fetchone()[0]
        if n or v:
            return 0
        store = RelationshipStore.load(seed or _DEFAULT_PATH)
        count = 0
        for rel in store.all(active_only=False):
            self._insert(rel, change_type="seed", changed_by=rel.created_by, change_note="packaged default")
            count += 1
        self.conn.commit()
        return count

    def sync_defaults(self, seed: Path | None = None, changed_by: str = "system") -> tuple[int, int]:
        """Add packaged default relationships that are missing from this workspace (by ID) and refresh
        defaults that were never edited (still at version 1 with a different payload). Returns (added, refreshed).
        Relationships the user has edited (version > 1) are never touched."""
        store = RelationshipStore.load(seed or _DEFAULT_PATH)
        added = refreshed = 0
        for rel in store.all(active_only=False):
            current = self.get(rel.id)
            if current is None:
                if self.history(rel.id):
                    continue  # deleted on purpose in this workspace; do not resurrect
                self._insert(rel, "seed", changed_by, "added from packaged defaults")
                added += 1
            elif current.version == 1 and (current.canonical, current.aliases, current.scope, current.item_anchors, current.doc_types, current.notes) != (rel.canonical, rel.aliases, rel.scope, rel.item_anchors, rel.doc_types, rel.notes):
                self.update(rel.id, changed_by, "refreshed from packaged defaults", canonical=rel.canonical, aliases=rel.aliases, scope=rel.scope, item_anchors=rel.item_anchors, doc_types=rel.doc_types, notes=rel.notes)
                refreshed += 1
        self.conn.commit()
        return added, refreshed

    # ---- reads -----------------------------------------------------------------------------------
    def list(self, active_only: bool = False, scope: str | None = None, search: str | None = None) -> list[Relationship]:
        rels = [_row_to_rel(r) for r in self.conn.execute("SELECT * FROM relationships ORDER BY id")]
        if active_only:
            rels = [r for r in rels if r.active]
        if scope:
            rels = [r for r in rels if r.scope == scope]
        if search:
            s = search.lower()
            rels = [r for r in rels if s in r.canonical.lower() or any(s in a.lower() for a in r.aliases) or s in r.id.lower() or s in r.notes.lower() or any(s in a.lower() for a in r.item_anchors)]
        return rels

    def get(self, rel_id: str) -> Relationship | None:
        row = self.conn.execute("SELECT * FROM relationships WHERE id = ?", (rel_id,)).fetchone()
        return _row_to_rel(row) if row else None

    def get_version(self, rel_id: str, version: int) -> Relationship | None:
        row = self.conn.execute("SELECT payload FROM relationship_versions WHERE id = ? AND version = ?", (rel_id, version)).fetchone()
        return Relationship.model_validate_json(row["payload"]) if row else None

    def history(self, rel_id: str) -> list[VersionRecord]:
        rows = self.conn.execute("SELECT * FROM relationship_versions WHERE id = ? ORDER BY version, changed_at", (rel_id,)).fetchall()
        return [VersionRecord(r["id"], r["version"], r["change_type"], r["changed_by"], datetime.fromisoformat(r["changed_at"]), r["change_note"], Relationship.model_validate_json(r["payload"])) for r in rows]

    def next_id(self) -> str:
        ids = [r[0] for r in self.conn.execute("SELECT id FROM relationships UNION SELECT id FROM relationship_versions")]
        nums = [int(m.group(1)) for rid in ids if (m := _ID_RE.match(rid))]
        return f"REL-{(max(nums) + 1 if nums else 1):03d}"

    def store(self) -> RelationshipStore:
        return RelationshipStore(self.list(active_only=True))

    # ---- writes ----------------------------------------------------------------------------------
    def _insert(self, rel: Relationship, change_type: str, changed_by: str, change_note: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO relationships (id,canonical,aliases,scope,doc_types,item_anchors,provenance,created_by,created_at,updated_at,active,notes,version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rel.id, rel.canonical, json.dumps(rel.aliases), rel.scope, json.dumps([d.value for d in rel.doc_types]), json.dumps(rel.item_anchors), rel.provenance, rel.created_by, rel.created_at.isoformat(), rel.updated_at.isoformat(), int(rel.active), rel.notes, rel.version),
        )
        self._record_version(rel, change_type, changed_by, change_note)

    def _record_version(self, rel: Relationship, change_type: str, changed_by: str, change_note: str) -> None:
        self.conn.execute(
            "INSERT INTO relationship_versions (id,version,payload,change_type,changed_by,changed_at,change_note) VALUES (?,?,?,?,?,?,?)",
            (rel.id, rel.version, rel.model_dump_json(), change_type, changed_by, _now().isoformat(), change_note),
        )
        self.conn.execute("INSERT INTO audit (at, actor, action, detail) VALUES (?,?,?,?)", (_now().isoformat(), changed_by, f"relationship.{change_type}", f"{rel.id} v{rel.version}: {change_note}"))

    def create(self, canonical: str, aliases=(), scope: str = "global", doc_types=(), item_anchors=(), provenance: str = "manual", created_by: str = "system", notes: str = "", rel_id: str | None = None, active: bool = True) -> Relationship:
        now = _now()
        with self.db.transaction():
            rel = Relationship(id=rel_id or self.next_id(), canonical=canonical, aliases=list(aliases), scope=scope, doc_types=[DocType(d) for d in doc_types], item_anchors=list(item_anchors), provenance=provenance, created_by=created_by, created_at=now, updated_at=now, notes=notes, version=1, active=active)
            if self.get(rel.id) is not None or self.history(rel.id):
                raise ValueError(f"Relationship {rel.id} already exists or has recorded history; use a new ID.")
            self._insert(rel, "create", created_by, notes or "created")
            self.conn.commit()
        return rel

    def update(self, rel_id: str, changed_by: str, change_note: str = "", **fields: Any) -> Relationship:
        fields.pop("id", None)
        fields.pop("version", None)
        if "doc_types" in fields:
            fields["doc_types"] = [DocType(d) for d in fields["doc_types"]]
        with self.db.transaction():
            current = self.get(rel_id)
            if current is None:
                raise KeyError(rel_id)
            updated = Relationship.model_validate({**current.model_dump(), **fields, "updated_at": _now(), "version": current.version + 1})
            self._insert(updated, "update", changed_by, change_note or "updated")
            self.conn.commit()
        return updated

    def deactivate(self, rel_id: str, changed_by: str, change_note: str = "") -> Relationship:
        with self.db.transaction():
            rel = self.update(rel_id, changed_by, change_note or "deactivated", active=False)
            self.conn.execute("UPDATE relationship_versions SET change_type = 'deactivate' WHERE id = ? AND version = ?", (rel.id, rel.version))
        return rel

    def activate(self, rel_id: str, changed_by: str, change_note: str = "") -> Relationship:
        with self.db.transaction():
            rel = self.update(rel_id, changed_by, change_note or "activated", active=True)
            self.conn.execute("UPDATE relationship_versions SET change_type = 'activate' WHERE id = ? AND version = ?", (rel.id, rel.version))
        return rel

    def delete(self, rel_id: str, changed_by: str, change_note: str = "") -> None:
        with self.db.transaction():
            current = self.get(rel_id)
            if current is None:
                raise KeyError(rel_id)
            tomb = current.model_copy(update={"version": current.version + 1, "updated_at": _now(), "active": False})
            self._record_version(tomb, "delete", changed_by, change_note or "deleted")
            self.conn.execute("DELETE FROM relationships WHERE id = ?", (rel_id,))

    # ---- run linkage -----------------------------------------------------------------------------
    def record_run_usage(self, run_id: str, usage: dict[str, int], snapshot: list[dict] | None = None) -> None:
        rows = []
        relationships = [Relationship.model_validate(r) for r in snapshot] if snapshot is not None else self.list(active_only=True)
        for rel in relationships:
            rows.append((run_id, rel.id, rel.version, int(usage.get(rel.id, 0))))
        known = {r[1] for r in rows}
        for rel_id, count in usage.items():
            if rel_id not in known:
                rel = self.get(rel_id)
                if rel:
                    rows.append((run_id, rel_id, rel.version, int(count)))
        self.conn.execute("DELETE FROM run_relationships WHERE run_id = ?", (run_id,))
        self.conn.executemany("INSERT INTO run_relationships (run_id,relationship_id,version,used_count) VALUES (?,?,?,?)", rows)
        self.conn.commit()

    def relationships_for_run(self, run_id: str) -> list[RunRelationship]:
        out = []
        pinned = {}
        record = self.conn.execute("SELECT json_path FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if record and Path(record['json_path']).is_file():
            payload = json.loads(Path(record['json_path']).read_text(encoding='utf-8'))
            pinned = {r['id']: Relationship.model_validate(r) for r in payload.get('terminology_snapshot', [])}
        for r in self.conn.execute("SELECT * FROM run_relationships WHERE run_id = ? ORDER BY relationship_id", (run_id,)):
            rel = pinned.get(r["relationship_id"]) or self.get_version(r["relationship_id"], r["version"])
            if rel is not None:
                out.append(RunRelationship(rel, r["used_count"]))
        return out

    def usage_counts(self) -> dict[str, int]:
        return {r["relationship_id"]: r["total"] for r in self.conn.execute("SELECT relationship_id, SUM(used_count) AS total FROM run_relationships GROUP BY relationship_id")}
