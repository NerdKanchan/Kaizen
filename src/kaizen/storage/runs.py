"""Index of runs in the workspace database (the full run stays in run.json)."""

import json
from datetime import datetime, timezone
from pathlib import Path

from kaizen.models import Classification, Run
from kaizen.storage.db import Database


class RunIndex:
    def __init__(self, db: Database):
        self.conn = db.conn

    def register(self, run: Run, json_path: Path | str) -> None:
        counts = {c.value: sum(1 for r in run.results if r.classification is c) for c in Classification}
        summary = {"rows": len(run.results), "skus": len(run.groups), "documents": len(run.documents), "needs_validation": sum(1 for r in run.results if r.requires_validation), **counts}
        self.conn.execute(
            "INSERT INTO runs (run_id,created_at,input_root,tool_version,terminology_version,json_path,summary) VALUES (?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET json_path=excluded.json_path, summary=excluded.summary",
            (run.metadata.run_id, run.metadata.timestamp.isoformat(), run.metadata.input_root, run.metadata.tool_version, run.metadata.terminology_version, str(Path(json_path).resolve()), json.dumps(summary)),
        )
        self.conn.execute("INSERT INTO audit (at, actor, action, detail) VALUES (?,?,?,?)", (datetime.now(timezone.utc).isoformat(), "system", "run.registered", f"{run.metadata.run_id} → {json_path}"))
        self.conn.commit()

    def list(self) -> list[dict]:
        return [dict(r) | {"summary": json.loads(r["summary"])} for r in self.conn.execute("SELECT * FROM runs ORDER BY created_at DESC")]

    def get(self, run_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(r) | {"summary": json.loads(r["summary"])} if r else None
