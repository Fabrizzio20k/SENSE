"""SQLite es el registro primario; SSE y CSV son proyecciones del mismo corte."""

import csv
import io
import json
import sqlite3
import time
import zipfile
from datetime import datetime, timezone
from uuid import uuid4

from context import encoded


def utc_now():
    return datetime.now(timezone.utc).isoformat()


TABLES = {
    "runs": ["status", "started_at", "ended_at", "source_mode", "profile_json", "block_id", "space_id", "scenario_id", "phase", "protocol_deviation",
             "measurement_status", "power_pending_count", "power_omitted_count"],
    "observations": ["observation_id", "source_id", "metric", "value", "unit", "source_timestamp",
                     "received_at", "received_elapsed_s", "accepted", "reason", "quality_flags"],
    "decisions": ["episode_id", "snapshot_id", "from_state", "to_state", "reason"],
    "answers": ["episode_id", "snapshot_id", "evidence_hash", "question", "status", "content_json", "followup_status",
                "followup_of_episode_id"],
    "faults": ["fault_id", "source_id", "mode", "status", "start_elapsed_s", "end_elapsed_s", "reason"],
    "power_readings": ["reading_id", "quantity", "value", "unit", "normalized_value", "normalized_unit", "observed_elapsed_s",
                       "recorded_elapsed_s", "time_basis", "time_uncertainty_s", "instrument_id", "observer_id",
                       "note", "supersedes_reading_id", "task_id"],
    "annotations": ["annotation_id", "label", "presence", "count", "observed_elapsed_s", "observer_id"],
    "resource_samples": ["sample_id", "interval_s", "system_cpu_percent", "per_cpu_percent", "ram_used_bytes",
                         "ram_available_bytes", "swap_used_bytes", "cpu_temperature_c", "cpu_frequency_mhz", "scope"],
    "process_samples": ["sample_id", "role", "pid", "process_instance_id", "process_cpu_percent", "rss_bytes"],
    "metrics": ["name", "value", "unit", "method", "details_json"],
    "actions": ["action_id", "episode_id", "tool", "status", "snapshot_id", "queue_duration_s", "duration_s", "reason", "result"],
    "evaluations": ["evaluation_id", "episode_id", "evaluator_id", "rubric_version", "correct", "supported", "score", "note"],
}


def safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return encoded(value)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'"+value
    return value


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE, request_hash TEXT NOT NULL,
            status TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT, manifest_json TEXT NOT NULL);
          CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs ((1)) WHERE status='running';
          CREATE TABLE IF NOT EXISTS events (
            run_id TEXT NOT NULL REFERENCES runs(run_id), sequence INTEGER NOT NULL,
            type TEXT NOT NULL, event_json TEXT NOT NULL, PRIMARY KEY(run_id,sequence));
          CREATE INDEX IF NOT EXISTS events_by_type ON events(run_id,type,sequence);
          CREATE TABLE IF NOT EXISTS runtime_flags (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY, path TEXT NOT NULL, metadata_json TEXT NOT NULL);
        """)
        for row in self.db.execute("SELECT run_id FROM runs WHERE status='running'").fetchall():
            last = self.events(row["run_id"], self.last_sequence(row["run_id"])-1)
            self.finish(row["run_id"], "interrupted", {"reason": "backend_restarted", "elapsed_basis": "last_persisted_event"},
                        last[-1]["elapsed_s"] if last else 0, "recovery")

    def run(self, run_id):
        row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return {**dict(row), "manifest": json.loads(row["manifest_json"])}

    def runs(self):
        return [self.run(r[0]) for r in self.db.execute("SELECT run_id FROM runs ORDER BY rowid DESC LIMIT 20")]

    def by_key(self, key):
        row = self.db.execute("SELECT run_id FROM runs WHERE idempotency_key=?", (key,)).fetchone()
        return self.run(row[0]) if row else None

    def last_sequence(self, run_id):
        return self.db.execute("SELECT COALESCE(MAX(sequence),0) FROM events WHERE run_id=?", (run_id,)).fetchone()[0]

    def _append(self, run_id, event_type, payload, elapsed, boot_id, episode_id=None):
        sequence = self.last_sequence(run_id)+1
        event = {"schema_version": 1, "run_id": run_id, "sequence": sequence,
                 "event_id": f"{run_id}:{sequence}", "type": event_type, "occurred_at": utc_now(),
                 "monotonic_ns": time.monotonic_ns(),
                 "elapsed_s": elapsed, "boot_id": boot_id, "episode_id": episode_id, "payload": payload}
        self.db.execute("INSERT INTO events VALUES (?,?,?,?)", (run_id, sequence, event_type, encoded(event)))
        return event

    def append(self, *args, **kwargs):
        with self.db:
            return self._append(*args, **kwargs)

    def create(self, run_id, key, request_hash, manifest, boot_id):
        with self.db:
            self.db.execute("INSERT INTO runs VALUES (?,?,?,'running',?,NULL,?)",
                            (run_id, key, request_hash, utc_now(), encoded(manifest)))
            self._append(run_id, "run.accepted", {"manifest": manifest}, 0, boot_id)

    def finish(self, run_id, status, payload, elapsed, boot_id):
        with self.db:
            self.db.execute("UPDATE runs SET status=?,ended_at=? WHERE run_id=?", (status, utc_now(), run_id))
            self._append(run_id, f"run.{status}", payload, elapsed, boot_id)

    def events(self, run_id, after=0, limit=100):
        return [json.loads(r[0]) for r in self.db.execute(
            "SELECT event_json FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
            (run_id, after, limit))]

    def measurement(self, run_id, elapsed=None, events=None):
        from experiment import measurement_state
        run = self.run(run_id)
        if events is None:
            events = [json.loads(row[0]) for row in self.db.execute(
                "SELECT event_json FROM events WHERE run_id=? AND type IN ('power.reading_recorded','power.task_omitted','measurement.closed',?) ORDER BY sequence",
                (run_id, "run."+run["status"]))]
        if elapsed is None:
            last = self.events(run_id, after=max(0, self.last_sequence(run_id)-1))
            elapsed = last[-1]["elapsed_s"] if last else 0
        return measurement_state(run, events, elapsed)

    def export(self, run_id):
        run = self.run(run_id)
        cutoff = self.last_sequence(run_id)
        if cutoff > 100000:
            raise ValueError("exportación excede límite de 100000 eventos del prototipo")
        events = self.events(run_id, limit=cutoff+1)
        measurement = self.measurement(run_id, elapsed=events[-1]["elapsed_s"] if events else 0, events=events)
        manifest = {**run["manifest"], "run_id": run_id, "status": run["status"],
                    "started_at": run["started_at"], "ended_at": run["ended_at"],
                    "export_id": str(uuid4()), "exported_at": utc_now(), "cutoff_sequence": cutoff,
                    "partial": run["status"] == "running" or measurement["status"] == "pending_review",
                    "measurement": measurement, "csv_text_profile": "spreadsheet_safe",
                    "csv_transformation": "prefix apostrophe on formula-like untrusted text; JSONL unchanged"}
        rows = {name: [] for name in TABLES}
        rows["runs"].append({"status": run["status"], "started_at": run["started_at"], "ended_at": run["ended_at"],
                             "source_mode": manifest["source_mode"], "profile_json": manifest["profile"],
                             "measurement_status": measurement["status"], "power_pending_count": measurement["pending_count"],
                             "power_omitted_count": measurement["omitted_count"],
                             **{k: manifest.get("request", {}).get(k) for k in ("block_id", "space_id", "scenario_id", "phase")},
                             "protocol_deviation": any(e["type"] == "protocol.deviation" for e in events)})
        mapping = {"state.changed": "decisions", "answer.validated": "answers", "power.reading_recorded": "power_readings",
                   "annotation.recorded": "annotations", "resource.sample": "resource_samples", "metrics.updated": "metrics",
                   "evaluation.recorded": "evaluations"}
        for event in events:
            payload = event["payload"]
            base = {"sequence": event["sequence"], "occurred_at": event["occurred_at"], "elapsed_s": event["elapsed_s"]}
            kind = event["type"]
            if kind.startswith("observation."):
                for observation in payload.get("observations", [{}]):
                    rows["observations"].append({**base, **payload, **observation, "accepted": kind == "observation.accepted"})
            elif kind.startswith("fault."):
                rows["faults"].append({**base, **payload})
            elif kind.startswith("action.") and kind != "action.deferred":
                rows["actions"].append({**base, "episode_id": event["episode_id"], **payload})
            elif kind == "resource.sample":
                rows["resource_samples"].append({**base, **payload})
                for process in payload.get("processes", []):
                    rows["process_samples"].append({**base, "sample_id": payload["sample_id"], **process})
            elif kind in mapping:
                rows[mapping[kind]].append({**base, "episode_id": event["episode_id"], **payload})
        summary = self.summary(run_id, events)
        for name, value in summary["metrics"].items():
            rows["metrics"].append({"name": name, "value": value, "method": "descriptive_run_summary_v1",
                                    "details_json": {"cutoff_sequence": cutoff, "scope": summary["scope"]}})
        files = {}
        common = ["schema_version", "run_id", "variant", "export_id", "cutoff_sequence", "sequence", "occurred_at", "elapsed_s"]
        for name, columns in TABLES.items():
            if name == "actions":
                merged = {}
                for row in rows[name]:
                    key = row.get("action_id")
                    if key:
                        merged[key] = {**merged.get(key, {}), **row}
                rows[name] = list(merged.values())
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=common+columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows[name]:
                row = {**row, "schema_version": 1, "run_id": run_id, "variant": manifest.get("request", {}).get("variant", "rules-v1"),
                       "export_id": manifest["export_id"], "cutoff_sequence": cutoff}
                writer.writerow({key: safe_cell(value) for key, value in row.items()})
            files[f"{name}.csv"] = output.getvalue().encode("utf-8")
        files["manifest.json"] = (encoded(manifest)+"\n").encode()
        files["events.jsonl"] = ("".join(encoded(e)+"\n" for e in events)).encode()
        files["schema.json"] = (encoded({"version": 1, "time": "UTC ISO8601; elapsed_s is live monotonic or replay logical",
                                        "missing": "empty CSV cell, null JSON", "tables": TABLES,
                                        "empty_tables": "unsupported or unused; never synthetic rows"})+"\n").encode()
        return files

    def zip_export(self, run_id):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in self.export(run_id).items():
                archive.writestr(name, data)
        return output.getvalue()

    def close(self):
        self.db.close()

    def flag(self, key, value=None, write=False):
        if write:
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO runtime_flags VALUES (?,?)", (key, encoded(value)))
        row = self.db.execute("SELECT value_json FROM runtime_flags WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def artifact(self, artifact_id, path=None, metadata=None):
        if path is not None:
            with self.db:
                self.db.execute("INSERT INTO artifacts VALUES (?,?,?)", (artifact_id, str(path), encoded(metadata)))
        row = self.db.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return {"artifact_id": artifact_id, "path": row["path"], "metadata": json.loads(row["metadata_json"])}

    def snapshot(self, run_id, snapshot_id):
        for row in self.db.execute("SELECT event_json FROM events WHERE run_id=? AND type='snapshot.created' ORDER BY sequence", (run_id,)):
            snapshot = json.loads(row[0])["payload"]
            if snapshot["snapshot_id"] == snapshot_id:
                return snapshot
        raise KeyError(snapshot_id)

    def summary(self, run_id, events=None):
        run = self.run(run_id)
        if events is None:
            if self.last_sequence(run_id) > 100000:
                raise ValueError("resumen excede límite de 100000 eventos")
            events = self.events(run_id, limit=100001)
        from experiment import energy_estimate
        resources = [e["payload"] for e in events if e["type"] == "resource.sample"]
        starts = [e["payload"] for e in events if e["type"] == "action.started"]
        duration = max((e["elapsed_s"] for e in events), default=0)
        readings = [e["payload"] for e in events if e["type"] == "power.reading_recorded"]
        cpu = [r["system_cpu_percent"] for r in resources if r.get("system_cpu_percent") is not None]
        memory = [r["ram_used_bytes"] for r in resources if r.get("ram_used_bytes") is not None]
        values = {"accepted_source_blocks": sum(e["type"] == "observation.accepted" for e in events),
                  "rejected_messages": sum(e["type"] == "message.rejected" for e in events),
                  "visual_action_attempts": sum(a["tool"] in ("count_people", "capture_image") for a in starts),
                  "slm_action_attempts": sum(a["tool"] in ("interpret_context", "describe_image") for a in starts),
                  "resource_sample_count": len(resources), "sampled_cpu_max_percent": max(cpu) if cpu else None,
                  "sampled_system_ram_max_bytes": max(memory) if memory else None,
                  "completed_detector_inferences": sum(e["payload"].get("result", {}).get("tile_count", 0) for e in events
                                                        if e["type"] in ("action.completed", "action.suppressed")),
                  "answer_count": sum(e["type"] == "answer.validated" for e in events),
                  "human_evaluation_count": sum(e["type"] == "evaluation.recorded" for e in events),
                  "protocol_deviation_count": sum(e["type"] == "protocol.deviation" for e in events)}
        energy = energy_estimate(readings, duration)
        return {"run_id": run_id, "cutoff_sequence": events[-1]["sequence"] if events else 0,
                "scope": run["manifest"]["source_mode"], "elapsed_s": duration, "metrics": values, "energy": energy,
                "limitations": ["no_accuracy_without_ground_truth", "no_peak_power_from_sparse_W", "sampled_resource_maxima_only",
                                "failed_partial_inferences_not_counted_as_completed"]}
