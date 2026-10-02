"""Train a local, explainable candidate from verified labels; evaluate without changing live runs."""

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from kaizen.ai.providers import NullProvider
from kaizen.checks.base import pair_token
from kaizen.matching.ladder import MatchOutcome
from kaizen.matching.normalize import normalize
from kaizen.models import Classification, MatchLevel, Relationship, Severity
from kaizen.pipeline import Ingested, run_checks, save_run
from kaizen.review.learning import LearningStore, now
from kaizen.terminology.store import RelationshipStore


class RejectedPairs:
    name = "verified_negative_pairs"

    def __init__(self, pairs):
        self.pairs = pairs

    def try_match(self, a, b, ctx):
        if (a.sorted_key, b.sorted_key, tuple(t.value for t in ctx.doc_types)) in self.pairs:
            return MatchOutcome(MatchLevel.NONE, 0.0, "Verified training examples reject this component pairing; reviewer evidence required.")
        return None


def build_candidate(train, relationships):
    learned, rejected, assemblies, overrides, attribute_conflicts = [], set(), [], {}, set()
    for sample in train["samples"]:
        p = sample["payload"]
        a, b = p["expected_a"], p["expected_b"]
        engine = p["engine"]
        sources = {i["id"]: i for i in [*a, *b]}
        for item_id, attributes in p["attributes"].items():
            source = sources[item_id]
            key = (source["doc_type"], normalize(source["description"]).sorted_key)
            if key in overrides and overrides[key] != attributes:
                attribute_conflicts.add(key)
            overrides[key] = attributes
        if (p["verdict"] == "INCORRECT_PAIR" or 'DESC_MISMATCH' in p['discrepancies']) and engine.get("source_a") and engine.get("source_b"):
            ea, eb = engine["source_a"], engine["source_b"]
            rejected.add((normalize(ea["description"]).sorted_key, normalize(eb["description"]).sorted_key, (ea["doc_type"], eb["doc_type"])))
        identity_verified = (p["classification"] in ("EXACT", "EQUIVALENT") and not p["discrepancies"]) or (p['classification'] == 'MISMATCH' and set(p['discrepancies']) == {'QTY_MISMATCH'})
        if not identity_verified or not a or not b:
            continue
        if p["assembly_quantities"]:
            assemblies.append({"id": sample["sample_id"] + f":v{sample['version']}", "sku": p["sku"],
                "label_key": normalize(b[0]["description"]).sorted_key,
                "members": [{"item_number": i["item_number"], "description_key": normalize(i["description"]).sorted_key,
                             "quantity_per_unit": p["assembly_quantities"][i["id"]]} for i in a]})
        elif len(a) == len(b) == 1:
            learned.append(Relationship(id="LEARN-" + sample["sample_id"], canonical=b[0]["description"], aliases=[a[0]["description"]],
                doc_types=[a[0]["doc_type"], b[0]["doc_type"]], provenance="learned", created_by=sample["approved_by"],
                created_at=sample["approved_at"], updated_at=sample["approved_at"],
                notes=f"Shadow candidate only; verified annotation {sample['run_id']} {sample['row_id']} v{sample['version']}"))
    overrides = {k: v for k, v in overrides.items() if k not in attribute_conflicts}
    return RelationshipStore([*relationships, *learned]), assemblies, RejectedPairs(rejected), overrides


def _pair(item_a, item_b):
    return (item_a.id if item_a else None, item_b.id if item_b else None)


def score_samples(run, dataset):
    counters = Counter()
    breakdown = defaultdict(Counter)
    details = []
    for sample in dataset["samples"]:
        p = sample["payload"]
        engine = p["engine"]
        anchor_a, anchor_b = engine.get("source_a"), engine.get("source_b")
        a_ids, b_ids = set(p["expected_a_ids"]), set(p["expected_b_ids"])
        if anchor_a:
            a_ids.add(anchor_a["id"])
        if anchor_b:
            b_ids.add(anchor_b["id"])
        token = pair_token(*p['compared_document_ids'])
        rows = [r for r in run.results if r.sku == p["sku"] and r.check.value == engine["check"] and r.role == "item" and (f'-{token}-' in r.row_id or r.row_id == engine['row_id']) and
                ((r.source_a and r.source_a.id in a_ids) if anchor_a else (r.source_b and r.source_b.id in b_ids))]
        expected_pairs = {(a, b) for a in (p["expected_a_ids"] or [None]) for b in (p["expected_b_ids"] or [None])}
        actual_pairs = {_pair(r.source_a, r.source_b) for r in rows}
        pairing_ok = actual_pairs == expected_pairs
        order = {"EXACT": 0, "EQUIVALENT": 1, "POTENTIAL": 2, "MISMATCH": 3, "MISSING": 4}
        classification = max((r.classification.value for r in rows), key=order.get, default=None)
        classification_ok = classification == p["classification"]
        expected_discrepancies = set(p["discrepancies"])
        actual_discrepancies = {d.type.value for r in rows for d in r.discrepancies if d.severity != Severity.INFO or d.type.value in expected_discrepancies}
        auto_cleared = bool(rows) and all(not r.requires_validation and r.classification in (Classification.EXACT, Classification.EQUIVALENT) for r in rows)
        should_flag = bool(expected_discrepancies) or p["classification"] in ("MISMATCH", "MISSING")
        false_clear = auto_cleared and (should_flag or not pairing_ok)
        counts = {"scored_samples": 1, "pairing_correct": int(pairing_ok), "classification_correct": int(classification_ok),
                  "tp": len(expected_discrepancies & actual_discrepancies), "fp": len(actual_discrepancies - expected_discrepancies),
                  "fn": len(expected_discrepancies - actual_discrepancies), "auto_cleared": int(auto_cleared), "false_clears": int(false_clear)}
        counters.update(counts)
        breakdown[f"{p['sku']}:{engine['check']}"].update(counts)
        details.append({"sample_id": sample["sample_id"], "row_id": sample["row_id"], "sku": p["sku"], "check": engine["check"],
                        "pairing_correct": pairing_ok, "expected_classification": p["classification"], "actual_classification": classification,
                        "expected_discrepancies": sorted(expected_discrepancies), "actual_discrepancies": sorted(actual_discrepancies), "false_clear": false_clear})
    def metrics(c):
        n = c["scored_samples"]
        return {**{k: c[k] for k in ("scored_samples", "pairing_correct", "classification_correct", "tp", "fp", "fn", "auto_cleared", "false_clears")},
            "pairing_accuracy": round(c["pairing_correct"] / n, 4) if n else None,
            "classification_accuracy": round(c["classification_correct"] / n, 4) if n else None,
            "discrepancy_precision": round(c["tp"] / (c["tp"] + c["fp"]), 4) if c["tp"] + c["fp"] else None,
            "discrepancy_recall": round(c["tp"] / (c["tp"] + c["fn"]), 4) if c["tp"] + c["fn"] else None,
            "false_clear_rate": round(c["false_clears"] / c["auto_cleared"], 4) if c["auto_cleared"] else None}
    return {**metrics(counters), "per_sku_check": {key: metrics(c) for key, c in breakdown.items()}, "details": details}


def shadow_evaluate(ws, baseline, actor):
    learning = LearningStore(ws.db)
    # Freeze both datasets and terminology together. Later reviews cannot alter this report.
    with ws.db.transaction():
        train, evaluation = learning.dataset(baseline, "train"), learning.dataset(baseline, "evaluation")
        relationships = ws.repository.store().all()
    store, assemblies, negatives, overrides = build_candidate(train, relationships)
    ingested = Ingested(root=Path(baseline.metadata.input_root), documents=baseline.documents, inputs=baseline.metadata.inputs, warnings=[], audit=[])
    candidate = run_checks(ingested, store, baseline.metadata.thresholds, NullProvider(), structured=True, assembly_rules=assemblies, learning_matchers=[negatives], attribute_overrides=overrides)
    before, after = score_samples(baseline, evaluation), score_samples(candidate, evaluation)
    failures = []
    if after["scored_samples"] < 20:
        failures.append("Collect at least 20 independently verified evaluation samples.")
    if not train["samples"]:
        failures.append("Collect independently verified training samples.")
    if train["conflicting_samples_excluded"] or evaluation["conflicting_samples_excluded"]:
        failures.append("Resolve conflicting ground-truth annotations.")
    expected_checks = {r.check.value for r in baseline.results if r.role == "item" and learning.split(r.sku) == "evaluation" and r.check.value in ("BOM_LABEL", "BOM_DRAWING", "LABEL_DRAWING")}
    measured_checks = {s["payload"]["engine"]["check"] for s in evaluation["samples"]}
    if expected_checks - measured_checks:
        failures.append("Verify evaluation samples for every available component check, including drawing applicability.")
    if not any(s["payload"]["discrepancies"] for s in evaluation["samples"]):
        failures.append("Include genuine discrepancies in evaluation before assessing false-clear risk.")
    if not any(not s["payload"]["engine"]["requires_validation"] for s in evaluation["samples"]):
        failures.append("Verify some originally auto-cleared rows to measure false clears.")
    if after["false_clears"]:
        failures.append("Candidate falsely clears verified discrepancies or incorrect pairings.")
    for metric in ("pairing_correct", "classification_correct", "tp"):
        if after[metric] < before[metric]:
            failures.append(f"Candidate regresses on {metric}.")
    for metric in ("fp", "fn"):
        if after[metric] > before[metric]:
            failures.append(f"Candidate increases discrepancy {metric}.")
    for key, group in before["per_sku_check"].items():
        candidate_group = after["per_sku_check"][key]
        if candidate_group["pairing_correct"] < group["pairing_correct"] or candidate_group["classification_correct"] < group["classification_correct"]:
            failures.append(f"Candidate regresses for {key}.")
    report_id = uuid.uuid4().hex
    source_root = Path(__file__).resolve().parents[1]
    source_hash = hashlib.sha256()
    for source in sorted(source_root.rglob('*.py')):
        source_hash.update(source.relative_to(source_root).as_posix().encode())
        source_hash.update(source.read_bytes())
    report = {"id": report_id, "created_at": now(), "run_id": baseline.metadata.run_id,
              "learning_pipeline_version": 1, "candidate_code_sha256": source_hash.hexdigest(),
              "training_samples": len(train["samples"]), "train_dataset_version": train["dataset_version"], "evaluation_dataset_version": evaluation["dataset_version"],
              "baseline": before, "candidate": after, "training_fit": score_samples(candidate, train),
              "candidate_terminology_version": candidate.metadata.terminology_version,
              "source_terminology_version": RelationshipStore(relationships).snapshot().version,
              "candidate_rules": {"structured_attributes": True, "learned_relationships": sum(r.id.startswith("LEARN-") for r in store.all()), "assemblies": len(assemblies), "attribute_patterns": len(overrides), "rejected_pairs": len(negatives.pairs)},
              "gate_passed": not failures, "gate_reasons": failures,
              "scope_note": "Metrics cover independently verified samples only; training-fit metrics are not held-out accuracy. Live runs are unchanged. This is an offline rule-learning candidate, not external AI fine-tuning."}
    folder = ws.runs_dir / baseline.metadata.run_id / "learning" / report_id
    folder.mkdir(parents=True, exist_ok=True)
    save_run(candidate, folder / "candidate.json")
    config = {"structured": True, "assembly_rules": assemblies, "rejected_pairs": sorted(negatives.pairs), "attribute_overrides": [{"doc_type": k[0], "description_key": k[1], "attributes": v} for k, v in sorted(overrides.items())]}
    (folder / "candidate-config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    for name, payload in (("train.json", train), ("evaluation.json", evaluation), ("report.json", report), ("assemblies.json", assemblies)):
        (folder / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    ws.db.conn.execute("INSERT INTO learning_evaluations VALUES (?,?,?,?,?)", (report_id, baseline.metadata.run_id, actor, report["created_at"], json.dumps(report)))
    ws.db.audit(actor, "learning.shadow_evaluated", f"{baseline.metadata.run_id} {report_id}; gate={report['gate_passed']}")
    ws.db.conn.commit()
    return report
