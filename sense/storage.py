from __future__ import annotations

import json
import math
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
            CREATE INDEX IF NOT EXISTS events_run_type ON events(run_id, type, sequence);
            CREATE TABLE IF NOT EXISTS human_records (record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS human_records_run ON human_records(run_id);
            CREATE TABLE IF NOT EXISTS samples_1s (run_id TEXT NOT NULL, second INTEGER NOT NULL,
                timestamp TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id, second));
            CREATE TABLE IF NOT EXISTS observer_requests (request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                requested_at TEXT NOT NULL, reason TEXT NOT NULL, task_id TEXT, event_id TEXT,
                fields TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', record_id TEXT);
            CREATE INDEX IF NOT EXISTS observer_requests_run ON observer_requests(run_id, status);
        """)
        # Un reinicio no transforma una ejecución incompleta en un resultado exitoso.
        interrupted = self.db.execute("SELECT run_id FROM runs WHERE status='RUNNING'").fetchall()
        for (run_id,) in interrupted:
            self.event(run_id, "RUN_INTERRUPTED", {"reason": "PROCESS_RESTART"})
            from .context import timestamp
            metadata = self.run(run_id)
            duration = metadata.get("duration_seconds", metadata.get("config", {}).get("runtime", {}).get("max_run_seconds", 1800))
            elapsed = min(duration, max(0, timestamp(utc_now()) - timestamp(metadata["start_time"])))
            expected = min(math.ceil(duration), max(1, math.ceil(elapsed)))
            last = self.db.execute("SELECT max(second) FROM samples_1s WHERE run_id=?", (run_id,)).fetchone()[0]
            if last is not None and last + 1 < expected:
                self.event(run_id, "SAMPLE_GAP", {"from_second": last + 1, "to_second": expected - 1, "reason": "PROCESS_RESTART"})
            metadata.update(elapsed_s=elapsed, expected_samples=expected, finish_reason="PROCESS_RESTART",
                            interruption_detected_at=utc_now(), end_time_uncertain=True)
            if metadata.get("guided"):
                self.request_observer(run_id, "RUN_FINAL", ["power_w", "visible_people", "action"])
            self.finish(run_id, "INTERRUPTED", metadata)
        self.db.commit()

    def begin(self, metadata: dict) -> None:
        with self.transaction():
            self.db.execute("INSERT INTO runs VALUES (?, ?, NULL, 'RUNNING', ?)",
                            (metadata["run_id"], metadata["start_time"], json.dumps(metadata, allow_nan=False)))

    def finish(self, run_id: str, status: str, metadata: dict | None = None) -> None:
        with self.transaction():
            self.db.execute("UPDATE runs SET ended_at=?, status=? WHERE run_id=?", (utc_now(), status, run_id))
            if metadata is not None:
                self.db.execute("UPDATE runs SET metadata=? WHERE run_id=?", (json.dumps(metadata, allow_nan=False), run_id))

    def event(self, run_id: str, kind: str, payload: dict) -> None:
        with self.transaction():
            self.db.execute("INSERT INTO events(run_id, timestamp, type, payload) VALUES (?, ?, ?, ?)",
                            (run_id, utc_now(), kind, json.dumps(payload, allow_nan=False)))

    def runs(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT run_id, started_at, ended_at, status, metadata FROM runs ORDER BY started_at DESC LIMIT 100").fetchall()
        return [dict({k: v for k, v in json.loads(row[4]).items() if k in ("mode", "scenario_id", "repetition", "guided")},
                     run_id=row[0], start_time=row[1], end_time=row[2], status=row[3], quality=self.quality(row[0])) for row in rows]

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

    def sample(self, run_id: str, second: int, payload: dict) -> None:
        with self.transaction():
            self.db.execute("INSERT INTO samples_1s VALUES (?, ?, ?, ?)",
                            (run_id, second, payload["timestamp_utc"], json.dumps(payload, allow_nan=False)))

    def request_observer(self, run_id: str, reason: str, fields: list[str], task_id=None, event_id=None, requested_at=None) -> str:
        request_id, requested_at = identifier(), requested_at or utc_now()
        with self.transaction():
            self.db.execute("INSERT INTO observer_requests VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', NULL)",
                            (request_id, run_id, requested_at, reason, task_id, event_id, json.dumps(fields)))
            self.event(run_id, "OBSERVER_REQUESTED", dict(request_id=request_id, reason=reason,
                       task_id=task_id, event_id=event_id, fields=fields, requested_at=requested_at))
        return request_id

    def observer_requests(self, run_id: str, pending_only: bool = False) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT request_id, requested_at, reason, task_id, event_id, fields, status, record_id "
                                   "FROM observer_requests WHERE run_id=? " +
                                   ("AND status='PENDING' " if pending_only else "") + "ORDER BY rowid", (run_id,)).fetchall()
        return [dict(request_id=r[0], run_id=run_id, requested_at=r[1], reason=r[2], task_id=r[3],
                     event_id=r[4], fields=json.loads(r[5]), status=r[6], record_id=r[7]) for r in rows]

    def resolve_observer(self, run_id: str, request_id: str, payload: dict) -> str:
        from .protocol import validate_observation

        with self.transaction():
            request = next((r for r in self.observer_requests(run_id) if r["request_id"] == request_id), None)
            if request is None or request["status"] != "PENDING":
                raise ValueError("Solicitud inexistente o ya resuelta. Actualiza los pendientes.")
            validate_observation(payload, request["fields"])
            run = self.run(run_id)
            record = dict(payload, request_id=request_id, task_id=request["task_id"], event_id=request["event_id"],
                          requested_at=request["requested_at"], event_at=request["requested_at"], reason=request["reason"], scope="connected_equipment",
                          **{k: payload.get(k, run.get(k)) for k in ("observer", "instrument", "equipment")})
            record_id = self.human_record(run_id, "OBSERVER_RECORD", record)
            self.db.execute("UPDATE observer_requests SET status='RESOLVED', record_id=? WHERE request_id=?",
                            (record_id, request_id))
            self.event(run_id, "OBSERVER_RECORDED", {"request_id": request_id, "record_id": record_id})
            return record_id

    def observer_previous(self, run_id: str) -> dict:
        previous = {}
        with self.lock:
            for field in ("power_w", "visible_people"):
                row = self.db.execute(
                    "SELECT h.payload FROM human_records h WHERE h.run_id=? AND h.kind='OBSERVER_RECORD' "
                    f"AND json_type(h.payload, '$.{field}') IN ('integer', 'real') "
                    "AND EXISTS (SELECT 1 FROM observer_requests r, json_each(r.fields) f "
                    "WHERE r.record_id=h.record_id AND r.run_id=h.run_id AND f.value=?) ORDER BY h.rowid DESC LIMIT 1",
                    (run_id, field)).fetchone()
                if row:
                    previous[field] = json.loads(row[0])[field]
        return previous

    def quality(self, run_id: str) -> dict:
        with self.lock:
            samples = self.db.execute("SELECT count(*), max(second) FROM samples_1s WHERE run_id=?", (run_id,)).fetchone()
            pending = self.db.execute("SELECT count(*) FROM observer_requests WHERE run_id=? AND status='PENDING'", (run_id,)).fetchone()[0]
            missing = self.db.execute("SELECT count(*) FROM human_records WHERE run_id=? AND kind='OBSERVER_RECORD' "
                                      "AND json_array_length(payload, '$.unavailable_fields')>0", (run_id,)).fetchone()[0]
            failures = dict(self.db.execute("SELECT type, count(*) FROM events WHERE run_id=? AND type IN ('TASK_FAILED','TASK_TIMEOUT') GROUP BY type", (run_id,)).fetchall())
            incomplete = self.db.execute("SELECT count(*) FROM samples_1s WHERE run_id=? AND json_extract(payload, '$.sensor_data_status')!='VALID'", (run_id,)).fetchone()[0]
        run = self.run(run_id) or {}
        expected = run.get("expected_samples", (samples[1] + 1) if samples[1] is not None else 0)
        return dict(samples=samples[0], expected_samples=expected, missing_samples=max(0, expected - samples[0]),
                    pending_observations=pending, unavailable_observations=missing,
                    task_failures=failures.get("TASK_FAILED", 0), task_timeouts=failures.get("TASK_TIMEOUT", 0), sensor_incomplete_samples=incomplete,
                    duration_completed=run.get("finish_reason") == "MAX_RUN_DURATION",
                    record_complete=bool(samples[0]) and run.get("status") != "INTERRUPTED" and not pending and not missing and samples[0] == expected)

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
        for item in self.observer_requests(run_id):
            yield json.dumps({"type": "OBSERVER_REQUEST", "payload": item}, ensure_ascii=False) + "\n"
        second = -1
        while True:
            with self.lock:
                rows = self.db.execute("SELECT second, payload FROM samples_1s WHERE run_id=? AND second>? ORDER BY second LIMIT 200", (run_id, second)).fetchall()
            if not rows:
                break
            for row in rows:
                yield json.dumps({"type": "SAMPLE_1S", "payload": json.loads(row[1])}, ensure_ascii=False) + "\n"
            second = rows[-1][0]
