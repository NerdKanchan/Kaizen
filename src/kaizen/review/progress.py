"""Current review progress alongside the immutable automated recommendations."""

from collections import Counter

from kaizen.models import Run
from kaizen.review.store import ReviewStore

SEVERITY_RANK = {"BLOCKER": 0, "MAJOR": 1, "MINOR": 2, "INFO": 3}
CLEAR_CLASSIFICATIONS = {"EXACT", "EQUIVALENT"}


def review_snapshot(run: Run, review: ReviewStore, viewer_slot: int = 1, blind: bool = False):
    # Counts, filters and approval metadata must describe the same committed snapshot.
    with review.db.lock:
        rows = review.rows_for_viewer(run.metadata.run_id, run.results, viewer_slot, blind)
    progress = dict(pending=0, awaiting_review=0, awaiting_approval=0, approved=0,
                    needs_information=0, unresolved_rows=0, confirmed_discrepancies=0,
                    blockers=0, low_confidence_rows=0)
    states = Counter()
    types = {}
    for result, row in zip(run.results, rows):
        decision = next((row["decisions"][slot] for slot in (2, 1) if row["decisions"][slot]), None)
        final = row["final"]
        kind = final["final_decision"] if final else decision["decision"] if decision else None
        needs_information = kind == "NEEDS_MORE_INFORMATION"
        pending = needs_information or (not final and (result.requires_validation or decision is not None))
        # Approval acknowledges a recommendation. A confirmed mismatch still needs correction;
        # an approved exact/equivalent assessment clears the finding, preserving the engine record.
        cleared = bool(final and kind in ("ACCEPT", "OVERRIDE") and row["effective_classification"] in CLEAR_CLASSIFICATIONS)
        discrepancies = [d.model_dump(mode="json") for d in result.discrepancies
                         if not cleared and (d.severity.value != "INFO" or result.requires_validation)]
        if final and not cleared and kind in ("OVERRIDE", "CONFIRM_DISCREPANCY") and not discrepancies:
            discrepancies.append({"type": "REVIEWER_FINDING", "severity": "BLOCKER" if row["effective_classification"] == "MISSING" else "MAJOR", "detail": "Approved reviewer finding", "recommended_action": "Correct the confirmed finding."})
        if needs_information and not discrepancies:
            discrepancies.append({"type": "NEEDS_MORE_INFORMATION", "severity": "MINOR", "detail": "Reviewer requested more information", "recommended_action": "Supply the requested information and review again."})
        row["pending_review"] = bool(pending)
        row["unresolved"] = bool(discrepancies)
        row["current_discrepancies"] = discrepancies
        row["current_severity"] = min((d["severity"] for d in discrepancies), key=SEVERITY_RANK.get, default=None)
        states[row["state"]] += 1
        progress["approved"] += bool(final)
        progress["pending"] += bool(pending)
        progress["awaiting_review"] += bool(pending and not decision and not final)
        progress["awaiting_approval"] += bool(pending and decision and not final)
        progress["needs_information"] += needs_information
        progress["unresolved_rows"] += bool(discrepancies)
        progress["confirmed_discrepancies"] += bool(final and discrepancies and not needs_information)
        progress["blockers"] += row["current_severity"] == "BLOCKER"
        progress["low_confidence_rows"] += any(d["type"] == "LOW_EXTRACTION_CONFIDENCE" for d in discrepancies)
        for dtype in {d["type"] for d in discrepancies}:
            severity = min((d["severity"] for d in discrepancies if d["type"] == dtype), key=SEVERITY_RANK.get)
            entry = types.setdefault(dtype, {"type": dtype, "count": 0, "severity": severity})
            entry["count"] += 1
            if SEVERITY_RANK[severity] < SEVERITY_RANK[entry["severity"]]:
                entry["severity"] = severity
    progress["discrepancies"] = sorted(types.values(), key=lambda d: (SEVERITY_RANK[d["severity"]], -d["count"], d["type"]))
    return rows, progress, {state: states[state] for state in ("ENGINE_RECOMMENDED", "REVIEWED", "FINALIZED")}
