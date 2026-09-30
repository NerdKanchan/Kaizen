"""Self-contained run snapshots. Source files are copied, never shared by writable path."""
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from kaizen.models import Run
from kaizen.pipeline import save_run


def snapshot(run: Run, folder: Path, run_id: str) -> Run:
    data = run.model_dump(mode='json')
    paths = {str(i.path) for i in run.metadata.inputs}
    paths.update(d.path for d in run.documents)
    mapping = {}
    destinations = {}
    for index, source in enumerate(sorted(paths)):
        src = Path(source)
        if not src.is_absolute():
            src = Path(run.metadata.input_root) / src
        src = src.resolve()
        if not src.is_file():
            raise ValueError(f'Source document is unavailable: {src.name}')
        dest = destinations.get(src)
        if dest is None:
            dest = folder / 'files' / f'{index:04d}' / src.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            destinations[src] = dest
        mapping[source] = str(dest.resolve())

    def rewrite(value):
        if isinstance(value, dict):
            return {k: rewrite(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rewrite(v) for v in value]
        return mapping.get(value, value) if isinstance(value, str) else value

    data = rewrite(data)
    data['metadata']['run_id'] = run_id
    data['metadata']['input_root'] = str((folder / 'files').resolve())
    data['metadata']['timestamp'] = datetime.now(timezone.utc).isoformat()
    return Run.model_validate(data)


def copy_run(ws, run: Run, actor: str) -> Run:
    rid = uuid.uuid4().hex
    folder = ws.runs_dir / rid
    try:
        copied = snapshot(run, folder, rid)
        path = save_run(copied, folder / 'run.json')
        with ws.db.lock:
            source = ws.runs.get(run.metadata.run_id)
            ws.register_run(copied, path)
            ws.db.conn.execute('UPDATE runs SET name=?, owner=?, copied_from=? WHERE run_id=?', (f"{source['name'] or 'Review'} — Copy", actor, run.metadata.run_id, rid))
            # Keep the working decisions, but copies always require their own approval.
            rows = ws.db.conn.execute('SELECT * FROM decisions WHERE run_id=?', (run.metadata.run_id,)).fetchall()
            for row in rows:
                fields = dict(row)
                fields['run_id'] = rid
                names = ','.join(fields)
                ws.db.conn.execute(f'INSERT INTO decisions ({names}) VALUES ({",".join("?" for _ in fields)})', tuple(fields.values()))
            for row in ws.db.conn.execute('SELECT * FROM action_items WHERE run_id=?', (run.metadata.run_id,)):
                fields = dict(row)
                fields.update(id='AI-' + uuid.uuid4().hex[:16], run_id=rid, resolved_in_run='', resolved_at='')
                names = ','.join(fields)
                ws.db.conn.execute(f'INSERT INTO action_items ({names}) VALUES ({",".join("?" for _ in fields)})', tuple(fields.values()))
            ws.db.audit(actor, 'run.copied', f'{rid} copied from {run.metadata.run_id}; approvals reset')
            ws.db.conn.commit()
        return copied
    except Exception:
        # Files in this new, random directory belong solely to the failed copy.
        shutil.rmtree(folder, ignore_errors=True)
        raise


def portable_payload(run: Run, folder: Path) -> dict:
    data = run.model_dump(mode='json')
    prefix = str(folder.resolve()) + '/'
    def rewrite(value):
        if isinstance(value, dict):
            return {k: rewrite(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rewrite(v) for v in value]
        return value[len(prefix):] if isinstance(value, str) and value.startswith(prefix) else value
    return rewrite(data)
