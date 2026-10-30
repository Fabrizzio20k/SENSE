"""Muestras compactas y exportación de las fuentes existentes, sin otro logger."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import tempfile
import zipfile
from contextlib import closing


def sample_document(controller, now: float) -> dict:
    context = controller.context.snapshot(now).document()
    resources = controller.resources
    tasks = controller.tasks.view(now)
    result = dict(timestamp_utc=context["created_at"], elapsed_s=round(now - controller.started, 3),
                  fsm_state=controller.fsm, conflict_status=context["conflict"],
                  active_question=[t["question_id"] for t in tasks["active"]],
                  information_need=[n["need_id"] for n in controller.policy.needs.values() if n["status"] == "PENDING"],
                  environment_event_active=any(c["state"] in ("ACTIVE", "RECOVERING") for c in context["environment_conditions"].values()),
                  cpu_percent=resources.get("cpu_total_percent"), ram_used_mb=resources.get("ram_used_mb"),
                  ram_available_mb=resources.get("available_mb"), swap_mb=resources.get("swap_used_mb"),
                  pi_temp_c=resources.get("temperature_c"), throttled=resources.get("throttled"),
                  resource_timestamp_utc=resources.get("sampled_at"), gemma_processes=resources.get("gemma_processes", []),
                  resource_age_s=round(max(0, now - resources["sampled_monotonic"]), 3) if resources.get("sampled_monotonic") is not None else None,
                  queued_tasks=tasks["queued"], sample_status="OBSERVED")
    result.update(component_health=controller.health.components, fault_ids=[f["fault_id"] for f in controller.faults.records.values() if not f["restored_at"]],
                  presence_source="MANUAL_CONTROL" if controller.manual_presence is not None else "RADAR", manual_near=controller.manual_near)
    raw = controller.last_raw_presence
    result.update(radar_raw_presence=raw.value if raw else None, radar_raw_observation_id=raw.observation_id if raw else None,
                  radar_raw_observed_at=raw.captured_at if raw else None,
                  radar_raw_age_s=round(max(0, now - controller.raw_presence_received + controller.raw_presence_age), 3) if raw else None,
                  radar_raw_distance_cm=dict(raw.metadata).get("trigger_distance_cm") if raw else None)
    for field, value in resources.get("main", {}).items():
        result["process_" + field] = value
    for lane, agent in (("vision", "VisionAgent"), ("gemma", "InterpretationAgent")):
        task = next((t for t in tasks["active"] if t["agent"] == agent), None)
        result[lane + "_worker_state"] = task["status"] if task else "IDLE"
        result[lane + "_task_id"] = task["command_id"] if task else None
        result[lane + "_task_simulated"] = bool(task and task.get("simulated"))
    names = {"temperature": "temperature_c", "humidity": "humidity_pct", "aqi": "aqi", "tvoc": "tvoc_ppb",
             "eco2": "eco2_ppm_equiv", "presence": "presence", "count": "visible_count"}
    for key, name in names.items():
        observation = context["observations"].get(key, {})
        result[name] = observation.get("value")
        for source, suffix in (("observation_id", "observation_id"), ("captured_at", "observed_at"),
                               ("age_seconds", "age_s"), ("status", "status")):
            result[key + "_" + suffix] = observation.get(source, "UNKNOWN" if source == "status" else None)
    radar = context["observations"].get("presence", {}).get("metadata", {})
    result.update(distance_cm=radar.get("trigger_distance_cm"), radar_status=result["presence_status"],
                  radar_state_code=radar.get("state_code"),
                  movement=radar["state_code"] in (1, 3) if radar.get("state_code") in (0, 1, 2, 3) else None,
                  sensor_data_status="VALID" if all(result[k + "_status"] == "VALID" for k in names if k != "count") else "PARTIAL")
    for key in ("motion_distance_cm", "static_distance_cm", "total_distance_cm", "motion_energy", "static_energy"):
        result[key] = radar.get(key)
    return result


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    # Conserva el texto del observador como texto al abrirlo en Excel.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _write_csv(archive, name, rows, fields):
    with archive.open(name + ".csv", "w") as binary:
        with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _cell(row.get(key)) for key in fields})


def export_csv_zip(path, run_id: str):
    """Snapshot WAL consistente; compresión en archivo temporal, no en RAM."""
    output = tempfile.TemporaryFile()
    try:
        with closing(sqlite3.connect(path)) as db:
            db.execute("BEGIN")
            row = db.execute("SELECT metadata, status, ended_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("Ejecución no encontrada.")
            run = dict(json.loads(row[0]), status=row[1], end_time=row[2])
            cutoff = db.execute("SELECT max(sequence) FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                sample_count = db.execute("SELECT count(*) FROM samples_1s WHERE run_id=?", (run_id,)).fetchone()[0]
                archive.writestr("metadata.json", json.dumps(dict(run, export_event_sequence=cutoff, exported_samples=sample_count), ensure_ascii=False, indent=2))
                archive.writestr("replay-manifest.json", json.dumps({
                    "schema": "sense-replay.v1", "run_id": run_id, "event_sequence": cutoff,
                    "files": ["metadata.json", "samples_1s.csv", "events.csv", "ground_truth.csv", "power_readings.csv", "observer_requests.csv"],
                    "images_stored": False,
                }))
                archive.writestr("LEEME.txt", "Snapshot de la ejecución al descargar. CSV UTF-8; celdas vacías = dato desconocido.\n"
                                 "Potencia W manual: hora observada distinta de hora registrada; no es energía ni consumo exclusivo de IA.\n"
                                 "samples_1s conserva datos retenidos con edad y referencia original. Segundos ausentes: SAMPLE_GAP en events.\n"
                                 "Personas: región observada, no necesariamente ocupación del aula. Fotografías no almacenadas.\n"
                                 "JSON anidado se conserva en columnas *_json. Tareas tardías pueden llegar después de esta descarga.\n"
                                 "Replay: importa este ZIP en la pestaña Replay; el manifiesto versiona las mismas fuentes CSV, sin duplicarlas.\n")
                samples = db.execute("SELECT payload FROM samples_1s WHERE run_id=? ORDER BY second", (run_id,))
                first = samples.fetchone()
                if first:
                    first_sample = json.loads(first[0])
                    def sample_rows():
                        yield dict(run_id=run_id, **first_sample)
                        for r in samples:
                            yield dict(run_id=run_id, **json.loads(r[0]))
                    _write_csv(archive, "samples_1s", sample_rows(), ["run_id", *first_sample])
                else:
                    _write_csv(archive, "samples_1s", [], ["run_id", "second", "timestamp_utc", "elapsed_s"])
                tasks, observations, images, faults = {}, {}, {}, {}
                def events():
                    for seq, at, kind, raw in db.execute("SELECT sequence,timestamp,type,payload FROM events WHERE run_id=? ORDER BY sequence", (run_id,)):
                        payload = json.loads(raw)
                        if kind.startswith("FAULT_") and payload.get("fault_id"):
                            faults[payload["fault_id"]] = dict(payload, run_id=run_id)
                        command = payload.get("command") if isinstance(payload.get("command"), dict) else payload if kind == "COMMAND_ISSUED" else None
                        if command:
                            task_id = command["command_id"]
                            task = tasks.setdefault(task_id, dict(run_id=run_id, task_id=task_id))
                            task.update(agent=command["target_agent"], action=command["action"], reason=command["reason"],
                                        requested_at=command["created_at"], cycle_id=command["correlation_id"],
                                        question_id=command["parameters"].get("question_id"),
                                        snapshot_id=command["parameters"].get("snapshot_id"))
                            task.update(fault_id=command["parameters"].get("fault_id"), simulated=command["parameters"].get("simulated", False), model_executed=command["parameters"].get("model_executed"))
                            if kind.startswith("TASK_"):
                                task.update(status=kind, **{k: payload[k] for k in ("started_at", "completed_at", "queue_seconds", "duration_seconds", "error", "late", "remote_execution_uncertain") if k in payload})
                                if kind == "TASK_TIMEOUT":
                                    task["timed_out"] = True
                                if "result" in payload:
                                    task["result_json"] = payload["result"]
                                    result = payload["result"]
                                    task.update({k: result.get(k) for k in ("image_id", "model_id", "runtime_model_id", "validation_status", "interpretation_id", "capture_seconds", "inference_seconds")})
                                    task["visible_count"] = result.get("count")
                                    if result.get("image_id"):
                                        images.setdefault(result["image_id"], dict(run_id=run_id, task_id=task_id, image_id=result["image_id"], captured_at=result.get("captured_at"), stored=False))
                        elif kind == "TASK_CANCELLED":
                            task = tasks.setdefault(payload["command_id"], dict(run_id=run_id, task_id=payload["command_id"]))
                            task.update(status=kind, cancelled=True)
                        if kind in ("OBSERVATIONS_RECEIVED", "CONTEXT_UPDATED"):
                            for key, observation in payload.get("observations", {}).items():
                                observations.setdefault(observation["observation_id"], dict(run_id=run_id, key=key, **observation))
                            if payload.get("raw_presence"):
                                observation = payload["raw_presence"]
                                observations.setdefault(observation["observation_id"], dict(run_id=run_id, key="raw_presence", **observation))
                        elif kind == "VISION_OBSERVATION":
                            observation = payload["observation"]
                            observations.setdefault(observation["observation_id"], dict(run_id=run_id, key="count", **observation))
                        task_id = command["command_id"] if command else payload.get("command_id") or payload.get("task_id") or (payload.get("request_id") if kind == "SLM_INPUT" else None)
                        event_at = payload.get("timestamp") or payload.get("captured_at") or payload.get("sampled_at") or at
                        if kind == "TASK_STARTED":
                            event_at = payload.get("started_at") or event_at
                        elif kind in ("TASK_COMPLETED", "TASK_FAILED"):
                            event_at = payload.get("completed_at") or event_at
                        elif kind == "COMMAND_ISSUED":
                            event_at = payload.get("created_at") or event_at
                        yield dict(run_id=run_id, sequence=seq, timestamp_utc=event_at, recorded_at=at, type=kind, task_id=task_id,
                                   event_id=payload.get("event_id") if kind != "OBSERVER_REQUESTED" else None, payload_json=payload)
                _write_csv(archive, "events", events(), ["run_id", "sequence", "event_id", "timestamp_utc", "recorded_at", "type", "task_id", "payload_json"])
                _write_csv(archive, "faults", faults.values(), ["run_id", "fault_id", "component", "kind", "simulated", "task_id", "baseline_status", "preexisting_failure", "activated_at", "activated_elapsed_s", "applied_at", "task_started_at", "detected_at", "detection_latency_s", "restored_at", "restored_elapsed_s", "recovered_at", "recovery_latency_s", "not_executed_reason"])
                _write_csv(archive, "inference_tasks", tasks.values(), ["run_id", "task_id", "fault_id", "simulated", "model_executed", "cycle_id", "agent", "action", "question_id", "reason", "snapshot_id", "image_id", "model_id", "runtime_model_id", "visible_count", "validation_status", "interpretation_id", "requested_at", "started_at", "completed_at", "queue_seconds", "duration_seconds", "capture_seconds", "inference_seconds", "status", "timed_out", "cancelled", "error", "late", "remote_execution_uncertain", "result_json"])
                _write_csv(archive, "observations", observations.values(), ["run_id", "key", "observation_id", "source_agent", "captured_at", "received_at", "region", "value", "unit", "quality", "status", "metadata"])
                _write_csv(archive, "images", images.values(), ["run_id", "task_id", "image_id", "captured_at", "stored"])
                def answers():
                    for at, raw in db.execute("SELECT timestamp,payload FROM events WHERE run_id=? AND type='RESULT_PUBLISHED' ORDER BY sequence", (run_id,)):
                        payload = json.loads(raw)
                        for question_id, answer in payload["answers"].items():
                            yield dict(run_id=run_id, timestamp_utc=at, cycle_id=payload["cycle_id"], question_id=question_id, **{k: v for k, v in answer.items() if k != "question_id"})
                _write_csv(archive, "question_results", answers(), ["run_id", "timestamp_utc", "cycle_id", "question_id", "question", "status", "answer", "evaluated_at", "evidence_ids", "limitations", "pending_information", "interpretation_id", "source_snapshot_id"])
                records = [dict(json.loads(r[3]), run_id=run_id, record_id=r[0], recorded_at=r[1], kind=r[2]) for r in db.execute("SELECT record_id,timestamp,kind,payload FROM human_records WHERE run_id=? ORDER BY rowid", (run_id,))]
                for record in records:
                    if record["kind"] == "EXTERNAL_POWER":
                        record["power_w"] = record.get("value")
                fields = ["run_id", "record_id", "request_id", "task_id", "event_id", "kind", "reason", "requested_at", "event_at", "observed_at", "power_observed_at", "people_observed_at", "recorded_at", "region", "observer", "notes", "unavailable_fields", "missing_reason", "repeated_fields"]
                _write_csv(archive, "ground_truth", (r for r in records if "visible_people" in r or "action" in r or r["kind"] == "GROUND_TRUTH"), fields + ["visible_people", "action"])
                _write_csv(archive, "power_readings", (r for r in records if "power_w" in r or "power_w" in r.get("unavailable_fields", []) or r["kind"] in ("EXTERNAL_POWER", "EXTERNAL_ENERGY")), fields + ["power_w", "instrument", "equipment", "scope", "value", "unit"])
                requests = [dict(run_id=run_id, request_id=r[0], requested_at=r[1], reason=r[2], task_id=r[3], event_id=r[4], fields=json.loads(r[5]), status=r[6], record_id=r[7]) for r in db.execute("SELECT request_id,requested_at,reason,task_id,event_id,fields,status,record_id FROM observer_requests WHERE run_id=? ORDER BY rowid", (run_id,))]
                _write_csv(archive, "observer_requests", requests, ["run_id", "request_id", "requested_at", "reason", "task_id", "event_id", "fields", "status", "record_id"])
            db.rollback()
        output.seek(0)
        return output
    except Exception:
        output.close()
        raise
