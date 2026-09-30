"""Hosted account approval and run permissions: exercise actual HTTP routes."""
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kaizen.api.app import RunCache, create_app
from kaizen.datasets.build import build_golden
from kaizen.pipeline import run_folder
from kaizen.review.access import AccessStore
from kaizen.review.auth import LocalAccounts
from kaizen.workspace import Workspace

ADMIN = 'admin@bd.com'
EDITOR = 'editor@bd.com'
VIEWER = 'viewer@bd.com'
OUTSIDER = 'outsider@bd.com'
PW = 'test-password-2026'


@pytest.fixture(scope='module')
def sample(tmp_path_factory):
    root = tmp_path_factory.mktemp('collaboration-source')
    golden = build_golden(root / 'golden')
    ws = Workspace(root / 'ws')
    return run_folder(golden / 'sku-002', ws.repository.store())


@pytest.fixture
def env(tmp_path, sample):
    ws = Workspace(tmp_path / 'ws')
    access = AccessStore(ws.db)
    access.bootstrap(ADMIN, PW)
    app = create_app(ws, accounts=LocalAccounts(ws.db))
    clients = {}
    for email in (ADMIN, EDITOR, VIEWER, OUTSIDER):
        c = TestClient(app)
        if email != ADMIN:
            assert c.post('/api/auth/signup', json={'email': email, 'password': PW}).status_code == 200
            access.update(email, ADMIN, 'approved', False)
        assert c.post('/api/auth/signin', json={'email': email, 'password': PW}).status_code == 200
        clients[email] = c
    RunCache(ws).put(sample)
    rid = sample.metadata.run_id
    ws.db.conn.execute('UPDATE runs SET owner=?, name=? WHERE run_id=?', (ADMIN, 'Project test', rid))
    access.share(rid, EDITOR, 'edit', ADMIN)
    access.share(rid, VIEWER, 'view', ADMIN)
    ws.db.conn.commit()
    yield ws, access, clients, rid, sample.results[0].row_id
    ws.db.close()


def test_registration_requires_admin_approval(env):
    ws, access, clients, rid, row = env
    c = TestClient(clients[ADMIN].app)
    assert c.post('/api/auth/signup', json={'email':'pending@bd.com', 'password': PW}).json()['status'] == 'pending'
    assert c.post('/api/auth/signin', json={'email':'pending@bd.com', 'password': PW}).status_code == 403
    assert c.get('/api/runs').status_code == 401
    assert clients[ADMIN].patch('/api/admin/users/pending@bd.com', json={'status':'approved'}).status_code == 200
    assert c.post('/api/auth/signin', json={'email':'pending@bd.com', 'password': PW, 'slot':2}).json()['blind'] is False
    assert c.get('/api/runs').json() == []


@pytest.mark.parametrize('email', ['x@gmail.com', 'x@bd.com.evil', 'x@y@bd.com', 'x y@bd.com', '@bd.com'])
def test_domain_is_strict(env, email):
    c = env[2][ADMIN]
    assert c.post('/api/auth/signup', json={'email':email, 'password': PW}).status_code == 400


def test_admin_management_and_revocation(env):
    ws, access, c, rid, row = env
    assert c[EDITOR].get('/api/admin/users').status_code == 403
    assert c[ADMIN].patch(f'/api/admin/users/{EDITOR}', json={'is_admin':True}).status_code == 200
    assert c[EDITOR].get('/api/admin/users').status_code == 200
    assert c[EDITOR].patch(f'/api/admin/users/{ADMIN}', json={'is_admin':False}).status_code == 200
    assert c[EDITOR].patch(f'/api/admin/users/{EDITOR}', json={'status':'rejected'}).status_code == 400
    assert c[EDITOR].patch(f'/api/admin/users/{VIEWER}', json={'status':'rejected'}).status_code == 200
    assert c[VIEWER].get('/api/runs').status_code == 401


def test_visibility_and_owner_only_sharing(env):
    ws, access, c, rid, row = env
    assert c[OUTSIDER].get('/api/runs').json() == []
    assert c[VIEWER].get('/api/runs').json()[0]['permission'] == 'view'
    assert c[EDITOR].put(f'/api/runs/{rid}/sharing', json={'email':OUTSIDER,'permission':'edit'}).status_code == 403
    assert c[ADMIN].put(f'/api/runs/{rid}/sharing', json={'email':OUTSIDER,'permission':'edit'}).status_code == 200
    assert c[OUTSIDER].get(f'/api/runs/{rid}').status_code == 200
    assert c[ADMIN].put(f'/api/runs/{rid}/sharing', json={'email':OUTSIDER,'permission':None}).status_code == 200
    assert c[OUTSIDER].get(f'/api/runs/{rid}').status_code == 404


@pytest.mark.parametrize('suffix', ['', '/results', '/documents', '/mining', '/business-case', '/export.xlsx', '/download.zip', '/certificate.pdf'])
def test_hidden_runs_cannot_be_read_by_guessing_ids(env, suffix):
    ws, access, c, rid, row = env
    assert c[OUTSIDER].get(f'/api/runs/{rid}{suffix}').status_code == 404
    anonymous = TestClient(c[ADMIN].app)
    assert anonymous.get(f'/api/runs/{rid}{suffix}').status_code == 401


@pytest.mark.parametrize('suffix', ['/decisions', '/finalize', '/bulk-accept', '/copy', '/verify-and-close', '/action-items', '/mining/approve', '/decisions/import'])
def test_viewer_cannot_mutate(env, suffix):
    ws, access, c, rid, row = env
    assert c[VIEWER].post(f'/api/runs/{rid}{suffix}', json={'row_id':row,'decision':'ACCEPT'}).status_code == 403


@pytest.mark.parametrize('suffix', ['/export.xlsx', '/download.zip', '/certificate.pdf'])
def test_viewer_cannot_download(env, suffix):
    assert env[2][VIEWER].get(f'/api/runs/{env[3]}{suffix}').status_code == 403


def save(c, rid, row, comment='Checked'):
    detail = c.get(f'/api/runs/{rid}/results/{row}').json()
    result = c.post(f'/api/runs/{rid}/decisions', json={'row_id':row,'decision':'ACCEPT','comment':comment,'expected_revision':detail['revision']})
    assert result.status_code == 200, result.text
    return c.get(f'/api/runs/{rid}/results/{row}').json()


def test_self_approval_confirmation_history_and_stale_changes(env):
    ws, access, c, rid, row = env
    detail = save(c[EDITOR], rid, row)
    body = {'row_id':row, 'final_decision':'ACCEPT','expected_revision':detail['revision']}
    assert c[EDITOR].post(f'/api/runs/{rid}/finalize', json=body).status_code == 400
    body['confirm_self_approval'] = True
    assert c[EDITOR].post(f'/api/runs/{rid}/finalize', json=body).status_code == 200
    approved = c[EDITOR].get(f'/api/runs/{rid}/results/{row}').json()
    assert approved['final']['self_approved'] is True
    assert approved['history'][-1]['self_approved'] is True
    assert c[EDITOR].post(f'/api/runs/{rid}/decisions', json={'row_id':row,'decision':'ACCEPT','expected_revision':detail['revision']}).status_code == 409
    updated = save(c[EDITOR], rid, row, 'Changed after approval')
    assert updated['final'] is None
    assert len(updated['history']) == 4
    assert c[EDITOR].post(f'/api/runs/{rid}/finalize', json=body).status_code == 400


def test_copy_is_private_and_independent(env):
    ws, access, c, rid, row = env
    save(c[EDITOR], rid, row)
    response = c[EDITOR].post(f'/api/runs/{rid}/copy')
    assert response.status_code == 200, response.text
    copied = response.json()['run_id']
    assert copied != rid and response.json()['owner'] == EDITOR
    assert c[ADMIN].get(f'/api/runs/{copied}').status_code == 404
    save(c[EDITOR], copied, row, 'Independent change')
    assert c[ADMIN].get(f'/api/runs/{rid}/results/{row}').json()['decisions']['1']['comment'] == 'Checked'
    source = json.loads(Path(ws.runs.get(rid)['json_path']).read_text())
    clone = json.loads(Path(ws.runs.get(copied)['json_path']).read_text())
    assert source['documents'][0]['path'] != clone['documents'][0]['path']
    assert Path(clone['documents'][0]['path']).read_bytes() == Path(source['documents'][0]['path']).read_bytes()
    archive = c[EDITOR].get(f'/api/runs/{copied}/download.zip')
    assert archive.status_code == 200, archive.text
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        assert {'run.json','review.xlsx','history.json','README.txt'} <= set(z.namelist())
        payload = json.loads(z.read('run.json'))
        assert payload['documents'][0]['path'] in z.namelist()


def test_comparison_requires_both_runs(env, sample):
    ws, access, c, rid, row = env
    clone = c[EDITOR].post(f'/api/runs/{rid}/copy').json()['run_id']
    assert c[ADMIN].get(f'/api/runs/{rid}/diff', params={'against':clone}).status_code == 404
    assert c[EDITOR].get(f'/api/runs/{clone}/diff', params={'against':rid}).status_code == 200


def test_same_origin_mutations(env):
    assert env[2][ADMIN].post('/api/demo/load', headers={'Origin':'https://other.example'}).status_code == 403


def test_approval_by_another_editor_and_export_history(env):
    import openpyxl
    ws, access, c, rid, row = env
    detail = save(c[ADMIN], rid, row)
    response = c[EDITOR].post(f'/api/runs/{rid}/finalize', json={'row_id':row,'final_decision':'ACCEPT','expected_revision':detail['revision']})
    assert response.status_code == 200, response.text
    assert c[EDITOR].get(f'/api/runs/{rid}/results/{row}').json()['final']['self_approved'] is False
    detail = save(c[EDITOR], rid, row, 'My own edit')
    assert c[EDITOR].post(f'/api/runs/{rid}/finalize', json={'row_id':row,'final_decision':'ACCEPT','expected_revision':detail['revision'],'confirm_self_approval':True}).status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(c[EDITOR].get(f'/api/runs/{rid}/export.xlsx').content))
    events = list(wb['Approval history'].values)
    assert events[-1][-1] == 'Yes' and events[-1][2] == EDITOR
    clone = c[EDITOR].post(f'/api/runs/{rid}/copy').json()['run_id']
    assert c[EDITOR].get(f'/api/runs/{clone}/results/{row}').json()['final'] is None
    assert c[ADMIN].get(f'/api/runs/{rid}/results/{row}').json()['final'] is not None


def test_action_items_do_not_leak_or_change_other_runs(env):
    ws, access, c, rid, row = env
    result = next(r for r in json.loads(Path(ws.runs.get(rid)['json_path']).read_text())['results'] if r['discrepancies'])
    response = c[EDITOR].post(f'/api/runs/{rid}/action-items', json={'row_id':result['row_id']})
    assert response.status_code == 200, response.text
    ai = response.json()['id']
    assert c[OUTSIDER].get('/api/action-items').json() == []
    assert c[VIEWER].patch(f'/api/action-items/{ai}', json={'status':'RESOLVED'}).status_code == 403
    assert c[OUTSIDER].patch(f'/api/action-items/{ai}', json={'status':'RESOLVED'}).status_code == 404
    clone = c[EDITOR].post(f'/api/runs/{rid}/copy').json()['run_id']
    copied_items = c[EDITOR].get('/api/action-items', params={'run_id':clone}).json()
    assert len(copied_items) == 1 and copied_items[0]['id'] != ai
    c[EDITOR].post(f'/api/runs/{clone}/verify-and-close')
    assert c[ADMIN].get('/api/action-items', params={'run_id':rid}).json()[0]['status'] == 'OPEN'


def test_document_previews_and_items_require_sharing(env):
    ws, access, c, rid, row = env
    doc = c[EDITOR].get(f'/api/runs/{rid}/documents').json()[0]['id']
    for suffix in (f'/documents/{doc}/items', f'/documents/{doc}/pages/1'):
        assert c[OUTSIDER].get(f'/api/runs/{rid}{suffix}').status_code == 404
        assert c[VIEWER].get(f'/api/runs/{rid}{suffix}').status_code == 200


def test_repeated_upload_is_a_new_owned_run(env, sample):
    ws, access, c, rid, row = env
    file = Path(sample.documents[0].path)
    results = []
    for _ in range(2):
        response = c[EDITOR].post('/api/runs/upload', files={'files': ('Project/bom.pdf', file.read_bytes(), 'application/pdf')}, data={'name':'My project review'})
        assert response.status_code == 200, response.text
        results.append(response.json())
    assert results[0]['run_id'] != results[1]['run_id']
    assert all(r['owner'] == EDITOR and r['name'] == 'My project review' for r in results)
    assert c[ADMIN].get(f"/api/runs/{results[0]['run_id']}").status_code == 404


def test_sharing_and_accounts_survive_app_restart(env):
    ws, access, c, rid, row = env
    restarted = TestClient(create_app(ws, accounts=LocalAccounts(ws.db)))
    assert restarted.post('/api/auth/signin', json={'email':EDITOR,'password':PW}).status_code == 200
    assert restarted.get(f'/api/runs/{rid}').json()['permission'] == 'edit'
    assert c[ADMIN].put(f'/api/runs/{rid}/sharing', json={'email':EDITOR,'permission':'view'}).status_code == 200
    assert restarted.post(f'/api/runs/{rid}/copy').status_code == 403
