from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .contracts import identifier, utc_now


class ExperimentLog:
    @contextmanager
    def transaction(self):
        with self.lock:
            nested = self.db.in_transaction
            if not nested:
                self.db.execute("BEGIN")
            try:
                yield
                if not nested:
                    self.db.commit()
            except Exception:
                if not nested:
                    self.db.rollback()
                raise

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
                ended_at TEXT, status TEXT NOT NULL, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY, run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_run ON events(run_id, sequence);
            CREATE TABLE IF NOT EXISTS human_records (record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
        """)
        # Un reinicio no transforma una ejecución incompleta en un resultado exitoso.
        interrupted = self.db.execute("SELECT run_id FROM runs WHERE status='RUNNING'").fetchall()
        for (run_id,) in interrupted:
            self.event(run_id, "RUN_INTERRUPTED", {"reason": "PROCESS_RESTART"})
            self.finish(run_id, "INTERRUPTED")
        self.db.commit()

    def begin(self, metadata: dict) -> None:
        with self.transaction():
            self.db.execute("INSERT INTO runs VALUES (?, ?, NULL, 'RUNNING', ?)",
                            (metadata["run_id"], metadata["start_time"], json.dumps(metadata, allow_nan=False)))

    def finish(self, run_id: str, status: str) -> None:
        with self.transaction():
            self.db.execute("UPDATE runs SET ended_at=?, status=? WHERE run_id=?", (utc_now(), status, run_id))

    def event(self, run_id: str, kind: str, payload: dict) -> None:
        with self.transaction():
            self.db.execute("INSERT INTO events(run_id, timestamp, type, payload) VALUES (?, ?, ?, ?)",
                            (run_id, utc_now(), kind, json.dumps(payload, allow_nan=False)))

    def runs(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT run_id, started_at, ended_at, status, metadata FROM runs ORDER BY started_at DESC LIMIT 100").fetchall()
        return [{"run_id": row[0], "start_time": row[1], "end_time": row[2], "status": row[3],
                 "mode": json.loads(row[4])["mode"]} for row in rows]

    def run(self, run_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT metadata, ended_at, status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(json.loads(row[0]), end_time=row[1], status=row[2]) if row else None

    def events(self, run_id: str, after: int = 0, limit: int = 200) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT sequence, timestamp, type, payload FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                                   (run_id, after, min(limit, 200))).fetchall()
        return [{"sequence": row[0], "timestamp": row[1], "type": row[2], "payload": json.loads(row[3])} for row in rows]

    def human_record(self, run_id: str, kind: str, payload: dict) -> str:
        record_id = identifier()
        with self.transaction():
            self.db.execute("INSERT INTO human_records VALUES (?, ?, ?, ?, ?)",
                            (record_id, run_id, utc_now(), kind, json.dumps(payload, allow_nan=False)))
        return record_id

    def export(self, run_id: str):
        yield json.dumps({"type": "RUN", "payload": self.run(run_id)}, ensure_ascii=False) + "\n"
        sequence = 0
        while batch := self.events(run_id, sequence):
            for event in batch:
                yield json.dumps(event, ensure_ascii=False) + "\n"
            sequence = batch[-1]["sequence"]
        cursor = 0
        while True:
            with self.lock:
                rows = self.db.execute("SELECT rowid, record_id, timestamp, kind, payload FROM human_records WHERE run_id=? AND rowid>? ORDER BY rowid LIMIT 200", (run_id, cursor)).fetchall()
            if not rows:
                break
            for row in rows:
                yield json.dumps({"type": row[3], "record_id": row[1], "timestamp": row[2], "payload": json.loads(row[4])}, ensure_ascii=False) + "\n"
            cursor = rows[-1][0]
