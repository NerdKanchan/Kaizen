"""One shared review per row, with append-only changes and explicit approvals."""
import json
from dataclasses import asdict

from kaizen.review.store import ReviewStore


class CollaborativeReviewStore(ReviewStore):
    def _atomic(self):
        return self.db.transaction()

    def bulk_accept_clean(self, run_id, results, slot, reviewer):
        # Keep the initial "not reviewed" snapshot and every write together. Another editor must
        # not have their decision overwritten between the snapshot and the bulk operation.
        with self._atomic():
            return super().bulk_accept_clean(run_id, results, slot, reviewer)

    @staticmethod
    def state_of(decisions, final):
        return 'FINALIZED' if final else ('REVIEWED' if decisions else 'ENGINE_RECOMMENDED')

    def revision(self, run_id, row_id):
        # Includes approvals so an editor cannot silently overwrite a newly approved row.
        row = self.conn.execute('SELECT MAX(seq) FROM review_events WHERE run_id=? AND row_id=?', (run_id, row_id)).fetchone()
        return row[0] or 0

    def _event(self, run_id, row_id, payload):
        self.conn.execute('INSERT INTO review_events (run_id,row_id,payload) VALUES (?,?,?)', (run_id, row_id, json.dumps(payload)))

    def decide(self, run_id, row_id, slot, reviewer, decision, comment='', override_classification=None, blind=False, now=None, timed=True):
        with self._atomic():
            if not self.revision(run_id, row_id):
                for old in super().history(run_id, row_id)[1:]:
                    self._event(run_id, row_id, old)
            d = super().decide(run_id, row_id, 1, reviewer, decision, comment, override_classification, False, now, timed, commit=False)
            # A change invalidates the previous approval, preserving it in history.
            self.conn.execute('DELETE FROM finals WHERE run_id=? AND row_id=?', (run_id, row_id))
            self.conn.execute('DELETE FROM decisions WHERE run_id=? AND row_id=? AND reviewer_slot != 1', (run_id, row_id))
            self._event(run_id, row_id, {'event': 'change', **asdict(d)})
        return d

    def approve(self, run_id, row_id, final_decision, actor, note, expected_revision, confirmed):
        with self._atomic():
            if expected_revision != self.revision(run_id, row_id):
                raise ValueError('This row changed. Refresh and review the latest changes before approving.')
            decisions = self.decisions(run_id, row_id)
            if not decisions:
                raise ValueError('Record a review decision before approving.')
            current = max(decisions.values(), key=lambda d: d.decided_at)
            if final_decision != current.decision:
                raise ValueError('Save the changed decision before approving it.')
            owner = self.conn.execute('SELECT owner FROM runs WHERE run_id=?', (run_id,)).fetchone()['owner']
            self_approved = actor in (current.reviewer, owner)
            if self_approved and confirmed is not True:
                raise ValueError('Confirm that you are approving your own work. It will be recorded as self-approved.')
            f = super().finalize(run_id, row_id, final_decision, actor, ("Self-approved. " if self_approved else "") + note, commit=False)
            self.conn.execute('UPDATE finals SET self_approved=? WHERE run_id=? AND row_id=?', (int(self_approved), run_id, row_id))
            self._event(run_id, row_id, {'event': 'approval', **asdict(f), 'self_approved': self_approved})
            self.db.audit(actor, 'review.self_approved' if self_approved else 'review.approved', f'{run_id} {row_id}: {final_decision}')
        return f

    def rows_for_viewer(self, run_id, results, viewer_slot=1, blind=False):
        out = super().rows_for_viewer(run_id, results, 1, False)
        flags = {r['row_id']: bool(r['self_approved']) for r in self.conn.execute('SELECT row_id,self_approved FROM finals WHERE run_id=?', (run_id,))}
        for row in out:
            if row['final']:
                row['final']['self_approved'] = flags.get(row['row_id'], False)
        return out

    def history(self, run_id, row_id):
        events = [json.loads(r['payload']) for r in self.conn.execute('SELECT payload FROM review_events WHERE run_id=? AND row_id=? ORDER BY seq', (run_id, row_id))]
        return [{'event': 'engine', 'detail': 'Engine recommendation recorded with the run'}, *events] if events else super().history(run_id, row_id)

    def state_counts(self, run_id, results, viewer_slot=1, blind=False):
        counts = {'ENGINE_RECOMMENDED': 0, 'REVIEWED': 0, 'FINALIZED': 0}
        decisions, finals = self.all_decisions(run_id), self.finals(run_id)
        for r in results:
            counts[self.state_of(decisions.get(r.row_id, {}), finals.get(r.row_id))] += 1
        return counts
