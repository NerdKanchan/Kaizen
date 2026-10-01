"""A workspace is a folder with the SQLite database (terminology, runs, decisions, action items) and saved runs."""

import os
from pathlib import Path

from kaizen.models import Run
from kaizen.storage.db import Database
from kaizen.storage.runs import RunIndex
from kaizen.terminology.repository import TerminologyRepository

DEFAULT_WORKSPACE = "kaizen-workspace"


class Workspace:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.path / "kaizen.db")
        self.repository = TerminologyRepository(self.db)
        self.repository.initialize()
        self.runs = RunIndex(self.db)
        self.runs_dir = self.path / "runs"

    @classmethod
    def resolve(cls, explicit: Path | str | None) -> "Workspace":
        return cls(explicit or os.environ.get("KAIZEN_WORKSPACE") or DEFAULT_WORKSPACE)

    def register_run(self, run: Run, json_path: Path | str, record_usage: bool = True) -> None:
        with self.db.transaction():
            self.runs.register(run, json_path)
            if record_usage:
                self.repository.record_run_usage(run.metadata.run_id, run.relationship_usage, snapshot=run.terminology_snapshot)
