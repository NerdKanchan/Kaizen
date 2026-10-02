"""Verified labels must survive normal review but never leak through a training split."""

import hashlib
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kaizen.ai.providers import NullProvider
from kaizen.api.app import RunCache
from kaizen.evaluation.learning import build_candidate, score_samples, shadow_evaluate
from kaizen.matching.attributes import attribute_conflicts, extract_attributes
from kaizen.matching.ladder import MatchLadder
from kaizen.models import Classification, DocType, Document, DocumentItem, Evidence, ItemCategory, Thresholds
from kaizen.pipeline import Ingested, run_checks
from kaizen.review.learning import DrawingInput, GroundTruthInput, LabelApproval, LearningStore
from kaizen.terminology.store import RelationshipStore
from kaizen.workspace import Workspace

AUTHOR = 'tester@bd.com'
VERIFIER = 'verifier@bd.com'


def document(root, sku, kind, entries):
    doc_id = f'{sku}:{kind.value}'
    sha = hashlib.sha256(doc_id.encode()).hexdigest()
    path = str(root / sku / f'{kind.value.lower()}.pdf')
    items = [DocumentItem(id=f'{doc_id}:{i}', doc_id=doc_id, doc_type=kind, sku=sku, item_number=f'ITEM-{i}' if kind == DocType.BOM else None,
        description=description, quantity=Decimal(quantity) if quantity is not None else None, uom='EA', category=ItemCategory.PHYSICAL_COMPONENT,
        attributes={'kind': 'callout'} if kind == DocType.DRAWING else {},
        evidence=Evidence(file=path, file_sha256=sha, page=1, locator=f'row {i}', raw_text=description)) for i, (description, quantity) in enumerate(entries)]
    return Document(id=doc_id, doc_type=kind, path=path, sha256=sha, sku=sku, items=items,
                    header={'drawing_number': f'DWG-{sku}', 'revision': 'A'} if kind == DocType.DRAWING else {}, parser_name='test', parser_version='1')


@pytest.fixture
def learning_env(tmp_path):
    ws = Workspace(tmp_path / 'ws')
    docs = []
    for sku in ('1001', '1002', '1003', '1004'):
        docs.extend([document(tmp_path, sku, DocType.BOM, [('MASK, VAPOR BARRIER', '1'), ('CATHETER', '2'), ('STYLET', '4'), ('NEEDLE 22 GA', '1')]),
                     document(tmp_path, sku, DocType.LABEL, [('Mask', '1'), ('Catheter with stylet', '2'), ('Needle 22 GA', '2')]),
                     document(tmp_path, sku, DocType.DRAWING, [('Mask', None), ('Catheter', None), ('Stylet', None), ('Needle 22 GA', None)])])
    run = run_checks(Ingested(root=tmp_path, documents=docs), RelationshipStore(), provider=NullProvider())
    RunCache(ws).put(run)
    ws.db.conn.execute('UPDATE runs SET owner=? WHERE run_id=?', (AUTHOR, run.metadata.run_id))
    ws.db.conn.commit()
    learning = LearningStore(ws.db)
    learning.enroll(run, AUTHOR)
    yield ws, run, learning
    ws.db.close()


def row_for(run, learning, split='train', check='BOM_LABEL', description='NEEDLE 22 GA'):
    return next(r for r in run.results if learning.split(r.sku) == split and r.check.value == check and r.role == 'item' and r.source_a and r.source_a.description == description)


def body_for(row, **changes):
    return GroundTruthInput.model_validate({'expected_version': 0, 'review_revision': 0, 'verdict': 'GENUINE_DISCREPANCY',
        'classification': 'MISMATCH', 'expected_a_ids': [row.source_a.id] if row.source_a else [],
        'expected_b_ids': [row.source_b.id] if row.source_b else [], 'discrepancies': ['QTY_MISMATCH'], 'note': 'Verified against both source pages.', **changes})


def verify(learning, run, row, data=None):
    record = learning.annotate(run, row, data or body_for(row), AUTHOR)
    return learning.approve('learning_labels', run, row.row_id, LabelApproval(expected_version=record['version'], approve=True), VERIFIER)


def test_four_skus_hold_out_one_and_copy_keeps_assignments(learning_env):
    ws, run, learning = learning_env
    assignments = {g.sku: learning.split(g.sku) for g in run.groups}
    assert list(assignments.values()).count('evaluation') == 1
    assert list(assignments.values()).count('train') == 3
    copy = run.model_copy(deep=True)
    copy.metadata.run_id = 'copy'
    learning.enroll(copy, AUTHOR)
    assert {g.sku: learning.split(g.sku) for g in copy.groups} == assignments
    assert len(learning.summary(run)['tasks']) >= 12
    assert len({r['sku'] for r in learning.summary(run)['tasks']}) == 4


def test_independent_approval_and_split_exports(learning_env):
    _, run, learning = learning_env
    training = row_for(run, learning)
    evaluation = row_for(run, learning, split='evaluation')
    learning.annotate(run, training, body_for(training), AUTHOR)
    with pytest.raises(ValueError, match='different administrator'):
        learning.approve('learning_labels', run, training.row_id, LabelApproval(expected_version=1, approve=True), AUTHOR)
    assert learning.dataset(run, 'train')['samples'] == []
    learning.approve('learning_labels', run, training.row_id, LabelApproval(expected_version=1, approve=True), VERIFIER)
    verify(learning, run, evaluation)
    train, held_out = learning.dataset(run, 'train'), learning.dataset(run, 'evaluation')
    assert len(train['samples']) == len(held_out['samples']) == 1
    assert train['samples'][0]['payload']['sku'] != held_out['samples'][0]['payload']['sku']
    assert train['dataset_version'] == learning.dataset(run, 'train')['dataset_version']


def test_stale_versions_and_review_changes_invalidate_labels(learning_env):
    _, run, learning = learning_env
    row = row_for(run, learning)
    verify(learning, run, row)
    with pytest.raises(ValueError, match='changed'):
        learning.annotate(run, row, body_for(row), AUTHOR)
    review = learning.review
    review.decide(run.metadata.run_id, row.row_id, 1, AUTHOR, 'NEEDS_MORE_INFORMATION', 'Quantity unreadable')
    assert learning.dataset(run, 'train')['samples'] == []
    with pytest.raises(ValueError, match='changed'):
        learning.annotate(run, row, body_for(row, expected_version=1), AUTHOR)
    verify(learning, run, row, body_for(row, expected_version=1, review_revision=review.revision(run.metadata.run_id, row.row_id)))
    assert learning.dataset(run, 'train')['samples'][0]['version'] == 2


def test_normal_review_approval_does_not_invalidate_ground_truth(learning_env):
    _, run, learning = learning_env
    row = row_for(run, learning)
    rid = run.metadata.run_id
    learning.review.decide(rid, row.row_id, 1, AUTHOR, 'CONFIRM_DISCREPANCY')
    revision = learning.review.revision(rid, row.row_id)
    verify(learning, run, row, body_for(row, review_revision=revision))
    learning.review.approve(rid, row.row_id, 'CONFIRM_DISCREPANCY', VERIFIER, '', revision, False)
    assert len(learning.dataset(run, 'train')['samples']) == 1


def test_unresolved_annotations_and_cross_sku_corrections_cannot_train(learning_env):
    _, run, learning = learning_env
    row = row_for(run, learning)
    unresolved = body_for(row, verdict='UNRESOLVED', classification='POTENTIAL')
    learning.annotate(run, row, unresolved, AUTHOR)
    with pytest.raises(ValueError, match='Resolve'):
        learning.approve('learning_labels', run, row.row_id, LabelApproval(expected_version=1, approve=True), VERIFIER)
    other = row_for(run, learning, split='evaluation')
    with pytest.raises(ValueError, match='this SKU'):
        learning.annotate(run, row, body_for(row, expected_version=1, expected_b_ids=[other.source_b.id]), AUTHOR)


def test_drawing_rows_wait_for_independent_release_confirmation(learning_env):
    _, run, learning = learning_env
    row = row_for(run, learning, check='BOM_DRAWING')
    verify(learning, run, row, body_for(row, verdict='CORRECT_PAIR', classification='EXACT', discrepancies=[]))
    assert learning.dataset(run, 'train')['samples'] == []
    drawing = DrawingInput(expected_version=0, doc_id=row.source_b.doc_id, applicability='CONFIRMED_RELEASED', released_revision='A', release_reference='Released record 123', note='Owner confirmed applicability to SKU.')
    learning.drawing(run, row.sku, drawing, AUTHOR)
    assert learning.dataset(run, 'train')['samples'] == []
    learning.approve('learning_drawings', run, row.sku, LabelApproval(expected_version=1, approve=True), VERIFIER)
    assert len(learning.dataset(run, 'train')['samples']) == 1
    learning.drawing(run, row.sku, drawing.model_copy(update={'expected_version': 1, 'applicability': 'NOT_APPLICABLE'}), AUTHOR)
    assert learning.dataset(run, 'train')['samples'] == []


def test_assembly_members_allocations_and_quantity_mismatch(learning_env):
    ws, run, learning = learning_env
    row = row_for(run, learning, description='CATHETER')
    a, b = learning.items_for_row(run, row)
    stylet = next(i for i in a.values() if i.description == 'STYLET')
    label = next(i for i in b.values() if i.description == 'Catheter with stylet')
    data = body_for(row, verdict='INCORRECT_PAIR', classification='EQUIVALENT', discrepancies=[],
        expected_a_ids=[row.source_a.id, stylet.id], expected_b_ids=[label.id], assembly_quantities={row.source_a.id: 1.0, stylet.id: 2.0})
    with pytest.raises(ValueError, match='every assembly'):
        learning.annotate(run, row, data.model_copy(update={'assembly_quantities': {row.source_a.id: 1.0}}), AUTHOR)
    verify(learning, run, row, data)
    train = learning.dataset(run, 'train')
    store, assemblies, negatives, overrides = build_candidate(train, [])
    candidate = run_checks(Ingested(root=ws.path, documents=run.documents), store, structured=True, assembly_rules=assemblies, learning_matchers=[negatives], attribute_overrides=overrides)
    members = [r for r in candidate.results if r.sku == row.sku and r.check.value == 'BOM_LABEL' and r.source_a and r.source_a.id in data.expected_a_ids]
    assert len(members) == 2
    assert all(r.classification == Classification.EQUIVALENT and r.source_b.id == label.id for r in members)
    assert score_samples(candidate, train)['pairing_accuracy'] == 1.0
    modified = [d.model_copy(deep=True) for d in run.documents]
    member = next(i for d in modified for i in d.items if i.id == stylet.id)
    member.quantity = Decimal('3')
    bad_candidate = run_checks(Ingested(root=ws.path, documents=modified), store, structured=True, assembly_rules=assemblies)
    bad = next(r for r in bad_candidate.results if r.check.value == 'BOM_LABEL' and r.source_a and r.source_a.id == stylet.id)
    assert bad.classification == Classification.MISMATCH
    assert bad.requires_validation
    missing_docs = [d.model_copy(deep=True) for d in run.documents]
    for doc in missing_docs:
        doc.items = [i for i in doc.items if i.id != stylet.id]
    missing = run_checks(Ingested(root=ws.path, documents=missing_docs), store, structured=True, assembly_rules=assemblies)
    assembly_rows = [r for r in missing.results if r.check.value == 'BOM_LABEL' and r.sku == row.sku and r.source_b and r.source_b.id == label.id]
    assert all(r.requires_validation for r in assembly_rows)
    assert any(r.classification == Classification.MISSING for r in assembly_rows)


def test_shadow_evaluation_is_frozen_and_keeps_live_run_unchanged(learning_env):
    ws, run, learning = learning_env
    verify(learning, run, row_for(run, learning))
    verify(learning, run, row_for(run, learning, split='evaluation'))
    before = run.model_dump_json()
    report = shadow_evaluate(ws, run, VERIFIER)
    assert report['baseline']['scored_samples'] == report['candidate']['scored_samples'] == 1
    assert report['training_samples'] == 1
    assert report['gate_passed'] is False
    assert run.model_dump_json() == before
    assert (ws.runs_dir / run.metadata.run_id / 'learning' / report['id'] / 'train.json').exists()
    assert report['evaluation_dataset_version'] == learning.dataset(run, 'evaluation')['dataset_version']
    assert learning.summary(run)['latest_evaluation']['stale'] is False


@pytest.mark.parametrize('changes', [{'assembly_quantities': {'x': float('nan')}}, {'attributes': {'x': {'dimensions_mm': [-1.0]}}}, {'discrepancies': ['UNKNOWN']}, {'classification': 'EXACT'}])
def test_invalid_ground_truth_fails_validation(learning_env, changes):
    _, run, learning = learning_env
    with pytest.raises(ValidationError):
        body_for(row_for(run, learning), **changes)


def test_structured_attributes_units_short_descriptions_and_conflicts():
    assert extract_attributes('Needle 22G x 1.5in').gauge == 22
    assert extract_attributes('Gauze 4 x 4 in').dimensions_mm == [101.6, 101.6]
    assert not attribute_conflicts(extract_attributes('Gauze 10cm x 10cm'), extract_attributes('Gauze 4 x 4 in'))
    assert attribute_conflicts(extract_attributes('Needle 22G'), extract_attributes('Needle 24G'))
    assert extract_attributes('Solution 2% pack of 3').concentration_pct == 2
    assert extract_attributes('Solution 2% pack of 3').pack_quantity == 3
    ladder = MatchLadder(RelationshipStore(), Thresholds(), structured=True)
    short = ladder.match('MASK, VAPOR BARRIER', 'Mask')
    assert short.assignable and short.needs_confirmation
    assert not ladder.match('Needle 22G', 'Needle 24G').assignable
    assert ladder.match('Gauze 10cm x 10cm', 'Gauze 4 x 4 in').assignable
    assert not ladder.match('Gauze 10cm x 10cm', 'Gauze 2 x 2 in').assignable
    assert attribute_conflicts(extract_attributes('Catheter 0.46mm'), extract_attributes('Catheter 0.9mm'))


def test_terminology_changes_mark_candidate_report_stale(learning_env):
    ws, run, learning = learning_env
    verify(learning, run, row_for(run, learning))
    shadow_evaluate(ws, run, VERIFIER)
    assert learning.summary(run)['latest_evaluation']['stale'] is False
    ws.repository.create(canonical='Example approved term', aliases=['Example ERP term'], created_by=VERIFIER)
    assert learning.summary(run)['latest_evaluation']['stale'] is True
    shadow_evaluate(ws, run, VERIFIER)
    assert learning.summary(run)['latest_evaluation']['stale'] is False


def test_identical_sources_cannot_cross_splits_when_renamed(learning_env):
    _, run, learning = learning_env
    group = next(g for g in run.groups if learning.split(g.sku) == 'evaluation')
    docs = [d.model_copy(deep=True) for d in run.documents if d.id in group.document_ids]
    for doc in docs:
        doc.id = 'renamed-' + doc.id
        doc.sku = '9999'
        doc.path = doc.path.replace(group.sku, '9999')
        for item in doc.items:
            item.doc_id = doc.id
    copy = run.model_copy(deep=True)
    copy.metadata.run_id = 'renamed-copy'
    copy.documents = docs
    copy.groups = [group.model_copy(update={'sku': '9999', 'document_ids': [d.id for d in docs]})]
    learning.enroll(copy, AUTHOR)
    assert learning.split('9999') == 'evaluation'


def test_reviewer_pair_corrections_do_not_double_count_expected_pair(learning_env):
    _, run, learning = learning_env
    row = row_for(run, learning, description='MASK, VAPOR BARRIER')
    a, b = learning.items_for_row(run, row)
    mask = next(i for i in b.values() if i.description == 'Mask')
    b_only = next(r for r in run.results if r.sku == row.sku and r.check.value == 'BOM_LABEL' and r.source_a is None and r.source_b and r.source_b.id == mask.id)
    data = body_for(row, verdict='INCORRECT_PAIR', classification='EQUIVALENT', discrepancies=[], expected_b_ids=[mask.id])
    verify(learning, run, row, data)
    verify(learning, run, b_only, data.model_copy(update={'expected_a_ids': [row.source_a.id]}))
    assert len(learning.dataset(run, 'train')['samples']) == 1


def test_false_clear_scoring_flags_silent_quantity_errors(learning_env):
    _, run, learning = learning_env
    row = row_for(run, learning, split='evaluation')
    verify(learning, run, row)
    dataset = learning.dataset(run, 'evaluation')
    candidate = run.model_copy(deep=True)
    incorrect = next(r for r in candidate.results if r.row_id == row.row_id)
    incorrect.classification = Classification.EXACT
    incorrect.discrepancies = []
    incorrect.requires_validation = False
    metrics = score_samples(candidate, dataset)
    assert metrics['false_clears'] == 1
    assert metrics['false_clear_rate'] == 1.0
    assert metrics['discrepancy_recall'] == 0.0
