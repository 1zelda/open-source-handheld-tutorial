from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import db


@dataclass
class Factory:
    root: Path

    @classmethod
    def discover(cls, root: str | Path | None = None) -> "Factory":
        if root is None:
            root = Path(__file__).resolve().parent.parent
        return cls(Path(root).resolve())

    @property
    def db_path(self) -> Path:
        return self.root / "state" / "factory.db"

    @property
    def jobs_dir(self) -> Path:
        return self.root / "jobs"

    @property
    def recipes_dir(self) -> Path:
        return self.root / "recipes"

    @property
    def devices_dir(self) -> Path:
        return self.root / "devices"

    def init(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.recipes_dir.mkdir(parents=True, exist_ok=True)
        self.devices_dir.mkdir(parents=True, exist_ok=True)
        db.init_db(self.db_path)

    @contextmanager
    def connect(self):
        conn = db.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id
