from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    kind TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    family TEXT NOT NULL,
    os TEXT,
    arch TEXT,
    capabilities TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    game_id TEXT REFERENCES games(id),
    device_id TEXT NOT NULL REFERENCES devices(id),
    recipe_id TEXT NOT NULL,
    input_path TEXT NOT NULL,
    status TEXT NOT NULL,
    workdir TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stages (
    job_id TEXT NOT NULL REFERENCES jobs(id),
    stage_id TEXT NOT NULL,
    order_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    detail TEXT,
    PRIMARY KEY (job_id, stage_id)
);
CREATE TABLE IF NOT EXISTS gate_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    stage_id TEXT NOT NULL,
    gate_id TEXT NOT NULL,
    status TEXT NOT NULL,
    required INTEGER NOT NULL,
    detail TEXT,
    evidence_path TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    evidence_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_gates_job ON gate_results(job_id, stage_id);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);
CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,
    game_id TEXT REFERENCES games(id),
    target TEXT NOT NULL,
    source_path TEXT NOT NULL,
    snapshot_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    workdir TEXT NOT NULL,
    status TEXT NOT NULL,
    analysis_sha256 TEXT,
    max_requests INTEGER NOT NULL,
    max_context_bytes INTEGER NOT NULL,
    max_active_seconds REAL NOT NULL,
    max_attempts INTEGER NOT NULL,
    max_modules INTEGER NOT NULL,
    active_seconds REAL NOT NULL DEFAULT 0,
    active_lease_seconds REAL NOT NULL DEFAULT 0,
    detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_modules (
    run_id TEXT NOT NULL REFERENCES research_runs(id),
    id TEXT NOT NULL,
    address INTEGER NOT NULL,
    module_path TEXT NOT NULL,
    module_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    accepted_ir_sha256 TEXT,
    detail TEXT,
    PRIMARY KEY(run_id,id)
);
CREATE TABLE IF NOT EXISTS research_attempts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(id),
    module_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    request_path TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    response_path TEXT,
    context_charge INTEGER NOT NULL,
    response_limit INTEGER NOT NULL,
    ir_sha256 TEXT,
    detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id,module_id,attempt_no),
    FOREIGN KEY(run_id,module_id) REFERENCES research_modules(run_id,id)
);
CREATE INDEX IF NOT EXISTS idx_research_attempts ON research_attempts(run_id,status);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex[:12]
    return f"{prefix}{raw}" if prefix else raw


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(research_runs)")}
        if "active_lease_seconds" not in columns:
            conn.execute("ALTER TABLE research_runs ADD COLUMN active_lease_seconds REAL NOT NULL DEFAULT 0")
        conn.commit()
    finally:
        conn.close()


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def load_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


def event(conn: sqlite3.Connection, job_id: str | None, kind: str, message: str,
          evidence_path: str | None = None) -> None:
    conn.execute(
        "INSERT INTO events(job_id, ts, kind, message, evidence_path) VALUES (?,?,?,?,?)",
        (job_id, now(), kind, message, evidence_path),
    )


def add_artifact(conn: sqlite3.Connection, job_id: str, path: Path, kind: str,
                 size: int, sha256: str) -> None:
    conn.execute(
        "INSERT INTO artifacts(job_id, path, kind, size, sha256, created_at) VALUES (?,?,?,?,?,?)",
        (job_id, str(path), kind, size, sha256, now()),
    )


def get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def get_device(conn: sqlite3.Connection, device_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["capabilities"] = load_json(item["capabilities"], [])
    return item


def get_game(conn: sqlite3.Connection, game_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["fingerprint"] = load_json(item["fingerprint"], {})
    return item


def list_jobs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT j.*, g.name AS game_name, d.name AS device_name "
        "FROM jobs j LEFT JOIN games g ON g.id = j.game_id "
        "LEFT JOIN devices d ON d.id = j.device_id ORDER BY j.created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def job_stages(conn: sqlite3.Connection, job_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM stages WHERE job_id = ? ORDER BY order_no", (job_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def job_gates(conn: sqlite3.Connection, job_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM gate_results WHERE job_id = ? ORDER BY id", (job_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def job_artifacts(conn: sqlite3.Connection, job_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM artifacts WHERE job_id = ? ORDER BY id", (job_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def job_events(conn: sqlite3.Connection, job_id: str, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM events WHERE job_id = ? ORDER BY id DESC LIMIT ?", (job_id, limit)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]
