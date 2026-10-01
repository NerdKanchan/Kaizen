"""Concurrency and persistence regressions found during the project sweep."""

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import typer

from kaizen.cli.main import _thresholds
from kaizen.datasets.pdf_bom import BomRowSpec, BomSpec, render_bom_pdf
from kaizen.datasets.pdf_label import LabelSpec, render_label_pdf
from kaizen.ingest.quantity import parse_decimal
from kaizen.models import Classification, Thresholds
from kaizen.pipeline import run_folder, save_run
from kaizen.review.action_items import ActionItemStore
from kaizen.review.business import business_case
from kaizen.review.copies import copy_run
from kaizen.storage.db import Database
from kaizen.workspace import Workspace


def test_run_without_comparisons_cannot_claim_savings(sample):
    run = sample[1].model_copy(update={'results': []})
    case = business_case(run)
    assert case.rows == 0 and case.reduction_pct == 0 and case.annual_savings == 0
    assert not case.meets_target and not case.meets_target_after_confirmation


@pytest.fixture
def sample(tmp_path):
    root = tmp_path / 'source'
    render_bom_pdf(BomSpec(parent_item='1295108NS', parent_description='KIT', rows=[BomRowSpec(item='2260001', description='END CAP', qty_per='2')]), root / 'bom.pdf')
    render_label_pdf(LabelSpec(ref='1295108', product_name='KIT', contents=['1 Each - End Cap']), root / 'label.pdf')
    ws = Workspace(tmp_path / 'ws')
    run = run_folder(root, ws.repository.store())
    ws.register_run(run, save_run(run, ws.runs_dir / run.metadata.run_id / 'run.json'))
    ws.db.conn.execute('UPDATE runs SET owner=?,name=? WHERE run_id=?', ('owner@bd.com', 'Original', run.metadata.run_id))
    ws.db.conn.commit()
    yield ws, run
    ws.db.close()


def test_nested_transactions_defer_commits_and_roll_back_every_store_write(tmp_path):
    db = Database(tmp_path / 'test.db')
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.audit('tester', 'outer', '')
            db.conn.commit()
            with db.transaction():
                db.audit('tester', 'inner', '')
                db.conn.commit()
            raise RuntimeError('fail')
    assert db.conn.execute('SELECT COUNT(*) FROM audit').fetchone()[0] == 0
    with db.transaction():
        db.audit('tester', 'kept', '')
        with pytest.raises(RuntimeError):
            with db.transaction():
                db.audit('tester', 'removed', '')
                raise RuntimeError('inner')
    assert [r['action'] for r in db.conn.execute('SELECT * FROM audit')] == ['kept']
    with sqlite3.connect(db.path) as other:
        assert other.execute('SELECT COUNT(*) FROM audit').fetchone()[0] == 1
    db.close()


def test_concurrent_action_creation_allocates_unique_ids(sample, monkeypatch):
    ws, run = sample
    store = ActionItemStore(ws.db)
    row = next(r for r in run.results if r.discrepancies)
    original = store.next_id
    def slower_id():
        value = original()
        time.sleep(0.005)
        return value
    monkeypatch.setattr(store, 'next_id', slower_id)
    with ThreadPoolExecutor(max_workers=8) as pool:
        items = list(pool.map(lambda _: store.create_from_result(run, row, 'reviewer'), range(24)))
    assert len({ai.id for ai in items}) == 24
    assert len(store.for_run(run.metadata.run_id)) == 24


def test_concurrent_relationship_updates_keep_every_historical_version(sample, monkeypatch):
    repo = sample[0].repository
    rel = repo.create(canonical='Original', created_by='tester')
    original = repo.get
    def slower_get(rid):
        value = original(rid)
        time.sleep(0.005)
        return value
    monkeypatch.setattr(repo, 'get', slower_get)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: repo.update(rel.id, 'tester', canonical=f'Edit {index}'), range(16)))
    history = repo.history(rel.id)
    assert [record.version for record in history] == list(range(1, 18))
    assert {record.payload.canonical for record in history[1:]} == {f'Edit {index}' for index in range(16)}


def test_relationship_create_cannot_replace_existing_or_deleted_history(sample):
    repo = sample[0].repository
    rel = repo.create(canonical='Original', created_by='tester')
    with pytest.raises(ValueError, match='recorded history'):
        repo.create(canonical='Replacement', rel_id=rel.id)
    repo.delete(rel.id, 'tester')
    with pytest.raises(ValueError, match='recorded history'):
        repo.create(canonical='Replacement', rel_id=rel.id)
    assert repo.get_version(rel.id, 1).canonical == 'Original'


def test_registration_pins_the_run_snapshot_even_if_terminology_changes(sample):
    ws, run = sample
    expected = next(r for r in run.terminology_snapshot if r['id'] == 'REL-001')
    ws.repository.update('REL-001', 'tester', canonical='A changed rule')
    ws.register_run(run, ws.runs_dir / run.metadata.run_id / 'run.json')
    links = {r.relationship.id: r.relationship for r in ws.repository.relationships_for_run(run.metadata.run_id)}
    assert links['REL-001'].canonical == expected['canonical']
    assert links['REL-001'].version == expected['version']


def test_failed_copy_rolls_back_database_and_removes_its_files(sample, monkeypatch):
    ws, run = sample
    store = ActionItemStore(ws.db)
    row = next(r for r in run.results if r.discrepancies)
    store.create_from_result(run, row, 'reviewer')
    original = ws.db.conn.execute
    def fail_copy(sql, params=()):
        if sql.startswith('INSERT INTO action_items'):
            raise RuntimeError('copy failed')
        return original(sql, params)
    monkeypatch.setattr(ws.db.conn, 'execute', fail_copy)
    with pytest.raises(RuntimeError, match='copy failed'):
        copy_run(ws, run, 'editor@bd.com')
    assert [r['run_id'] for r in ws.runs.list()] == [run.metadata.run_id]
    assert [p.name for p in ws.runs_dir.iterdir()] == [run.metadata.run_id]
    assert ws.db.conn.execute('SELECT COUNT(*) FROM action_items').fetchone()[0] == 1


def test_skipped_comparison_and_potential_pair_are_not_verified_as_fixed(sample):
    ws, run = sample
    store = ActionItemStore(ws.db)
    row = next(r for r in run.results if r.discrepancies)
    ai = store.create_from_result(run, row, 'reviewer')
    skipped = run.model_copy(update={'results': []})
    outcome = store.verify_and_close(skipped)
    assert outcome.not_covered == [ai.id] and outcome.resolved == []
    assert store.get(ai.id).status == 'OPEN'
    potential = run.model_copy(update={'results': [row.model_copy(update={'classification': Classification.POTENTIAL, 'discrepancies': [], 'requires_validation': True})]})
    outcome = store.verify_and_close(potential)
    assert outcome.still_open == [ai.id] and outcome.resolved == []


def test_reopening_resolved_action_clears_previous_resolution(sample):
    ws, run = sample
    store = ActionItemStore(ws.db)
    row = next(r for r in run.results if r.discrepancies)
    ai = store.create_from_result(run, row, 'reviewer')
    ws.db.conn.execute("UPDATE action_items SET status='RESOLVED',resolved_in_run='old',resolved_at='yesterday' WHERE id=?", (ai.id,))
    ws.db.conn.commit()
    reopened = store.update(ai.id, 'reviewer', status='OPEN')
    assert reopened.resolved_in_run == '' and reopened.resolved_at == ''


def test_old_label_without_current_label_is_missing_coverage(sample):
    ws, run = sample
    source = Path(run.metadata.input_root)
    (source / 'label.pdf').rename(source / 'label_old.pdf')
    old_only = run_folder(source, ws.repository.store())
    assert old_only.coverage[0].status == 'MISSING_LABEL'
    assert old_only.results == []


@pytest.mark.parametrize('text', ['NaN', 'sNaN', 'Infinity', '-Infinity', 'INF'])
def test_nonfinite_quantities_are_unreadable_instead_of_poisoning_comparisons(text):
    assert parse_decimal(text) is None


def test_cli_thresholds_are_validated_instead_of_bypassing_model_rules():
    with pytest.raises(ValueError, match='candidate floor'):
        Thresholds(floor=0.9, potential=0.8)
    with pytest.raises(typer.BadParameter, match='less than or equal to 1'):
        _thresholds(1.1, None, None)
