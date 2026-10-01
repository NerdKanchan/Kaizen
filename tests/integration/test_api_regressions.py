"""Failure paths missed by the happy-path API suite: uploads, payloads and audit identity."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kaizen.api.app import RunCache, create_app
from kaizen.datasets.pdf_bom import BomRowSpec, BomSpec, render_bom_pdf
from kaizen.datasets.pdf_label import LabelSpec, render_label_pdf
from kaizen.pipeline import run_folder
from kaizen.review.access import AccessStore
from kaizen.workspace import Workspace

EMAIL = 'regression@bd.com'
PASSWORD = 'regression-password'


@pytest.fixture
def env(tmp_path):
    source = tmp_path / 'source'
    render_bom_pdf(BomSpec(parent_item='1295108NS', parent_description='KIT', rows=[BomRowSpec(item='2260001', description='END CAP', qty_per='2')]), source / 'bom.pdf')
    render_label_pdf(LabelSpec(ref='1295108', product_name='KIT', contents=['1 Each - End Cap']), source / 'label.pdf')
    ws = Workspace(tmp_path / 'ws')
    AccessStore(ws.db).bootstrap(EMAIL, PASSWORD)
    client = TestClient(create_app(ws))
    client.post('/api/auth/signin', json={'email': EMAIL, 'password': PASSWORD})
    run = run_folder(source, ws.repository.store())
    RunCache(ws).put(run)
    ws.db.conn.execute('UPDATE runs SET owner=?,name=? WHERE run_id=?', (EMAIL, 'Existing run', run.metadata.run_id))
    ws.db.conn.commit()
    yield ws, client, run, source
    ws.db.close()


def upload(client, source, names=('Project/bom.pdf', 'Project/label.pdf'), **kwargs):
    return client.post('/api/runs/upload', files=[('files', (name, (source / ('label.pdf' if 'label' in name else 'bom.pdf')).read_bytes(), 'application/pdf')) for name in names], **kwargs)


def test_upload_on_migrated_database_preserves_existing_run(env):
    ws, client, existing, source = env
    # This reproduces the migrated, ten-column schema that the old running server could not insert into.
    ws.db.conn.execute('ALTER TABLE runs ADD COLUMN future_metadata TEXT DEFAULT ""')
    response = upload(client, source, data={'name': 'Fresh upload'})
    assert response.status_code == 200, response.text
    assert response.json()['owner'] == EMAIL and response.json()['name'] == 'Fresh upload'
    assert response.json()['documents'] == 2 and response.json()['rows'] > 0
    assert client.get(f'/api/runs/{existing.metadata.run_id}').json()['name'] == 'Existing run'
    assert client.get('/api/health').json()['api_contract'] == 3


@pytest.mark.parametrize('names', [
    ('../bom.pdf',), ('/tmp/bom.pdf',), ('C:/private/bom.pdf',),
    ('Project/bom.pdf', 'Project/bom.pdf'), ('Project/bom.pdf', 'Project\\bom.pdf'),
    ('Project/bom.pdf', 'Project/bom.pdf/label.pdf'),
])
def test_invalid_upload_paths_are_client_errors_and_leave_no_files(env, names):
    ws, client, run, source = env
    response = upload(client, source, names)
    assert response.status_code == 400, response.text
    assert len(ws.runs.list()) == 1
    assert not list((ws.path / 'uploads').rglob('*.pdf'))


@pytest.mark.parametrize('name,content', [('notes.txt', b'notes'), ('bom.pdf', b'broken PDF'), ('bom.csv', b'no usable table')])
def test_unreadable_or_unsupported_upload_does_not_create_empty_run(env, name, content):
    ws, client, run, source = env
    response = client.post('/api/runs/upload', files={'files': (name, content)})
    assert response.status_code == 400, response.text
    assert len(ws.runs.list()) == 1
    assert not list((ws.path / 'uploads').rglob(name))


def test_unrelated_folder_files_are_not_stored(env):
    ws, client, run, source = env
    response = client.post('/api/runs/upload', files=[('files', ('Project/bom.pdf', (source / 'bom.pdf').read_bytes())), ('files', ('Project/notes.txt', b'unrelated')), ('files', ('Project/~$bom.xlsx', b'Excel lock'))])
    assert response.status_code == 200, response.text
    assert response.json()['documents'] == 1
    assert not list((ws.path / 'uploads').rglob('*.txt'))
    assert not list((ws.path / 'uploads').rglob('~$*'))


def test_upload_size_limit_and_failed_registration_clean_up(env, monkeypatch):
    import kaizen.api.app as api_module
    ws, client, run, source = env
    monkeypatch.setattr(api_module, 'MAX_UPLOAD_BYTES', 32)
    assert upload(client, source).status_code == 413
    assert len(ws.runs.list()) == 1
    assert not list((ws.path / 'uploads').rglob('*.pdf'))
    monkeypatch.setattr(api_module, 'MAX_UPLOAD_BYTES', 250 * 1024 * 1024)
    original = ws.repository.record_run_usage
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('injected registration failure')
    monkeypatch.setattr(ws.repository, 'record_run_usage', fail)
    with pytest.raises(RuntimeError, match='injected registration failure'):
        upload(client, source)
    assert len(ws.runs.list()) == 1
    assert [p.name for p in ws.runs_dir.iterdir()] == [run.metadata.run_id]
    assert not list((ws.path / 'uploads').rglob('*.pdf'))
    handled = TestClient(client.app, raise_server_exceptions=False, cookies=client.cookies)
    failure = upload(handled, source)
    assert failure.status_code == 500 and 'Error reference:' in failure.json()['detail']
    assert len(ws.runs.list()) == 1


@pytest.mark.parametrize('query', [{'hourly_rate': 'NaN'}, {'hourly_rate': 'Infinity'}, {'reviewers': 0}, {'baseline_minutes_per_sku': -1}, {'target_reduction_pct': 101}])
def test_business_parameters_are_validated(env, query):
    response = env[1].get(f'/api/runs/{env[2].metadata.run_id}/business-case', params=query)
    assert response.status_code == 422, response.text


def test_failed_and_oversized_imports_are_removed(env, monkeypatch):
    import kaizen.api.app as api_module
    ws, client, run, source = env
    url = f'/api/runs/{run.metadata.run_id}/decisions/import'
    assert client.post(url, files={'file': ('bad.xlsx', b'broken')}).status_code == 400
    assert not list((ws.runs_dir / run.metadata.run_id / 'imports').glob('*'))
    monkeypatch.setattr(api_module, 'MAX_IMPORT_BYTES', 4)
    assert client.post(url, files={'file': ('large.xlsx', b'12345')}).status_code == 413
    assert client.post('/api/terminology/import', files={'file': ('large.csv', b'12345')}).status_code == 413
    assert not list((ws.path / 'uploads').glob('import-*'))


def test_corrective_run_verifies_only_the_selected_earlier_run(env):
    from kaizen.review.action_items import ActionItemStore
    ws, client, before, source = env
    items = ActionItemStore(ws.db)
    row = next(r for r in before.results if r.discrepancies)
    original = items.create_from_result(before, row, EMAIL)
    render_label_pdf(LabelSpec(ref='1295108', product_name='KIT', contents=['2 Each - End Cap']), source / 'label.pdf')
    after = upload(client, source).json()['run_id']
    assert client.post(f'/api/runs/{after}/verify-and-close').json()['resolved'] == []
    assert items.get(original.id).status == 'OPEN'
    assert client.post(f'/api/runs/{after}/verify-and-close', params={'against': before.metadata.run_id}).json()['resolved'] == [original.id]
    assert items.get(original.id).resolved_in_run == after
    items.update(original.id, EMAIL, status='OPEN')
    ws.db.conn.execute('UPDATE runs SET owner=? WHERE run_id=?', ('other@bd.com', before.metadata.run_id))
    ws.db.conn.commit()
    url = f'/api/runs/{after}/verify-and-close'
    assert client.post(url, params={'against': before.metadata.run_id}).status_code == 404
    AccessStore(ws.db).share(before.metadata.run_id, EMAIL, 'view', 'other@bd.com')
    assert client.post(url, params={'against': before.metadata.run_id}).status_code == 403
    assert items.get(original.id).status == 'OPEN'


def test_health_detects_stale_server_after_source_changes(env, monkeypatch):
    import kaizen.api.app as api_module
    assert not env[1].get('/api/health').json()['restart_required']
    monkeypatch.setattr(api_module, '_source_fingerprint', lambda: 'source has changed')
    assert env[1].get('/api/health').json()['restart_required']


@pytest.mark.parametrize('path,method,payload', [
    ('/api/runs/from-path', 'post', {}),
    ('/api/runs/from-path', 'post', {'path': None}),
    ('/api/runs/{rid}', 'patch', {'name': {}}),
    ('/api/runs/{rid}/sharing', 'put', {'email': []}),
    ('/api/runs/{rid}/decisions', 'post', {}),
    ('/api/runs/{rid}/decisions', 'post', {'row_id': 'x', 'decision': 'ACCEPT', 'comment': []}),
    ('/api/runs/{rid}/decisions', 'post', {'row_id': 'x', 'decision': 'ACCEPT', 'expected_revision': True}),
    ('/api/runs/{rid}/finalize', 'post', {}),
    ('/api/runs/{rid}/relationships/from-row', 'post', {'row_id': 'x', 'aliases': 'wrong type'}),
    ('/api/runs/{rid}/mining/approve', 'post', {}),
    ('/api/runs/{rid}/mining/reject', 'post', {}),
    ('/api/runs/{rid}/action-items', 'post', {}),
    ('/api/terminology', 'post', {}),
    ('/api/terminology', 'post', {'canonical': 'cap', 'aliases': 'not a list'}),
    ('/api/terminology/REL-001', 'put', {'aliases': None}),
    ('/api/admin/users/regression@bd.com', 'patch', {'is_admin': 'false'}),
    ('/api/auth/signup', 'post', {'email': {}, 'password': []}),
])
def test_malformed_mutations_are_validation_errors(env, path, method, payload):
    ws, client, run, source = env
    response = getattr(client, method)(path.format(rid=run.metadata.run_id), json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize('action', ['activate', 'deactivate'])
def test_unknown_relationship_actions_return_404(env, action):
    assert env[1].post(f'/api/terminology/REL-missing/{action}', json={}).status_code == 404


def test_relationship_author_is_the_session_and_blank_wording_is_refused(env):
    ws, client, run, source = env
    response = client.post('/api/terminology', json={'canonical': 'Cap', 'by': 'forged@bd.com'})
    assert response.status_code == 200
    assert response.json()['created_by'] == EMAIL
    rid = response.json()['id']
    client.put(f'/api/terminology/{rid}', json={'canonical': 'End cap', 'by': 'forged@bd.com'})
    assert ws.repository.history(rid)[-1].changed_by == EMAIL
    assert client.post('/api/terminology', json={'canonical': '   '}).status_code == 400
    assert client.post('/api/terminology/import', files={'file': ('bad.xlsx', b'broken')}).status_code == 400
    assert not list((ws.path / 'uploads').glob('import-*'))


@pytest.mark.parametrize('query', [{'limit': -1}, {'limit': 0}, {'limit': 5001}, {'offset': -1}, {'offset': 0.5}])
def test_result_pagination_is_bounded(env, query):
    assert env[1].get(f'/api/runs/{env[2].metadata.run_id}/results', params=query).status_code == 422


def test_page_rendering_bounds_and_missing_source(env):
    ws, client, run, source = env
    doc = run.documents[0]
    url = f'/api/runs/{run.metadata.run_id}/documents/{doc.id}/pages/1'
    for dpi in (-1, 0, 301):
        assert client.get(url, params={'dpi': dpi}).status_code == 422
    Path(doc.path).unlink()
    assert client.get(url).status_code == 404


def test_action_item_status_and_run_filters_both_apply(env):
    ws, client, run, source = env
    row = next(r for r in run.results if r.discrepancies)
    response = client.post(f'/api/runs/{run.metadata.run_id}/action-items', json={'row_id': row.row_id})
    assert response.status_code == 200
    aid = response.json()['id']
    assert client.get('/api/action-items', params={'run_id': run.metadata.run_id, 'status': 'RESOLVED'}).json() == []
    client.patch(f'/api/action-items/{aid}', json={'status': 'RESOLVED'})
    assert len(client.get('/api/action-items', params={'run_id': run.metadata.run_id, 'status': 'RESOLVED'}).json()) == 1


def test_local_path_must_be_a_folder(env):
    assert env[1].post('/api/runs/from-path', json={'path': str(env[3] / 'bom.pdf')}).status_code == 400


def review_row(client, run_id, row_id, kind, classification=None, approve=False):
    base = f'/api/runs/{run_id}'
    detail = client.get(f'{base}/results/{row_id}').json()
    response = client.post(f'{base}/decisions', json={'row_id': row_id, 'decision': kind,
                           'override_classification': classification, 'expected_revision': detail['revision']})
    assert response.status_code == 200, response.text
    if approve:
        detail = client.get(f'{base}/results/{row_id}').json()
        response = client.post(f'{base}/finalize', json={'row_id': row_id, 'final_decision': kind,
                               'expected_revision': detail['revision'], 'confirm_self_approval': True})
        assert response.status_code == 200, response.text


def test_approved_override_updates_overview_runs_list_queue_and_filters(env):
    ws, client, run, _ = env
    base = f'/api/runs/{run.metadata.run_id}'
    row = next(r for r in run.results if r.requires_validation and r.discrepancies)
    target = 'EXACT' if row.classification.value != 'EXACT' else 'EQUIVALENT'
    before = client.get(base).json()
    review_row(client, run.metadata.run_id, row.row_id, 'OVERRIDE', target)
    saved = client.get(base).json()['review_progress']
    assert saved['pending'] == before['review_progress']['pending']
    assert saved['awaiting_approval'] == 1 and saved['approved'] == 0
    assert saved['unresolved_rows'] == before['review_progress']['unresolved_rows']
    assert row.row_id in {r['row_id'] for r in client.get(f'{base}/results', params={'classification': target}).json()['rows']}
    review_row(client, run.metadata.run_id, row.row_id, 'OVERRIDE', target, approve=True)
    after = client.get(base).json()
    assert after['review_progress']['pending'] == before['review_progress']['pending'] - 1
    assert after['review_progress']['approved'] == after['state_counts']['FINALIZED'] == 1
    assert after['review_progress']['unresolved_rows'] == before['review_progress']['unresolved_rows'] - 1
    assert after['counts'] == before['counts']  # Engine evidence is never rewritten.
    assert client.get('/api/runs').json()[0]['summary']['review_progress'] == after['review_progress']
    pending = client.get(f'{base}/results', params={'needs_validation': True}).json()
    assert pending['total'] == after['review_progress']['pending']
    assert row.row_id not in {r['row_id'] for r in pending['rows']}
    approved = client.get(f'{base}/results', params={'state': 'FINALIZED'}).json()['rows'][0]
    assert approved['effective_classification'] == target
    assert not approved['pending_review'] and not approved['unresolved']
    assert approved['current_discrepancies'] == [] and approved['discrepancies']
    assert row.row_id not in {r['row_id'] for r in client.get(f'{base}/results', params={'classification': row.classification.value}).json()['rows']}
    assert row.row_id in {r['row_id'] for r in client.get(f'{base}/results', params={'engine_classification': row.classification.value}).json()['rows']}
    review_row(client, run.metadata.run_id, row.row_id, 'CONFIRM_DISCREPANCY')
    reopened = client.get(base).json()['review_progress']
    assert reopened['approved'] == 0 and reopened['pending'] == before['review_progress']['pending']
    assert reopened['unresolved_rows'] == before['review_progress']['unresolved_rows']


def test_approval_of_confirmed_discrepancy_completes_review_without_clearing_finding(env):
    _, client, run, _ = env
    base = f'/api/runs/{run.metadata.run_id}'
    row = next(r for r in run.results if r.requires_validation and r.discrepancies)
    before = client.get(base).json()['review_progress']
    review_row(client, run.metadata.run_id, row.row_id, 'CONFIRM_DISCREPANCY', approve=True)
    progress = client.get(base).json()['review_progress']
    assert progress['approved'] == progress['confirmed_discrepancies'] == 1
    assert progress['pending'] == before['pending'] - 1
    assert progress['unresolved_rows'] == before['unresolved_rows']
    assert progress['discrepancies'] == before['discrepancies']
    results = client.get(f'{base}/results', params={'unresolved': True, 'discrepancy': row.discrepancies[0].type.value}).json()
    assert row.row_id in {r['row_id'] for r in results['rows']}


def test_more_information_stays_pending_even_when_approved(env):
    _, client, run, _ = env
    row = next(r for r in run.results if r.requires_validation)
    base = f'/api/runs/{run.metadata.run_id}'
    before = client.get(base).json()['review_progress']['pending']
    review_row(client, run.metadata.run_id, row.row_id, 'NEEDS_MORE_INFORMATION', approve=True)
    progress = client.get(base).json()['review_progress']
    assert progress['approved'] == progress['needs_information'] == 1
    assert progress['pending'] == before
    assert row.row_id in {r['row_id'] for r in client.get(f'{base}/results', params={'needs_validation': True}).json()['rows']}


def test_clean_row_with_saved_decision_waits_for_approval(env):
    _, client, run, _ = env
    row = next(r for r in run.results if not r.requires_validation)
    base = f'/api/runs/{run.metadata.run_id}'
    before = client.get(base).json()['review_progress']['pending']
    review_row(client, run.metadata.run_id, row.row_id, 'ACCEPT')
    progress = client.get(base).json()['review_progress']
    assert progress['pending'] == before + 1 and progress['awaiting_approval'] == 1
    review_row(client, run.metadata.run_id, row.row_id, 'ACCEPT', approve=True)
    assert client.get(base).json()['review_progress']['pending'] == before


def test_missing_saved_run_does_not_hide_other_runs_in_list(env):
    ws, client, run, _ = env
    Path(ws.runs.get(run.metadata.run_id)['json_path']).unlink()
    records = client.get('/api/runs').json()
    assert len(records) == 1 and records[0]['unavailable']
    assert client.get(f'/api/runs/{run.metadata.run_id}').status_code == 404


def test_overview_aggregates_every_row_beyond_queue_page_limit(env):
    ws, client, run, _ = env
    row = next(r for r in run.results if r.requires_validation and r.discrepancies)
    run.results = [row.model_copy(update={'row_id': f'large-{i}'}) for i in range(5010)]
    RunCache(ws).put(run)
    base = f'/api/runs/{run.metadata.run_id}'
    overview = client.get(base).json()['review_progress']
    assert overview['pending'] == overview['unresolved_rows'] == 5010
    assert overview['discrepancies'][0]['count'] == 5010
    page = client.get(f'{base}/results', params={'needs_validation': True, 'limit': 1}).json()
    assert page['total'] == 5010 and len(page['rows']) == 1


def test_accepting_a_mismatch_preserves_the_confirmed_finding(env):
    from kaizen.models import Classification
    ws, client, run, _ = env
    row = next(r for r in run.results if r.requires_validation and r.discrepancies)
    row.classification = Classification.MISMATCH
    RunCache(ws).put(run)
    base = f'/api/runs/{run.metadata.run_id}'
    before = client.get(base).json()['review_progress']
    review_row(client, run.metadata.run_id, row.row_id, 'ACCEPT', approve=True)
    progress = client.get(base).json()['review_progress']
    assert progress['pending'] == before['pending'] - 1
    assert progress['approved'] == progress['confirmed_discrepancies'] == 1
    assert progress['unresolved_rows'] == before['unresolved_rows']


def test_reviewer_finding_on_a_clean_row_is_counted_filtered_and_prioritized(env):
    ws, client, run, _ = env
    clean = next(r for r in run.results if not r.requires_validation).model_copy(update={'row_id': 'z-reviewer-finding'})
    major = next(r for r in run.results if r.severity and r.severity.value == 'MAJOR').model_copy(update={'row_id': 'a-engine-finding'})
    run.results = [major, clean]
    RunCache(ws).put(run)
    base = f'/api/runs/{run.metadata.run_id}'
    review_row(client, run.metadata.run_id, clean.row_id, 'OVERRIDE', 'MISSING', approve=True)
    progress = client.get(base).json()['review_progress']
    assert progress['approved'] == progress['confirmed_discrepancies'] == progress['blockers'] == 1
    assert {'type': 'REVIEWER_FINDING', 'count': 1, 'severity': 'BLOCKER'} in progress['discrepancies']
    results = client.get(f'{base}/results', params={'unresolved': True}).json()['rows']
    assert results[0]['row_id'] == clean.row_id and results[0]['current_severity'] == 'BLOCKER'
    assert results[0]['engine']['requires_validation'] is False
    filtered = client.get(f'{base}/results', params={'unresolved': True, 'discrepancy': 'REVIEWER_FINDING', 'severity': 'BLOCKER'}).json()
    assert filtered['total'] == 1 and filtered['rows'][0]['row_id'] == clean.row_id
