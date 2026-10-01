"""FastAPI backend for approved accounts and shared document reviews."""

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pymupdf
from fastapi import Body, Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi import Response as FastResponse
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from kaizen import __version__
from kaizen.api.payloads import (
    ActionInput,
    ActionUpdate,
    ApprovalInput,
    ChangeNote,
    Credentials,
    DecisionInput,
    MiningInput,
    RelationshipInput,
    RelationshipUpdate,
    RowRelationship,
    RunName,
    RunPath,
    RunShare,
    UserUpdate,
)
from kaizen.models import Classification, DocType, Run, Thresholds
from kaizen.pipeline import SUPPORTED_SUFFIXES, load_run, run_folder, save_run
from kaizen.reporting.annotated_bom import write_annotated_bom
from kaizen.reporting.certificate import write_certificate, write_run_certificate
from kaizen.reporting.excel import ReviewBundle, export_with_review
from kaizen.reporting.excel_import import import_decisions
from kaizen.review.access import AccessStore, bd_email
from kaizen.review.action_items import ActionItemStore
from kaizen.review.auth import AuthError, LocalAccounts, SupabaseAccounts, accounts_for
from kaizen.review.business import BusinessAssumptions, business_case
from kaizen.review.collaborative import CollaborativeReviewStore
from kaizen.review.copies import copy_run, portable_payload, snapshot
from kaizen.review.mining import approve_suggestion, mine_suggestions, reject_suggestion, terminology_worklist
from kaizen.review.progress import review_snapshot
from kaizen.review.rundiff import diff_runs
from kaizen.review.sessions import ReviewSession, SessionStore
from kaizen.review.store import ReviewStore
from kaizen.terminology.exchange import export_xlsx
from kaizen.terminology.source_import import import_source, inspect_source
from kaizen.workspace import Workspace

SESSION_COOKIE = "kaizen_session"
SIGN_IN_HINT = "Sign in first: POST /api/auth/signin with your approved BD email and password."
BLIND_REFUSAL = "Not available while you are reviewing blind: it would reveal reviewer 1's decisions. End your blind session or ask reviewer 1."
API_CONTRACT = 3
MAX_UPLOAD_BYTES = 250 * 1024 * 1024
MAX_IMPORT_BYTES = 10 * 1024 * 1024
logger = logging.getLogger(__name__)


async def _save_import(file: UploadFile, dest: Path) -> None:
    total = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open('wb') as output:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_IMPORT_BYTES:
                raise HTTPException(413, 'Import a workbook or CSV of at most 10 MB.')
            output.write(chunk)


def _source_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*.py')):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()

# ---- sign-in -----------------------------------------------------------------------------------
def _bd_email(raw: str) -> str:
    """The address, normalised, or a 400. The domain must match a whole allowed domain: splitting on the
    last `@` and comparing for equality is what stops `someone@bd.com.evil.io` from passing as BD."""
    try:
        return bd_email(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))



SEVERITY_RANK = {"BLOCKER": 0, "MAJOR": 1, "MINOR": 2, "INFO": 3, None: 4}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _demo_dataset_path() -> Path | None:

    env = os.environ.get("KAIZEN_DEMO_DATA")
    candidates = [Path(env)] if env else []
    candidates.append(Path(__file__).resolve().parents[3] / "datasets" / "golden")
    candidates.append(Path.cwd() / "datasets" / "golden")
    return next((c for c in candidates if (c / "ground-truth.json").exists()), None)


class RunCache:
    def __init__(self, ws: Workspace):
        self.ws = ws
        self._runs: dict[str, Run] = {}

    def get(self, run_id: str) -> Run:
        if run_id in self._runs:
            return self._runs[run_id]
        rec = self.ws.runs.get(run_id)
        if rec is None:
            raise HTTPException(404, f"run {run_id} not found")
        try:
            run = load_run(rec["json_path"])
        except FileNotFoundError:
            raise HTTPException(404, "The saved run is unavailable. Upload its source documents again.")
        self._runs[run_id] = run
        return run

    def put(self, run: Run) -> Path:
        path = save_run(run, self.ws.runs_dir / run.metadata.run_id / "run.json")
        self.ws.register_run(run, path)
        self._runs[run.metadata.run_id] = run
        return path


def _summary(run: Run, review: ReviewStore, viewer_slot: int = 1, blind: bool = False) -> dict[str, Any]:
    from kaizen.review.business import reviewable

    rev = reviewable(run)
    counts = {c.value: sum(1 for r in rev if r.classification is c) for c in Classification}
    needs = sum(1 for r in rev if r.requires_validation)
    header_needs = sum(1 for r in run.results if r.role in ("header", "reference", "coverage") and r.requires_validation)
    _, progress, states = review_snapshot(run, review, viewer_slot, blind)
    return {
        "run_id": run.metadata.run_id, "timestamp": run.metadata.timestamp.isoformat(), "input_root": run.metadata.input_root, "tool_version": run.metadata.tool_version,
        "skus": len(run.groups), "documents": len(run.documents), "documents_by_type": {t: sum(1 for d in run.documents if d.doc_type.value == t) for t in ("BOM", "LABEL", "DRAWING", "PCO")},
        "unrecognised_files": [i.path for i in run.metadata.inputs if i.doc_type is None], "rows": len(run.results), "reviewable_rows": len(rev), "exempt_rows": sum(1 for r in run.results if r.role == "exempt"), "header_rows_needing_validation": header_needs,
        "counts": counts, "needs_validation": needs, "auto_cleared": len(rev) - needs,
        "per_check": {ct: sum(1 for r in run.results if r.check.value == ct) for ct in ("BOM_LABEL", "BOM_DRAWING", "LABEL_DRAWING", "PCO_BOM", "LABEL_REVISION")},
        "blockers": sum(1 for r in run.results for d in r.discrepancies if d.severity.value == "BLOCKER"),
        "coverage": [c.model_dump() for c in run.coverage], "groups": [g.model_dump() for g in run.groups], "warnings": run.warnings,
        "parser_warnings": [{"document": Path(d.path).name, "doc_id": d.id, "warnings": d.warnings} for d in run.documents if d.warnings],
        "low_confidence_rows": sum(1 for r in run.results for d in r.discrepancies if d.type.value == "LOW_EXTRACTION_CONFIDENCE"),
        "state_counts": states, "review_progress": progress, "terminology_version": run.metadata.terminology_version, "terminology_count": run.metadata.terminology_count,
        "relationships_used": run.relationships_used, "capabilities": run.metadata.capabilities, "thresholds": run.metadata.thresholds.model_dump(),
        "inputs": [i.model_dump() for i in run.metadata.inputs],
    }


def _evidence(item) -> dict[str, Any] | None:
    if item is None:
        return None
    ev = item.evidence
    return {"doc_id": item.doc_id, "doc_type": item.doc_type.value, "file": ev.file, "file_name": Path(ev.file).name, "sha256": ev.file_sha256, "page": ev.page, "bbox": ev.bbox.model_dump() if ev.bbox else None, "locator": ev.locator, "raw_text": ev.raw_text, "sheet": ev.sheet,
            "item_number": item.item_number, "description": item.description, "quantity": str(item.quantity) if item.quantity is not None else None, "uom": item.uom, "oper_seq": item.oper_seq, "category": item.category.value, "category_reason": item.category_reason, "confidence": item.extraction_confidence, "attributes": item.attributes, "sub_quantity": item.sub_quantity.model_dump() if item.sub_quantity else None}


def _queue_sort_key(r):
    types = {d['type'] for d in r['current_discrepancies']}
    return (SEVERITY_RANK[r['current_severity']], 0 if "AMBIGUOUS_MATCH" in types else 1, 0 if r['effective_classification'] == 'POTENTIAL' else 1, 0 if "LOW_EXTRACTION_CONFIDENCE" in types else 1, r['sku'], r['row_id'])


def create_app(workspace: Workspace | None = None, ui_dir: Path | None = None, accounts: LocalAccounts | SupabaseAccounts | None = None) -> FastAPI:
    ws = workspace or Workspace.resolve(None)
    app = FastAPI(title="Kaizen Cross-Check", version=__version__)
    source_fingerprint = _source_fingerprint()

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        reference = uuid.uuid4().hex[:12]
        logger.error("Request %s failed: %s %s", reference, request.method, request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": f"The server could not complete this request. Error reference: {reference}. See the Kaizen server log for details."})

    cache = RunCache(ws)
    review = CollaborativeReviewStore(ws.db)
    access = AccessStore(ws.db)
    items = ActionItemStore(ws.db)
    sessions = SessionStore(ws.db)
    # Where email + password are checked: this workspace, or Supabase (see kaizen.review.auth). Only the
    # credentials move; sessions, slots, blind mode and decisions always stay in the workspace.
    accounts = accounts or accounts_for(ws.db)
    if os.environ.get("KAIZEN_ADMIN_EMAIL"):
        if accounts.name != 'local':
            raise ValueError('Initial administrator bootstrap requires local accounts. Bootstrap before enabling Supabase.')
        access.bootstrap(os.environ['KAIZEN_ADMIN_EMAIL'], os.environ.get('KAIZEN_ADMIN_PASSWORD'))

    # ---- reviewer sessions --------------------------------------------------------------------
    # Identity, slot and blind mode are server-side. The token lives in an HttpOnly cookie so page
    # scripts cannot read or forge it, and `viewer`/`blind` query parameters are ignored whenever a
    # session is present.

    def _open_session(kaizen_session: str | None = Cookie(default=None)) -> ReviewSession | None:
        session = sessions.resolve(kaizen_session)
        profile = access.profile(session.reviewer) if session else None
        return replace(session, slot=1, blind=False) if profile and profile['status'] == 'approved' else None

    def _identified(session: ReviewSession | None = Depends(_open_session)) -> ReviewSession | None:
        if session is None:
            raise HTTPException(401, SIGN_IN_HINT)
        return session

    def _view_of(session: ReviewSession | None, viewer: int = 1, blind: bool = False) -> tuple[int, bool]:
        """The slot and blind flag actually used. A session always wins over the query string."""
        if session is not None:
            return session.slot, session.blind
        return (viewer if viewer in (1, 2) else 1), bool(blind)

    def _refuse_if_blind(session: ReviewSession | None) -> None:
        if session is not None and session.blind:
            raise HTTPException(403, BLIND_REFUSAL)

    def run_path(path: Path, actor: str, name: str = "") -> dict[str, Any]:
        if not path.is_dir():
            raise HTTPException(400, f"folder not found: {path}")
        if len(name.strip()) > 120:
            raise HTTPException(400, "Run name must contain at most 120 characters.")
        run = run_folder(path.resolve(), ws.repository.store(), Thresholds())
        if not any(doc.items or (doc.doc_type is DocType.DRAWING and (doc.sku or doc.header.get('drawing_number'))) for doc in run.documents):
            warnings = run.warnings + [warning for doc in run.documents for warning in doc.warnings]
            raise HTTPException(400, "No usable BOM, label, drawing or PCO data could be extracted. " + " ".join(warnings[:3]))
        run.metadata.run_id = uuid.uuid4().hex
        label = name.strip()[:120] or f"{path.name.replace('_', ' ').replace('-', ' ').title()} · Review · {datetime.now(timezone.utc):%d %b %Y}"
        try:
            with ws.db.transaction():
                cache.put(run)
                ws.db.conn.execute('UPDATE runs SET owner=?, name=? WHERE run_id=?', (actor, label, run.metadata.run_id))
        except Exception:
            cache._runs.pop(run.metadata.run_id, None)
            shutil.rmtree(ws.runs_dir / run.metadata.run_id, ignore_errors=True)
            raise
        return _summary(run, review) | run_info(run.metadata.run_id, actor)

    def require_run(run_id: str, actor: str, edit: bool = False, owner: bool = False):
        permission = access.permission(run_id, actor)
        if not permission:
            raise HTTPException(404, 'Run not found or not shared with you.')
        if owner and permission != 'owner':
            raise HTTPException(403, 'Only the run owner can manage sharing or rename it.')
        if edit and permission == 'view':
            raise HTTPException(403, 'This run is shared with view-only access.')
        return permission

    def authorize(request: Request, session=Depends(_open_session)):
        path = request.url.path
        # Cookie authentication also requires same-origin mutations in the hosted app.
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin and urlparse(origin).netloc != request.headers.get('host'):
                raise HTTPException(403, 'Cross-origin changes are not allowed.')
        if path in ('/api/auth/signin', '/api/auth/signup', '/api/sessions/current', '/api/health'):
            return
        if session is None:
            raise HTTPException(401, 'Sign in with an approved BD account.')
        actor = session.reviewer
        admin = bool(access.profile(actor)['is_admin'])
        if path.startswith('/api/admin') or path == '/api/audit' or path == '/api/runs/from-path':
            if not admin:
                raise HTTPException(403, 'Application administrator access required.')
        if path == '/api/runs/from-path' and os.environ.get('KAIZEN_HOSTED') == '1':
            raise HTTPException(403, 'Upload documents in the hosted app.')
        if path.startswith('/api/terminology') and request.method not in ('GET', 'HEAD') and not admin:
            raise HTTPException(403, 'Only application administrators can change shared terminology.')
        rid = request.path_params.get('run_id')
        if rid:
            edit = request.method not in ('GET', 'HEAD') or any(x in path for x in ('export.xlsx', 'certificate.pdf', 'annotated-bom', 'download.zip'))
            require_run(rid, actor, edit=edit, owner=path.endswith('/sharing') or (request.method == 'PATCH' and path == f'/api/runs/{rid}'))
            if path.endswith('/diff') and request.query_params.get('against'):
                require_run(request.query_params['against'], actor)
            if any(x in path for x in ('/relationships/from-row', '/mining/approve', '/mining/reject')) and not admin:
                raise HTTPException(403, 'Only application administrators can change shared terminology.')
        ai_id = request.path_params.get('ai_id')
        if ai_id:
            ai = items.get(ai_id)
            if ai is None:
                raise HTTPException(404, 'Action item not found.')
            require_run(ai.run_id, actor, edit=True)

    app.router.dependencies.append(Depends(authorize))

    def run_info(run_id, actor):
        rec = ws.runs.get(run_id)
        return {key: rec[key] for key in ('name', 'owner', 'copied_from')} | {'permission': access.permission(run_id, actor)}

    @app.get('/api/profiles')
    def profiles():
        return [dict(r) for r in ws.db.conn.execute("SELECT email FROM profiles WHERE status='approved' ORDER BY email")]

    @app.get('/api/admin/users')
    def admin_users():
        return [dict(r) for r in ws.db.conn.execute('SELECT * FROM profiles ORDER BY created_at DESC')]

    @app.patch('/api/admin/users/{email}')
    def update_user(email: str, payload: UserUpdate, session=Depends(_identified)):
        payload = payload.model_dump(exclude_unset=True)
        try:
            current = access.profile(email)
            if current is None:
                raise KeyError(email)
            if 'is_admin' in payload and type(payload['is_admin']) is not bool:
                raise ValueError('is_admin must be a boolean.')
            return access.update(email, session.reviewer, payload.get('status', current['status']), payload.get('is_admin', bool(current['is_admin'])))
        except KeyError:
            raise HTTPException(404, 'Account not found.')
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get('/api/runs/{run_id}/sharing')
    def get_sharing(run_id: str):
        return [dict(r) for r in ws.db.conn.execute('SELECT email,permission,shared_by,shared_at FROM run_shares WHERE run_id=? ORDER BY email', (run_id,))]

    @app.put('/api/runs/{run_id}/sharing')
    def share_run(run_id: str, payload: RunShare, session=Depends(_identified)):
        payload = payload.model_dump()
        try:
            access.share(run_id, payload.get('email', ''), payload.get('permission'), session.reviewer)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return get_sharing(run_id)

    @app.patch('/api/runs/{run_id}')
    def rename_run(run_id: str, payload: RunName, session=Depends(_identified)):
        payload = payload.model_dump()
        name = str(payload.get('name', '')).strip()
        if not name or len(name) > 120:
            raise HTTPException(400, 'Run name must contain 1–120 characters.')
        with ws.db.lock:
            ws.db.conn.execute('UPDATE runs SET name=? WHERE run_id=?', (name, run_id))
            ws.db.audit(session.reviewer, 'run.renamed', f'{run_id}: {name}')
            ws.db.conn.commit()
        return run_info(run_id, session.reviewer)

    @app.post('/api/runs/{run_id}/copy')
    def make_copy(run_id: str, session=Depends(_identified)):
        try:
            run = copy_run(ws, cache.get(run_id), session.reviewer)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _summary(run, review) | run_info(run.metadata.run_id, session.reviewer)

    @app.get('/api/runs/{run_id}/download.zip')
    def download_copy(run_id: str, session=Depends(_identified)):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        try:
            run = snapshot(cache.get(run_id), root / 'bundle', run_id)
            bundle = root / 'bundle'
            (bundle / 'run.json').write_text(json.dumps(portable_payload(run, bundle), indent=2))
            export_with_review(ws, run, bundle / 'review.xlsx')
            (bundle / 'history.json').write_text(json.dumps({r.row_id: review.history(run_id, r.row_id) for r in run.results}, indent=2))
            (bundle / 'README.txt').write_text('Independent Kaizen snapshot. Edit review.xlsx offline. To continue in Kaizen, first use Make a copy, then import your workbook into that copy. Original approvals do not transfer to a new copy. Source files and portable run.json are included.\n')
            archive = root / 'run.zip'
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
                for file in bundle.rglob('*'):
                    if file.is_file():
                        z.write(file, file.relative_to(bundle))
            return FileResponse(archive, filename=f'{run_id}-independent-copy.zip', background=BackgroundTask(temporary.cleanup))
        except ValueError as e:
            temporary.cleanup()
            raise HTTPException(400, str(e))
        except Exception:
            temporary.cleanup()
            raise

    # ---- sign-up and sign-in --------------------------------------------------------------------
    # A session can only be opened by someone holding an account on a BD address. Only /api/auth/signin
    # reaches SessionStore.open, so there is one door.

    def _start_session(response: FastResponse, reviewer: str, payload: dict) -> dict:
        try:
            s = sessions.open(reviewer, 1, False)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))
        response.set_cookie(SESSION_COOKIE, s.token, httponly=True, secure=os.environ.get("KAIZEN_SECURE_COOKIES") == "1", samesite="lax", path="/")
        return s.to_dict("required") | {"is_admin": bool(access.profile(reviewer)["is_admin"])}

    @app.post("/api/auth/signup")
    def signup(payload: Credentials):
        """Register a BD account; access remains pending until an administrator approves it."""
        payload = payload.model_dump()
        email = _bd_email(payload.get("email", ""))
        try:
            accounts.sign_up(email, str(payload.get("password", "")))
        except AuthError as e:
            raise HTTPException(e.status, e.message)
        access.register(email)
        return {"ok": True, "email": email, "status": "pending"}

    @app.post("/api/auth/signin")
    def signin(response: FastResponse, payload: Credentials):
        """Open a session only after password verification and application approval."""
        payload = payload.model_dump()
        email = _bd_email(payload.get("email", ""))
        try:
            accounts.sign_in(email, str(payload.get("password", "")))
        except AuthError as e:
            raise HTTPException(e.status, e.message)
        profile = access.register(email)
        if profile['status'] != 'approved':
            raise HTTPException(403, 'Your account is awaiting administrator approval.' if profile['status'] == 'pending' else 'Your account has not been approved. Contact an administrator.')
        return _start_session(response, email, payload)

    # ---- runs ---------------------------------------------------------------------------------
    @app.post("/api/sessions")
    def open_session():
        """Kept only so an old cached bundle gets an explanation rather than a 404. There is no bypass."""
        raise HTTPException(403, "Use /api/auth/signin")

    @app.get("/api/sessions/current")
    def current_session(session: ReviewSession | None = Depends(_open_session)):
        return {"session": (session.to_dict("required") | {"is_admin": bool(access.profile(session.reviewer)["is_admin"])}) if session else None, "blind_review_policy": "required", "accounts": accounts.name}

    @app.delete("/api/sessions/current")
    def end_session(response: FastResponse, kaizen_session: str | None = Cookie(default=None)):
        ended = sessions.end(kaizen_session)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ended": ended}

    @app.get("/api/health")
    def health():
        try:
            restart_required = _source_fingerprint() != source_fingerprint
        except OSError:
            restart_required = True
        return {"status": "ok", "version": __version__, "api_contract": API_CONTRACT, "restart_required": restart_required, "hosted": os.environ.get("KAIZEN_HOSTED") == "1"}

    @app.get("/api/runs")
    def list_runs(session=Depends(_identified)):
        out = []
        for record in ws.runs.list():
            if not access.permission(record['run_id'], session.reviewer):
                continue
            try:
                summary = _summary(cache.get(record['run_id']), review)
                record['summary'] = {**summary['counts'], **{key: summary[key] for key in ('rows', 'reviewable_rows', 'skus', 'documents', 'needs_validation', 'auto_cleared', 'review_progress')}}
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                record['unavailable'] = True
            out.append(record | run_info(record['run_id'], session.reviewer))
        return out

    @app.post("/api/runs/from-path")
    def run_from_path(payload: RunPath, session=Depends(_identified)):
        payload = payload.model_dump()
        return run_path(Path(payload["path"]), session.reviewer, str(payload.get("name", "")))

    @app.post("/api/runs/upload")
    async def run_upload(files: list[UploadFile] = File(...), name: str = Form(""), session=Depends(_identified)):
        target = ws.path / "uploads" / uuid.uuid4().hex
        total = 0
        seen = set()
        try:
            if not files or not any(Path(f.filename or "").suffix.lower() in SUPPORTED_SUFFIXES for f in files):
                raise HTTPException(400, "Choose a folder containing PDF, XLSX, XLSM or CSV documents.")
            for f in files:
                filename = (f.filename or "").replace("\\", "/")
                rel = Path(filename)
                if not filename or "\x00" in filename or re.match(r"^[A-Za-z]:", filename) or rel.is_absolute() or ".." in rel.parts or not rel.name or rel in seen:
                    raise HTTPException(400, f"Invalid or duplicate upload path: {f.filename}")
                seen.add(rel)
                if rel.suffix.lower() not in SUPPORTED_SUFFIXES or rel.name.startswith((".", "~$")):
                    continue
                if any(parent in seen for parent in rel.parents) or any(rel in other.parents for other in seen):
                    raise HTTPException(400, "An upload path is used as both a file and a folder.")
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('wb') as output:
                    while chunk := await f.read(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_UPLOAD_BYTES:
                            raise HTTPException(413, 'Upload at most 250 MB per run.')
                        output.write(chunk)
            label = name or f"{Path(files[0].filename or 'Project').parts[0]} · Review · {datetime.now(timezone.utc):%d %b %Y}"
            return await run_in_threadpool(run_path, target, session.reviewer, label)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        finally:
            for file in files:
                await file.close()

    @app.post("/api/demo/load")
    def demo_load(session=Depends(_identified)):
        src = _demo_dataset_path()
        if src is None:
            from kaizen.datasets.build import build_golden

            src = build_golden(ws.path / "demo-data")
        return run_path(src, session.reviewer, "Demo · BOM cross-check")

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, session: ReviewSession | None = Depends(_identified)):
        return _summary(cache.get(run_id), review) | run_info(run_id, session.reviewer)

    @app.get("/api/runs/{run_id}/results")
    def get_results(run_id: str, check: str | None = None, sku: str | None = None, classification: str | None = None, engine_classification: str | None = None, severity: str | None = None, discrepancy: str | None = None, needs_validation: bool | None = None, unresolved: bool | None = None, state: str | None = None, role: str | None = None, viewer: int = 1, blind: bool = False, limit: int = Query(500, ge=1, le=5000), offset: int = Query(0, ge=0), search: str | None = None, session: ReviewSession | None = Depends(_identified)):
        slot, blind = _view_of(session, viewer, blind)
        run = cache.get(run_id)
        rows = run.results
        if check:
            rows = [r for r in rows if r.check.value == check]
        if sku:
            rows = [r for r in rows if r.sku == sku]
        if engine_classification:
            rows = [r for r in rows if r.classification.value == engine_classification]
        if role:
            rows = [r for r in rows if r.role == role]
        if search:
            s = search.lower()
            rows = [r for r in rows if s in r.sku.lower() or s in r.explanation.lower() or any(s in (item.description + " " + (item.item_number or "")).lower() for item in (r.source_a, r.source_b) if item)]
        by_id = {r.row_id: r for r in rows}
        snapshot_rows, _, _ = review_snapshot(run, review, slot, blind)
        selected_ids = {r.row_id for r in rows}
        merged = [m for m in snapshot_rows if m['row_id'] in selected_ids]
        if classification:
            merged = [m for m in merged if m['effective_classification'] == classification]
        if severity:
            merged = [m for m in merged if m['current_severity'] == severity]
        if discrepancy:
            if unresolved:
                merged = [m for m in merged if any(d['type'] == discrepancy for d in m['current_discrepancies'])]
            else:
                merged = [m for m in merged if any(d.type.value == discrepancy for d in by_id[m['row_id']].discrepancies)]
        if needs_validation is not None:
            merged = [m for m in merged if m['pending_review'] == needs_validation]
        if unresolved is not None:
            merged = [m for m in merged if m['unresolved'] == unresolved]
        if state:
            merged = [m for m in merged if m["state"] == state]
        merged.sort(key=_queue_sort_key)
        total = len(merged)
        page = merged[offset : offset + limit]
        for m in page:
            r = by_id[m["row_id"]]
            m["a"] = {"item_number": r.source_a.item_number, "description": r.source_a.description, "quantity": str(r.source_a.quantity) if r.source_a.quantity is not None else None, "page": r.source_a.evidence.page, "locator": r.source_a.evidence.locator, "file_name": Path(r.source_a.evidence.file).name} if r.source_a else None
            m["b"] = {"item_number": r.source_b.item_number, "description": r.source_b.description, "quantity": str(r.source_b.quantity) if r.source_b.quantity is not None else None, "page": r.source_b.evidence.page, "locator": r.source_b.evidence.locator, "file_name": Path(r.source_b.evidence.file).name} if r.source_b else None
            m["discrepancies"] = [d.model_dump() for d in r.discrepancies]
            m["action_items"] = [a.id for a in items.for_row(run_id, r.row_id)]
        return {"total": total, "offset": offset, "limit": limit, "rows": page, "viewer": {"slot": slot, "blind": blind, "reviewer": session.reviewer if session else None}}

    def _find(run: Run, row_id: str):
        r = next((r for r in run.results if r.row_id == row_id), None)
        if r is None:
            raise HTTPException(404, f"row {row_id} not found")
        return r

    @app.get("/api/runs/{run_id}/results/{row_id}")
    def get_row(run_id: str, row_id: str, viewer: int = 1, blind: bool = False, session: ReviewSession | None = Depends(_identified)):
        # A revision must describe exactly the decision snapshot shown to the user.
        with ws.db.lock:
            slot, blind = _view_of(session, viewer, blind)
            run = cache.get(run_id)
            r = _find(run, row_id)
            merged = review.rows_for_viewer(run_id, [r], viewer_slot=slot, blind=blind)[0]
            hidden = ReviewStore.is_blind_hidden(review.decisions(run_id, row_id), slot, blind)
            if session is not None and access.permission(run_id, session.reviewer) != "view":
                review.mark_opened(run_id, row_id, session.slot)  # starts the effort clock for this reviewer
            return {"result": r.model_dump(mode="json"), "evidence": {"a": _evidence(r.source_a), "b": _evidence(r.source_b)}, "decisions": {str(k): v for k, v in merged["decisions"].items()}, "state": merged["state"], "final": merged["final"], "effective_classification": merged["effective_classification"], "permission": access.permission(run_id, session.reviewer), "revision": review.revision(run_id, row_id), "owner": ws.runs.get(run_id)["owner"], "history": [{"event": "engine", "detail": "engine recommendation recorded with the run"}] if hidden else review.history(run_id, row_id), "viewer": {"slot": slot, "blind": blind, "reviewer": session.reviewer if session else None}, "action_items": [asdict(a) for a in items.for_row(run_id, row_id)]}

    @app.get("/api/runs/{run_id}/documents")
    def get_documents(run_id: str):
        run = cache.get(run_id)
        return [{"id": d.id, "doc_type": d.doc_type.value, "file": d.path, "file_name": Path(d.path).name, "sku": d.sku, "sha256": d.sha256, "parser": d.parser_name, "parser_version": d.parser_version, "items": len(d.items), "warnings": d.warnings, "header": d.header, "pages": _page_count(d.path)} for d in run.documents]

    def _doc(run: Run, doc_id: str):
        d = next((d for d in run.documents if d.id == doc_id), None)
        if d is None:
            raise HTTPException(404, f"document {doc_id} not found")
        return d

    @app.get("/api/runs/{run_id}/documents/{doc_id}/items")
    def get_document_items(run_id: str, doc_id: str):
        d = _doc(cache.get(run_id), doc_id)
        return {"doc_id": d.id, "doc_type": d.doc_type.value, "file_name": Path(d.path).name, "header": d.header, "warnings": d.warnings, "pages": _page_count(d.path), "items": [_evidence(i) | {"id": i.id, "is_active": i.is_active} for i in d.items]}

    @app.get("/api/runs/{run_id}/documents/{doc_id}/pages/{page_no}")
    def get_page_image(run_id: str, doc_id: str, page_no: int, highlight: str | None = None, dpi: int = Query(110, ge=36, le=300)):
        run = cache.get(run_id)
        d = _doc(run, doc_id)
        if not d.path.lower().endswith(".pdf"):
            raise HTTPException(404, "document has no page images (spreadsheet source)")
        if not Path(d.path).is_file():
            raise HTTPException(404, "Source document is unavailable. Upload it again to view its pages.")
        with pymupdf.open(d.path) as pdf:
            if page_no < 1 or page_no > len(pdf):
                raise HTTPException(404, "page out of range")
            page = pdf[page_no - 1]
            if highlight:
                r = _find(run, highlight)
                for item in (r.source_a, r.source_b):
                    if item is not None and item.doc_id == doc_id and item.evidence.bbox is not None and item.evidence.page == page_no:
                        b = item.evidence.bbox
                        shape = page.new_shape()
                        shape.draw_rect(pymupdf.Rect(b.x0 - 2, b.y0 - 2, b.x1 + 2, b.y1 + 2) * page.derotation_matrix)
                        shape.finish(color=(0.9, 0.1, 0.1), fill=(1, 0.85, 0.2), fill_opacity=0.25, width=1.2)
                        shape.commit()
            png = page.get_pixmap(dpi=dpi).tobytes("png")
        return Response(content=png, media_type="image/png")

    # ---- review -------------------------------------------------------------------------------
    @app.post("/api/runs/{run_id}/decisions")
    def post_decision(run_id: str, payload: DecisionInput, session: ReviewSession | None = Depends(_identified)):
        payload = payload.model_dump()
        run = cache.get(run_id)
        _find(run, payload["row_id"])
        slot, blind = _view_of(session)
        try:
            with ws.db.lock:
                if payload.get('expected_revision') != review.revision(run_id, payload['row_id']):
                    raise HTTPException(409, 'This row changed. Refresh before saving your decision.')
                review.decide(run_id, payload["row_id"], slot, session.reviewer, payload["decision"], payload.get("comment", ""), payload.get("override_classification"), blind)
        except ValueError as e:
            raise HTTPException(400, str(e))
        merged = review.rows_for_viewer(run_id, [_find(run, payload["row_id"])], viewer_slot=slot, blind=blind)[0]
        return {"row_id": payload["row_id"], "state": merged["state"], "decisions": {str(k): v for k, v in merged["decisions"].items()}, "effective_classification": merged["effective_classification"]}

    @app.post("/api/runs/{run_id}/finalize")
    def post_final(run_id: str, payload: ApprovalInput, session: ReviewSession | None = Depends(_identified)):
        payload = payload.model_dump()
        _find(cache.get(run_id), payload["row_id"])
        slot, blind = _view_of(session)
        if ReviewStore.is_blind_hidden(review.decisions(run_id, payload["row_id"]), slot, blind):
            raise HTTPException(403, "Record your own decision on this row before closing it: you cannot see reviewer 1's yet.")
        try:
            review.approve(run_id, payload["row_id"], payload["final_decision"], session.reviewer, payload.get("note", ""), payload.get("expected_revision"), payload.get("confirm_self_approval"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"row_id": payload["row_id"], "state": review.row_state(run_id, payload["row_id"]).state}

    @app.post("/api/runs/{run_id}/bulk-accept")
    def post_bulk(run_id: str, payload: dict = Body(...), session: ReviewSession | None = Depends(_identified)):
        run = cache.get(run_id)
        slot, _ = _view_of(session)
        return {"accepted": review.bulk_accept_clean(run_id, run.results, slot, session.reviewer)}

    @app.post("/api/runs/{run_id}/relationships/from-row")
    def relationship_from_row(run_id: str, payload: RowRelationship, session: ReviewSession | None = Depends(_identified)):
        payload = payload.model_dump()
        run = cache.get(run_id)
        r = _find(run, payload["row_id"])
        if r.source_a is None or r.source_b is None:
            raise HTTPException(400, "row has no pair to save as a relationship")
        canonical = payload.get("canonical") or r.source_b.description
        aliases = payload.get("aliases") or [r.source_a.description]
        anchors = [r.source_a.item_number] if payload.get("anchor") and r.source_a.item_number else []
        try:
            rel = ws.repository.create(canonical=canonical, aliases=aliases, scope=payload.get("scope", "global"), doc_types=payload.get("doc_types", []), item_anchors=anchors, provenance="learned", created_by=session.reviewer, notes=payload.get("notes") or f"Saved from run {run_id} row {r.row_id} ({r.check.value}, {r.sku}); engine said {r.classification.value}")
        except ValueError as e:
            raise HTTPException(400, str(e))
        ws.db.audit(session.reviewer, "relationship.learned", f"{rel.id} from {run_id} {r.row_id}")
        ws.db.conn.commit()
        return rel.model_dump(mode="json")

    @app.get("/api/runs/{run_id}/terminology-worklist")
    def get_worklist(run_id: str, session: ReviewSession | None = Depends(_identified)):
        """Unconfirmed pairings ranked by the rows they would auto-clear once approved (human approval still required)."""
        run = cache.get(run_id)
        return terminology_worklist(run, review, ws.repository).to_dict()

    @app.get("/api/runs/{run_id}/mining")
    def get_mining(run_id: str, min_skus: int = 2):
        run = cache.get(run_id)
        return [asdict(s) | {"evidence": s.evidence, "pair_key": s.pair_key} for s in mine_suggestions(run, review, ws.repository, min_skus=min_skus)]

    def _suggestion(run_id: str, a_key: str, b_key: str):
        run = cache.get(run_id)
        s = next((s for s in mine_suggestions(run, review, ws.repository, min_skus=1) if s.a_key == a_key and s.b_key == b_key), None)
        if s is None:
            raise HTTPException(404, "suggestion not found (already approved or rejected?)")
        return s

    @app.post("/api/runs/{run_id}/mining/approve")
    def approve(run_id: str, payload: MiningInput, session: ReviewSession | None = Depends(_identified)):
        payload = payload.model_dump()
        s = _suggestion(run_id, payload["a_key"], payload["b_key"])
        try:
            return approve_suggestion(ws.repository, s, session.reviewer, payload.get("scope", "global"), payload.get("anchor", False), payload.get("notes", "")).model_dump(mode="json")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/runs/{run_id}/mining/reject")
    def reject(run_id: str, payload: MiningInput, session: ReviewSession | None = Depends(_identified)):
        payload = payload.model_dump()
        s = _suggestion(run_id, payload["a_key"], payload["b_key"])
        reject_suggestion(ws.db, s, session.reviewer, payload.get("note", ""))
        return {"rejected": s.pair_key}

    # ---- action items ------------------------------------------------------------------------
    @app.post("/api/runs/{run_id}/action-items")
    def create_action_item(run_id: str, payload: ActionInput, session: ReviewSession | None = Depends(_identified)):
        payload = payload.model_dump()
        run = cache.get(run_id)
        r = _find(run, payload["row_id"])
        try:
            return asdict(items.create_from_result(run, r, session.reviewer, payload.get("owner", "")))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/action-items")
    def list_action_items(status: str | None = None, run_id: str | None = None, session=Depends(_identified)):
        out = items.for_run(run_id) if run_id else items.list(status)
        if status and run_id:
            out = [a for a in out if a.status == status]
        return [asdict(a) | {"permission": access.permission(a.run_id, session.reviewer)} for a in out if access.permission(a.run_id, session.reviewer)]

    @app.patch("/api/action-items/{ai_id}")
    def patch_action_item(ai_id: str, payload: ActionUpdate, session: ReviewSession | None = Depends(_identified)):
        payload = payload.model_dump(exclude_unset=True)
        try:
            return asdict(items.update(ai_id, session.reviewer, payload.get("status"), payload.get("owner"), payload.get("note", "")))
        except KeyError:
            raise HTTPException(404, "action item not found")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/runs/{run_id}/verify-and-close")
    def verify_and_close(run_id: str, against: str | None = None, session=Depends(_identified)):
        allowed = {run_id}
        if against:
            require_run(against, session.reviewer, edit=True)
            allowed.add(against)
        return asdict(items.verify_and_close(cache.get(run_id), by=session.reviewer, allowed_run_ids=allowed))

    @app.get("/api/runs/{run_id}/business-case")
    def get_business_case(run_id: str, baseline_minutes_per_sku: float = Query(60.0, gt=0, allow_inf_nan=False), hourly_rate: float = Query(37.5, ge=0, allow_inf_nan=False), skus_per_project: int = Query(100, ge=1), projects_per_year: int = Query(20, ge=0), reviewers: int = Query(2, ge=1), minutes_per_validation_row: float = Query(1.5, ge=0, allow_inf_nan=False), minutes_per_cleared_row: float = Query(0.1, ge=0, allow_inf_nan=False), target_reduction_pct: float = Query(50.0, ge=0, le=100, allow_inf_nan=False)):
        return business_case(cache.get(run_id), BusinessAssumptions(baseline_minutes_per_sku, hourly_rate, skus_per_project, projects_per_year, reviewers, minutes_per_validation_row, minutes_per_cleared_row, target_reduction_pct), timing=review.timing(run_id)).to_dict()

    # ---- exports -----------------------------------------------------------------------------
    @app.get("/api/runs/{run_id}/export.xlsx")
    def export_run(run_id: str, session: ReviewSession | None = Depends(_identified)):
        _refuse_if_blind(session)
        run = cache.get(run_id)
        path = export_with_review(ws, run, ws.runs_dir / run_id / "report.xlsx")
        return FileResponse(path, media_type=XLSX, filename=f"kaizen-{run_id}.xlsx")

    @app.get("/api/runs/{run_id}/annotated-bom/{doc_id}")
    def annotated_bom(run_id: str, doc_id: str, session: ReviewSession | None = Depends(_identified)):
        _refuse_if_blind(session)
        run = cache.get(run_id)
        d = _doc(run, doc_id)
        decisions = review.all_decisions(run_id)
        names = sorted({dec.reviewer for slots in decisions.values() for dec in slots.values()})
        states: dict[str, str] = {}
        for row_id, slots in decisions.items():
            last = slots.get(2) or slots.get(1)
            if last and last.decision == "ACCEPT":
                states[row_id] = "clear"
            elif last and last.decision == "CONFIRM_DISCREPANCY":
                states[row_id] = "discrepancy"
        out = write_annotated_bom(run, d, ws.runs_dir / run_id / f"annotated-{re.sub(r'[^A-Za-z0-9]+', '_', d.sku or doc_id)}.pdf", checked_by=names or None, review_states=states)
        return FileResponse(out.path, media_type="application/pdf", filename=out.path.name, headers={"X-Kaizen-Fallback": "true" if out.fallback else "false", "X-Kaizen-Marks": str(out.marks)})

    # ---- certificate, run diff, optional Excel round-trip ---------------------------------------
    def _bundle(run: Run) -> ReviewBundle:
        rid = run.metadata.run_id
        decisions, finals = review.all_decisions(rid), review.finals(rid)
        states = {r.row_id: review.state_of(decisions.get(r.row_id, {}), finals.get(r.row_id)) for r in run.results}
        return ReviewBundle(decisions=decisions, finals=finals, states=states, action_items=items.for_run(rid))

    @app.get("/api/runs/{run_id}/certificate.pdf")
    def certificate(run_id: str, sku: str | None = None, session: ReviewSession | None = Depends(_identified)):
        """One page per SKU (or one SKU): run id, file hashes, counts, named reviewers, open action items."""
        _refuse_if_blind(session)  # it lists both reviewers' decisions
        run = cache.get(run_id)
        target = ws.runs_dir / run_id / (f"certificate-{re.sub(r'[^A-Za-z0-9]+', '_', sku)}.pdf" if sku else "certificate.pdf")
        try:
            out = write_certificate(run, sku, target, _bundle(run)) if sku else write_run_certificate(run, target, _bundle(run))
        except ValueError as e:
            raise HTTPException(404, str(e))
        return FileResponse(out, media_type="application/pdf", filename=out.name)

    @app.get("/api/runs/{run_id}/diff")
    def run_diff(run_id: str, against: str, session: ReviewSession | None = Depends(_identified)):
        """What changed from run `against` (before) to `run_id` (after): resolved, new, still open."""
        after, before = cache.get(run_id), cache.get(against)
        return diff_runs(before, after).to_dict()

    @app.post("/api/runs/{run_id}/decisions/import")
    async def import_from_excel(run_id: str, file: UploadFile = File(...), dry_run: bool = Form(False), force: bool = Form(False), session: ReviewSession | None = Depends(_identified)):
        """Optional: apply the signed-in reviewer's decisions from an exported workbook. Slot and name come from the session."""
        if session is None:
            raise HTTPException(401, SIGN_IN_HINT)
        run = cache.get(run_id)
        folder = ws.runs_dir / run_id / "imports"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{uuid.uuid4().hex[:8]}-{re.sub(r'[^A-Za-z0-9._-]+', '_', Path(file.filename or 'decisions.xlsx').name)}"
        try:
            await _save_import(file, dest)
            result = await run_in_threadpool(import_decisions, ws, run, dest, session.slot, session.reviewer, dry_run=dry_run, force=force, review_store=review)
            return result.to_dict()
        except ValueError as e:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, str(e))
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        finally:
            if dry_run:
                dest.unlink(missing_ok=True)
            await file.close()

    # ---- terminology --------------------------------------------------------------------------
    def _rel(r, usage):
        return r.model_dump(mode="json") | {"usage": usage.get(r.id, 0)}

    @app.get("/api/terminology")
    def list_terminology(search: str | None = None, scope: str | None = None, all: bool = False):
        usage = ws.repository.usage_counts()
        return [_rel(r, usage) for r in ws.repository.list(active_only=not all, scope=scope, search=search)]

    @app.get("/api/terminology/export.xlsx")
    def terminology_export():
        path = export_xlsx(ws.repository, ws.path / "exports" / "relationships.xlsx")
        return FileResponse(path, media_type=XLSX, filename="relationships.xlsx")

    @app.post("/api/terminology/import")
    async def terminology_import(
        file: UploadFile = File(...), by: str = Form("import"), dry_run: bool = Form(False),
        column_map: str | None = Form(None), sheet: str | None = Form(None), header_row: int = Form(1),
        default_scope: str = Form("global"), expected_version: str | None = Form(None), session=Depends(_identified),
    ):
        name = Path(file.filename or "rels.xlsx").name
        tmp = ws.path / "uploads" / f"import-{uuid.uuid4().hex[:8]}{Path(name).suffix.lower()}"
        try:
            await _save_import(file, tmp)
            mapping = json.loads(column_map) if column_map else None
            result = await run_in_threadpool(import_source, ws.repository, tmp, session.reviewer, column_map=mapping,
                                            sheet=sheet, header_row=header_row, default_scope=default_scope, dry_run=dry_run, source_name=name, expected_version=expected_version)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(400, f"Could not read the terminology file ({type(e).__name__}). Supply a readable XLSX or CSV export.")
        finally:
            tmp.unlink(missing_ok=True)
            await file.close()
        return result.to_dict()

    @app.post("/api/terminology/inspect")
    async def terminology_inspect(file: UploadFile = File(...), sheet: str | None = Form(None), header_row: int = Form(1)):
        tmp = ws.path / "uploads" / f"inspect-{uuid.uuid4().hex[:8]}{Path(file.filename or 'rels.xlsx').suffix.lower()}"
        try:
            await _save_import(file, tmp)
            return await run_in_threadpool(inspect_source, tmp, sheet, header_row)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(400, f"Could not read the terminology file ({type(e).__name__}). Supply a readable XLSX or CSV export.")
        finally:
            tmp.unlink(missing_ok=True)
            await file.close()

    @app.post("/api/terminology")
    def create_relationship(payload: RelationshipInput, session=Depends(_identified)):
        payload = payload.model_dump()
        try:
            rel = ws.repository.create(canonical=payload["canonical"], aliases=payload.get("aliases", []), scope=payload.get("scope", "global"), doc_types=payload.get("doc_types", []), item_anchors=payload.get("item_anchors", []), provenance=payload.get("provenance", "manual"), created_by=session.reviewer, notes=payload.get("notes", ""))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return rel.model_dump(mode="json")

    @app.get("/api/terminology/{rel_id}")
    def get_relationship(rel_id: str):
        rel = ws.repository.get(rel_id)
        if rel is None:
            raise HTTPException(404, "relationship not found")
        return _rel(rel, ws.repository.usage_counts())

    @app.put("/api/terminology/{rel_id}")
    def update_relationship(rel_id: str, payload: RelationshipUpdate, session=Depends(_identified)):
        payload = payload.model_dump(exclude_unset=True)
        fields = {k: payload[k] for k in ("canonical", "aliases", "scope", "doc_types", "item_anchors", "notes") if k in payload}
        try:
            return ws.repository.update(rel_id, session.reviewer, payload.get("note", ""), **fields).model_dump(mode="json")
        except KeyError:
            raise HTTPException(404, "relationship not found")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/terminology/{rel_id}/deactivate")
    def deactivate_relationship(rel_id: str, payload: ChangeNote = Body(default=ChangeNote()), session=Depends(_identified)):
        try:
            return ws.repository.deactivate(rel_id, session.reviewer, payload.note).model_dump(mode="json")
        except KeyError:
            raise HTTPException(404, "relationship not found")

    @app.post("/api/terminology/{rel_id}/activate")
    def activate_relationship(rel_id: str, payload: ChangeNote = Body(default=ChangeNote()), session=Depends(_identified)):
        try:
            return ws.repository.activate(rel_id, session.reviewer, payload.note).model_dump(mode="json")
        except KeyError:
            raise HTTPException(404, "relationship not found")

    @app.delete("/api/terminology/{rel_id}")
    def delete_relationship(rel_id: str, by: str = "ui", note: str = "", session=Depends(_identified)):
        try:
            ws.repository.delete(rel_id, session.reviewer, note)
        except KeyError:
            raise HTTPException(404, "relationship not found")
        return {"deleted": rel_id}

    @app.get("/api/terminology/{rel_id}/history")
    def relationship_history(rel_id: str):
        return [{"version": h.version, "change_type": h.change_type, "changed_by": h.changed_by, "changed_at": h.changed_at.isoformat(), "change_note": h.change_note, "payload": h.payload.model_dump(mode="json")} for h in ws.repository.history(rel_id)]

    @app.get("/api/audit")
    def audit(limit: int = Query(200, ge=1, le=1000), session: ReviewSession | None = Depends(_identified)):
        _refuse_if_blind(session)
        return [dict(r) for r in ws.db.conn.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (limit,))]

    if ui_dir and ui_dir.exists():

        @app.middleware("http")
        async def no_cache_index(request, call_next):
            """The bundle's asset names are hashed, but index.html is not: a stale cached index would keep
            pointing at an old bundle after a rebuild. Ask the browser to revalidate it every time."""
            response = await call_next(request)
            if request.url.path in ("/", "/index.html"):
                response.headers["Cache-Control"] = "no-cache"
            return response

        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")
    return app


def _page_count(path: str) -> int:
    if not path.lower().endswith(".pdf"):
        return 0
    try:
        pdf = pymupdf.open(path)
        n = len(pdf)
        pdf.close()
        return n
    except Exception:
        return 0
