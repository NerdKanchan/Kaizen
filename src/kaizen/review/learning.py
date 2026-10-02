"""Closed-testing labels, immutable SKU splits and locally curated datasets.

Review events already capture normal work. A separate annotation is needed for real
pairing ground truth: accepting an engine finding is not proof that its pair is right.
"""

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kaizen.checks.base import pair_token
from kaizen.checks.bom_drawing import callouts, drawing_relevant_bom_items
from kaizen.checks.bom_label import comparable_bom_items
from kaizen.ingest.grouping import identity_key
from kaizen.matching.attributes import extract_attributes
from kaizen.models import DiscrepancyType, DocType, Run
from kaizen.review.collaborative import CollaborativeReviewStore
from kaizen.storage.db import Database
from kaizen.terminology.repository import TerminologyRepository


def now():
    return datetime.now(timezone.utc).isoformat()


class AttributeLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    component_type: str | None = Field(default=None, max_length=100)
    dimensions_mm: list[float] = Field(default_factory=list, max_length=3)
    gauge: float | None = Field(default=None, gt=0)
    concentration_pct: float | None = Field(default=None, ge=0, le=100)
    pack_quantity: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def positive_dimensions(self):
        if any(x <= 0 for x in self.dimensions_mm):
            raise ValueError("Dimensions must be positive millimetres.")
        return self


class GroundTruthInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    expected_version: int = Field(ge=0)
    review_revision: int = Field(ge=0)
    verdict: Literal["CORRECT_PAIR", "INCORRECT_PAIR", "GENUINE_DISCREPANCY", "UNRESOLVED"]
    classification: Literal["EXACT", "EQUIVALENT", "POTENTIAL", "MISMATCH", "MISSING"]
    expected_a_ids: list[str] = Field(max_length=30)
    expected_b_ids: list[str] = Field(max_length=30)
    discrepancies: list[str] = Field(default_factory=list, max_length=20)
    attributes: dict[str, AttributeLabel] = Field(default_factory=dict, max_length=60)
    # BOM item id -> component quantity required per one label assembly.
    assembly_quantities: dict[str, float] = Field(default_factory=dict, max_length=30)
    note: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def consistency(self):
        for values in (self.expected_a_ids, self.expected_b_ids, self.discrepancies):
            if len(set(values)) != len(values):
                raise ValueError("Do not repeat item ids or discrepancy types.")
        if not self.note.strip():
            raise ValueError("Explain the evidence behind this annotation.")
        for kind in self.discrepancies:
            DiscrepancyType(kind)
        if self.verdict != "UNRESOLVED":
            if not self.expected_a_ids and not self.expected_b_ids:
                raise ValueError("Identify at least one source item.")
            if self.classification == "POTENTIAL":
                raise ValueError("An uncertain classification belongs in Unresolved.")
            if self.classification in ("EXACT", "EQUIVALENT") and (self.discrepancies or not self.expected_a_ids or not self.expected_b_ids):
                raise ValueError("A clear match needs both sources and no discrepancies.")
            if self.classification in ("MISMATCH", "MISSING") and not self.discrepancies:
                raise ValueError("Select the genuine discrepancy types.")
            if self.classification == 'MISMATCH' and (not self.expected_a_ids or not self.expected_b_ids):
                raise ValueError("A mismatch needs both sources; an absent counterpart is Missing.")
            if self.verdict == "GENUINE_DISCREPANCY" and self.classification not in ("MISMATCH", "MISSING"):
                raise ValueError("A genuine discrepancy must be Mismatch or Missing.")
            if self.classification == "MISSING" and bool(self.expected_a_ids) == bool(self.expected_b_ids):
                raise ValueError("Missing means exactly one source side is absent.")
        if any(q <= 0 for q in self.assembly_quantities.values()):
            raise ValueError("Assembly allocations must be positive quantities per label unit.")
        return self


class DrawingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=0)
    doc_id: str
    applicability: Literal["CONFIRMED_RELEASED", "NOT_APPLICABLE", "UNCONFIRMED"]
    released_revision: str = Field(max_length=100)
    release_reference: str = Field(max_length=1000)
    note: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def release_evidence(self):
        if self.applicability == "CONFIRMED_RELEASED" and (not self.released_revision.strip() or not self.release_reference.strip()):
            raise ValueError("Confirm the released revision and provide its release record reference.")
        if not self.note.strip():
            raise ValueError("Add a drawing applicability note.")
        return self


class LabelApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1)
    approve: bool
    note: str = Field(default="", max_length=4000)


def _sku_key(sku):
    return identity_key(sku).strip().upper()


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _record(row):
    if row is None:
        return None
    data = dict(row)
    data["payload"] = json.loads(data["payload"])
    return data


class LearningStore:
    def __init__(self, db: Database):
        self.db, self.conn = db, db.conn
        self.review = CollaborativeReviewStore(db)

    def enrolled(self, run_id):
        return self.conn.execute("SELECT 1 FROM learning_enrollments WHERE run_id=?", (run_id,)).fetchone() is not None

    def enroll(self, run: Run, actor: str):
        rid = run.metadata.run_id
        keys = sorted({_sku_key(g.sku) for g in run.groups})
        if not keys or any(k in ("", "UNKNOWN") for k in keys):
            raise ValueError("Resolve the product identities before enabling closed testing.")
        with self.db.transaction():
            if self.enrolled(rid):
                return
            existing = {r["sku_key"]: r["split"] for r in self.conn.execute("SELECT * FROM learning_partitions")}
            new = sorted(set(keys) - set(existing), key=lambda k: _digest(["kaizen-closed-test-v1", k]))
            # At least one whole SKU is held out when the first delivery has 2+ SKUs.
            # Existing assignments never move, including copied and re-uploaded runs.
            holdouts = math.ceil(len(new) * 0.2) if len(new) > 1 else 0
            if new and len(existing) + len(new) > 1 and "evaluation" not in existing.values():
                holdouts = max(1, holdouts)
            assignments = {**existing, **{key: "evaluation" if i < holdouts else "train" for i, key in enumerate(new)}}
            document_splits = {r["sha256"]: r["split"] for r in self.conn.execute("SELECT * FROM learning_documents")}
            # Identical BOM/label sources must stay in one split even if uploaded under
            # another SKU name. Shared packaging drawings are applicability evidence.
            sources = {key: set() for key in keys}
            for group in run.groups:
                sources[_sku_key(group.sku)].update(d.sha256 for d in run.documents if d.id in group.document_ids and d.doc_type in (DocType.BOM, DocType.LABEL))
            for _ in range(len(keys) + 1):
                changed = False
                for _key, hashes in sources.items():
                    related = [k for k in keys if hashes & sources[k]]
                    if not related:
                        continue
                    fixed = {existing[k] for k in related if k in existing} | {document_splits[h] for h in hashes if h in document_splits}
                    if len(fixed) > 1:
                        raise ValueError("Duplicate source documents cross existing dataset splits. Supply distinct SKU sources.")
                    chosen = next(iter(fixed)) if fixed else "evaluation" if any(assignments[k] == "evaluation" for k in related) else "train"
                    for k in related:
                        if k in existing and assignments[k] != chosen:
                            raise ValueError("A duplicate source conflicts with an immutable SKU split.")
                        if assignments[k] != chosen:
                            assignments[k] = chosen
                            changed = True
                if not changed:
                    break
            for key in new:
                self.conn.execute("INSERT INTO learning_partitions VALUES (?,?,?)", (key, assignments[key], now()))
            for key, hashes in sources.items():
                for sha in hashes:
                    self.conn.execute("INSERT OR IGNORE INTO learning_documents VALUES (?,?)", (sha, assignments[key]))
            self.conn.execute("INSERT INTO learning_enrollments VALUES (?,?,?)", (rid, actor, now()))
            self.db.audit(actor, "learning.enrolled", rid)

    def split(self, sku):
        row = self.conn.execute("SELECT split FROM learning_partitions WHERE sku_key=?", (_sku_key(sku),)).fetchone()
        return row[0] if row else None

    def require_enrolled(self, run):
        if not self.enrolled(run.metadata.run_id):
            raise ValueError("The run owner must enable closed testing first.")

    def review_changed(self, rid, row_id, revision):
        events = self.conn.execute("SELECT payload FROM review_events WHERE run_id=? AND row_id=? AND seq>?", (rid, row_id, revision))
        # Approval of the same decision does not change pairing evidence.
        return any(json.loads(e[0]).get('event') != 'approval' for e in events)

    def current(self, table, rid, key):
        column = "row_id" if table == "learning_labels" else "sku"
        return _record(self.conn.execute(f"SELECT * FROM {table} WHERE run_id=? AND {column}=? ORDER BY version DESC LIMIT 1", (rid, key)).fetchone())

    def records(self, table, rid):
        column = "row_id" if table == "learning_labels" else "sku"
        return [_record(r) for r in self.conn.execute(f"SELECT t.* FROM {table} t WHERE run_id=? AND version=(SELECT MAX(version) FROM {table} x WHERE x.run_id=t.run_id AND x.{column}=t.{column}) ORDER BY {column}", (rid,))]

    def documents_for_row(self, run, row):
        types = {"BOM_LABEL": (DocType.BOM, DocType.LABEL), "BOM_DRAWING": (DocType.BOM, DocType.DRAWING), "LABEL_DRAWING": (DocType.LABEL, DocType.DRAWING)}
        if row.role != "item" or row.check.value not in types:
            raise ValueError("Ground-truth pairing annotations cover component rows in BOM/label/drawing checks.")
        group = next(g for g in run.groups if g.sku == row.sku)
        ta, tb = types[row.check.value]
        candidates = [d for d in run.documents if d.id in group.document_ids and d.header.get("revision_role") != "old"]
        pairs = [(a, b) for a in candidates for b in candidates if a.doc_type == ta and b.doc_type == tb
                 and (row.source_a is None or row.source_a.doc_id == a.id) and (row.source_b is None or row.source_b.doc_id == b.id)]
        token_pairs = [(a, b) for a, b in pairs if f"-{pair_token(a.id, b.id)}-" in row.row_id]
        pairs = token_pairs or pairs
        if len(pairs) != 1:
            raise ValueError("The source document pair is ambiguous. Re-run these documents before annotating.")
        return pairs[0]

    def items_for_row(self, run, row):
        a_doc, b_doc = self.documents_for_row(run, row)
        a, b = {}, {}
        for doc, dest in ((a_doc, a), (b_doc, b)):
            items = callouts(doc) if doc.doc_type == DocType.DRAWING else comparable_bom_items(doc) if doc.doc_type == DocType.BOM and row.check.value == 'BOM_LABEL' else drawing_relevant_bom_items(doc) if doc.doc_type == DocType.BOM else doc.items
            dest.update({i.id: i for i in items})
        # The engine merges duplicate BOM quantities. Preserve that comparison source.
        for r in run.results:
            if r.sku == row.sku and r.check == row.check:
                for source, dest in ((r.source_a, a), (r.source_b, b)):
                    if source and source.id in dest and source.attributes.get("merged_rows"):
                        dest[source.id] = source
        return a, b

    def row_detail(self, run, row):
        a, b = self.items_for_row(run, row)
        def option(item):
            return {"id": item.id, "doc_id": item.doc_id, "description": item.description, "item_number": item.item_number,
                    "quantity": str(item.quantity) if item.quantity is not None else None, "page": item.evidence.page,
                    "suggested_attributes": extract_attributes(item.description).to_dict()}
        return {"enabled": self.enrolled(run.metadata.run_id), "split": self.split(row.sku),
                "annotation": self.current("learning_labels", run.metadata.run_id, row.row_id),
                "a_options": [option(i) for i in a.values()], "b_options": [option(i) for i in b.values()]}

    def annotate(self, run, row, data: GroundTruthInput, actor):
        self.require_enrolled(run)
        a, b = self.items_for_row(run, row)
        if not set(data.expected_a_ids) <= a.keys() or not set(data.expected_b_ids) <= b.keys():
            raise ValueError("Choose source items from this SKU and document pair.")
        if not data.attributes.keys() <= (set(data.expected_a_ids) | set(data.expected_b_ids)):
            raise ValueError("Attribute corrections must reference the expected source items.")
        is_assembly = len(data.expected_a_ids) > 1 or len(data.expected_b_ids) > 1
        if is_assembly:
            if row.check.value != "BOM_LABEL" or len(data.expected_b_ids) != 1 or len(data.expected_a_ids) < 2:
                raise ValueError("An assembly needs multiple BOM components and one label entry.")
            if set(data.assembly_quantities) != set(data.expected_a_ids):
                raise ValueError("Allocate every assembly member's quantity per label unit.")
            if len({a[i].item_number for i in data.expected_a_ids}) != len(data.expected_a_ids):
                raise ValueError("Use each BOM item number once; duplicate BOM rows are merged by the engine.")
            if any(not a[i].item_number or not a[i].is_active or a[i].category.value != "PHYSICAL_COMPONENT" for i in data.expected_a_ids):
                raise ValueError("Assembly members must be active physical BOM components with item numbers.")
        elif data.assembly_quantities:
            raise ValueError("Assembly allocations require multiple BOM components.")
        engine_a = [row.source_a.id] if row.source_a else []
        engine_b = [row.source_b.id] if row.source_b else []
        same = data.expected_a_ids == engine_a and data.expected_b_ids == engine_b
        if data.verdict == "CORRECT_PAIR" and not same:
            raise ValueError("Use Incorrect pairing when correcting the source pairing.")
        if data.verdict == "INCORRECT_PAIR" and same:
            raise ValueError("Identify the corrected pairing or the genuinely absent source.")
        if row.source_a and row.source_a.id not in data.expected_a_ids:
            raise ValueError("Keep the reviewed A-side component; correct its counterpart. Review another row to label another component.")
        if not row.source_a and row.source_b and row.source_b.id not in data.expected_b_ids:
            raise ValueError("Keep the reviewed B-side component when identifying its BOM counterpart.")
        with self.db.transaction():
            current = self.current("learning_labels", run.metadata.run_id, row.row_id)
            version = current["version"] if current else 0
            if version != data.expected_version or data.review_revision != self.review.revision(run.metadata.run_id, row.row_id):
                raise ValueError("This row or annotation changed. Refresh before saving ground truth.")
            payload = data.model_dump(mode="json", exclude={"expected_version"})
            payload["expected_a"] = [a[i].model_dump(mode="json") for i in data.expected_a_ids]
            payload["expected_b"] = [b[i].model_dump(mode="json") for i in data.expected_b_ids]
            payload["engine"] = row.model_dump(mode="json")
            payload["compared_document_ids"] = [d.id for d in self.documents_for_row(run, row)]
            payload["sku"] = row.sku
            self.conn.execute("INSERT INTO learning_labels (run_id,row_id,version,payload,annotated_by,annotated_at) VALUES (?,?,?,?,?,?)", (run.metadata.run_id, row.row_id, version + 1, json.dumps(payload), actor, now()))
            self.db.audit(actor, "learning.annotated", f"{run.metadata.run_id} {row.row_id} v{version + 1}")
        return self.current("learning_labels", run.metadata.run_id, row.row_id)

    def drawing(self, run, sku, data: DrawingInput, actor):
        self.require_enrolled(run)
        group = next((g for g in run.groups if g.sku == sku), None)
        doc = next((d for d in run.documents if d.id == data.doc_id and d.doc_type == DocType.DRAWING), None)
        if not group or not doc or doc.id not in group.document_ids:
            raise ValueError("Choose the drawing supplied for this SKU.")
        with self.db.transaction():
            current = self.current("learning_drawings", run.metadata.run_id, sku)
            version = current["version"] if current else 0
            if version != data.expected_version:
                raise ValueError("Drawing applicability changed. Refresh before saving.")
            payload = data.model_dump(exclude={"expected_version"}) | {"sha256": doc.sha256, "drawing_number": doc.header.get("drawing_number")}
            self.conn.execute("INSERT INTO learning_drawings (run_id,sku,version,payload,annotated_by,annotated_at) VALUES (?,?,?,?,?,?)", (run.metadata.run_id, sku, version + 1, json.dumps(payload), actor, now()))
            self.db.audit(actor, "learning.drawing_annotated", f"{run.metadata.run_id} {sku} v{version + 1}")
        return self.current("learning_drawings", run.metadata.run_id, sku)

    def approve(self, table, run, key, data: LabelApproval, actor):
        self.require_enrolled(run)
        with self.db.transaction():
            record = self.current(table, run.metadata.run_id, key)
            if not record or data.expected_version != record["version"] or record["status"] != "pending":
                raise ValueError("This annotation changed or was already reviewed. Refresh first.")
            if data.approve and actor == record["annotated_by"]:
                raise ValueError("A different administrator must verify ground truth; self-approval cannot create a training label.")
            if data.approve and table == "learning_labels":
                if record["payload"]["verdict"] == "UNRESOLVED":
                    raise ValueError("Resolve the annotation before approving ground truth.")
                if self.review_changed(run.metadata.run_id, key, record["payload"]["review_revision"]):
                    raise ValueError("The review decision changed. Save a fresh annotation first.")
            if data.approve and table == "learning_drawings" and record["payload"]["applicability"] == "UNCONFIRMED":
                raise ValueError("Unconfirmed drawing applicability cannot be approved.")
            column = "row_id" if table == "learning_labels" else "sku"
            status = "approved" if data.approve else "rejected"
            self.conn.execute(f"UPDATE {table} SET status=?,approved_by=?,approved_at=?,approval_note=? WHERE run_id=? AND {column}=? AND version=?", (status, actor, now(), data.note, run.metadata.run_id, key, record["version"]))
            self.db.audit(actor, "learning." + status, f"{table} {run.metadata.run_id} {key} v{record['version']}")
        return self.current(table, run.metadata.run_id, key)

    def eligible(self, run, record):
        if record["status"] != "approved":
            return False, "Awaiting independent verification" if record["status"] == "pending" else "Rejected"
        p = record["payload"]
        if self.review_changed(run.metadata.run_id, record["row_id"], p["review_revision"]):
            return False, "Review changed; annotate and verify again"
        if p["engine"]["check"] in ("BOM_DRAWING", "LABEL_DRAWING"):
            drawing = self.current("learning_drawings", run.metadata.run_id, p["sku"])
            if not drawing or drawing["status"] != "approved" or drawing["payload"]["applicability"] != "CONFIRMED_RELEASED":
                return False, "Released drawing applicability needs verification"
            expected_docs = {i["doc_id"] for i in p["expected_b"]}
            expected_docs.add(p['compared_document_ids'][1])
            # Even a missing drawing counterpart must be judged against the reviewed drawing.
            reviewed_doc = p["engine"].get("source_b")
            if reviewed_doc:
                expected_docs.add(reviewed_doc["doc_id"])
            if expected_docs and expected_docs != {drawing["payload"]["doc_id"]}:
                return False, "This annotation concerns a different drawing"
        return True, "Verified"

    def dataset(self, run, split):
        self.require_enrolled(run)
        samples, seen, conflicts = [], {}, set()
        for record in self.records("learning_labels", run.metadata.run_id):
            p = record["payload"]
            if self.split(p["sku"]) != split or not self.eligible(run, record)[0]:
                continue
            # Source content and the reviewed anchor define an example, not row/run ids.
            engine = p["engine"]
            anchor = engine.get("source_a") or engine.get("source_b")
            key = _digest([_sku_key(p["sku"]), engine["check"], p['compared_document_ids'], anchor["evidence"]["file_sha256"], anchor["item_number"], anchor["evidence"].get("locator"), anchor["description"]])
            truth = {k: p[k] for k in ("classification", "discrepancies", "attributes", "assembly_quantities")}
            truth["sources"] = [[(i["doc_id"], i["id"]) for i in p[side]] for side in ("expected_a", "expected_b")]
            signature = _digest(truth)
            if key in seen and seen[key] != signature:
                conflicts.add(key)
            seen[key] = signature
            samples.append(record | {"sample_id": key, "split": split})
        unique = {s["sample_id"]: s for s in samples if s["sample_id"] not in conflicts}
        # Missing A and missing B can both be corrected to the same true pair.
        # Count that pair once, rather than inflating the benchmark with two anchors.
        identities, conflicting_pairs = {}, set()
        for sample in unique.values():
            p = sample['payload']
            pair = _digest([_sku_key(p['sku']), p['engine']['check'], p['compared_document_ids'], sorted(p['expected_a_ids']), sorted(p['expected_b_ids'])])
            signature = _digest({k: p[k] for k in ('classification', 'discrepancies', 'attributes', 'assembly_quantities')})
            if pair in identities and identities[pair][0] != signature:
                conflicting_pairs.add(pair)
            if pair not in identities or p['engine'].get('source_a'):
                identities[pair] = (signature, sample)
        unique = {pair: sample for pair, (_, sample) in identities.items() if pair not in conflicting_pairs}
        samples = list(unique.values())
        data = {"schema_version": 1, "run_id": run.metadata.run_id, "split": split, "samples": samples,
                "conflicting_samples_excluded": len(conflicts) + len(conflicting_pairs), "tool_version": run.metadata.tool_version,
                "terminology_version": run.metadata.terminology_version, "parser_versions": run.metadata.parser_versions,
                "thresholds": run.metadata.thresholds.model_dump(), "input_hashes": sorted({d.sha256 for d in run.documents})}
        data["dataset_version"] = _digest(data)
        return data

    def summary(self, run):
        rid = run.metadata.run_id
        labels = self.records("learning_labels", rid)
        drawings = self.records("learning_drawings", rid)
        for record in labels:
            record["eligible"], record["eligibility_note"] = self.eligible(run, record)
            record["split"] = self.split(record["payload"]["sku"])
        events = self.conn.execute("SELECT COUNT(*) FROM review_events WHERE run_id=?", (rid,)).fetchone()[0]
        decisions = self.review.all_decisions(rid)
        groups = []
        for group in run.groups:
            rows = [r for r in run.results if r.sku == group.sku and r.role == "item" and r.check.value in ("BOM_LABEL", "BOM_DRAWING", "LABEL_DRAWING")]
            relevant = [a for a in labels if a["payload"]["sku"] == group.sku]
            groups.append({"sku": group.sku, "split": self.split(group.sku), "total_rows": len(rows),
                           "reviewed_rows": sum(r.row_id in decisions for r in rows), "annotated_rows": len(relevant),
                           "verified_rows": sum(a["eligible"] for a in relevant),
                           "drawing": next((d for d in drawings if d["sku"] == group.sku), None),
                           "drawing_options": [{"id": d.id, "number": d.header.get("drawing_number"), "revision": d.header.get("revision"), "file_name": d.path.rsplit("/", 1)[-1]} for d in run.documents if d.id in group.document_ids and d.doc_type == DocType.DRAWING]})
        latest = self.conn.execute("SELECT payload FROM learning_evaluations WHERE run_id=? ORDER BY created_at DESC LIMIT 1", (rid,)).fetchone()
        latest_report = json.loads(latest[0]) if latest else None
        if latest_report and self.enrolled(rid):
            latest_report['stale'] = any(self.dataset(run, split)['dataset_version'] != latest_report[f'{split if split == "train" else "evaluation"}_dataset_version'] for split in ('train', 'evaluation'))
            latest_report['stale'] |= TerminologyRepository(self.db).store().snapshot().version != latest_report.get('source_terminology_version')
        # Include a sample of auto-cleared rows: reviewing only flagged cases biases accuracy.
        by_id = {a["row_id"]: a for a in labels}
        tasks = [r for r in run.results if r.role == "item" and r.check.value in ("BOM_LABEL", "BOM_DRAWING", "LABEL_DRAWING") and (r.row_id not in by_id or by_id[r.row_id]["status"] == "rejected")]
        buckets = {}
        for row in sorted(tasks, key=lambda r: _digest(r.row_id)):
            buckets.setdefault((row.sku, row.check.value, row.requires_validation), []).append(row)
        tasks = []
        while buckets and len(tasks) < 50:
            for key in list(buckets):
                tasks.append(buckets[key].pop(0))
                if not buckets[key]:
                    del buckets[key]
        return {"enabled": self.enrolled(rid), "review_events": events, "groups": groups, "labels": labels,
                "counts": {"annotated": len(labels), "pending": sum(a["status"] == "pending" for a in labels),
                           "verified_train": sum(a["eligible"] and a["split"] == "train" for a in labels),
                           "verified_evaluation": sum(a["eligible"] and a["split"] == "evaluation" for a in labels)},
                "tasks": [{"row_id": r.row_id, "sku": r.sku, "check": r.check.value, "classification": r.classification.value,
                           "auto_cleared": not r.requires_validation, "description": (r.source_a or r.source_b).description if r.source_a or r.source_b else ""} for r in tasks[:50]],
                "latest_evaluation": latest_report}
