"""Políticas A–D y ejecución pesada; nunca bloquea la ingesta de sensores."""

import asyncio
import json
import time
from collections import deque
from pathlib import Path
from uuid import uuid4

import psutil

from context import ACQUISITION_PROFILE, MQTT_SOURCES, aware_time, digest, encoded
from orchestrator import Conflict, State
from slm import CompletedResponseError, NoRequestError, SLM, model_evidence
from store import utc_now
from vision import CameraWorker


class Actions:
    def __init__(self, runtime):
        self.runtime = runtime
        self.queue = deque()
        self.task = None
        self.current = None
        self.stop_reason = None
        self.camera = CameraWorker(runtime.settings.camera_config())
        self.slm = SLM(runtime.settings.slm_url, runtime.settings.slm_model,
                       ACQUISITION_PROFILE["slm_timeout_s"], ACQUISITION_PROFILE["slm_max_completion_tokens"])
        self.last_visual_start = -1000
        self.periodic_due = 0
        self.vision_failures = 0
        self.followup_due = 0
        self.count_need_started = None
        self.vision_suspended = False
        self.pending_count_parent = None
        self.last_conflict_signature = None
        self.camera_version = 0

    @property
    def engine(self):
        return self.runtime.engine

    def reset(self):
        self.queue.clear()
        self.stop_reason = None
        self.last_visual_start, self.periodic_due = -1000, 0
        self.vision_failures, self.followup_due = 0, 0
        self.count_need_started, self.vision_suspended = None, False
        self.pending_count_parent = None
        self.last_conflict_signature = None
        self.camera_version = 0

    def new_count_need(self):
        self.vision_suspended, self.vision_failures = False, 0
        self.count_need_started, self.pending_count_parent = None, None
        self.followup_due = self.engine.elapsed

    def submit(self, tool, reason, snapshot=None, artifact_id=None, followup_of=None, source_run_id=None):
        if self.stop_reason:
            raise Conflict("la sesión se está cerrando")
        if len(self.queue) >= ACQUISITION_PROFILE["heavy_queue_capacity"]:
            self.engine.emit("admission.rejected", {"reason": "heavy_queue_full", "tool": tool})
            raise Conflict("cola de acciones pesadas llena")
        if self.camera.failed_stop:
            raise Conflict("worker sin detención confirmada; slot pesado ocupado")
        if (self.runtime.store.flag("slm_busy") or self.runtime.store.flag("camera_busy")) and not (self.current and self.task and not self.task.done()):
            raise Conflict("recurso pesado reservado: falta confirmar que LiteRT-LM terminó")
        if self.runtime.settings.mode != "live":
            raise Conflict("el replay sin imágenes pareadas no ejecuta cámara ni SLM")
        job = {"job_id": str(uuid4()), "episode_id": str(uuid4()), "run_id": self.engine.run_id,
               "tool": tool, "reason": reason, "snapshot": snapshot, "artifact_id": artifact_id,
               "followup_of_episode_id": followup_of, "source_run_id": source_run_id,
               "queued_elapsed_s": self.engine.elapsed, "queued_monotonic": time.monotonic()}
        job["followup_deadline_elapsed_s"] = (self.count_need_started+ACQUISITION_PROFILE["max_followup_lifetime_s"]
                                              if tool == "count_people" and self.count_need_started is not None else None)
        self.engine.emit("job.queued", {k: v for k, v in job.items() if k not in ("snapshot", "queued_monotonic")})
        self.queue.append(job)
        return {"job_id": job["job_id"], "episode_id": job["episode_id"], "status": "queued"}

    def count_is_fresh(self):
        source = self.engine.sources["camera"]
        return bool(source.usable and source.latest and "visible_person_count" in source.latest["values"]
                    and source.latest.get("time_basis") != "uploaded_image_unknown_capture_time"
                    and self.engine.elapsed-source.latest["elapsed_s"] <= ACQUISITION_PROFILE["visual_count_ttl_s"])

    def tick(self):
        if self.task and self.task.done():
            self.task.result()
            self.task, self.current = None, None
        if not self.engine.run_id:
            return
        if self.stop_reason:
            if not self.task:
                status, reason = self.stop_reason
                self.engine.finish(status, reason)
            return
        request, elapsed = self.engine.request, self.engine.elapsed
        variant = request.get("variant", "rules-v1")
        camera = self.engine.sources["camera"]
        if camera.status == "awaiting_fresh_data" and camera.availability_version != self.camera_version:
            self.new_count_need()
        self.camera_version = camera.availability_version
        if camera.usable and camera.latest and elapsed-camera.latest["elapsed_s"] > ACQUISITION_PROFILE["visual_count_ttl_s"]:
            self.engine.availability("camera", "stale_receipt", "visual_evidence_expired")
        while self.engine.triggers:
            trigger = self.engine.triggers.popleft()
            if variant == "D" and trigger["reason"] == "environment_change_persistent":
                snapshot = trigger["snapshot"]
                snapshot["derived_metrics"] = trigger["details"]
                snapshot["snapshot_id"] = digest({k: v for k, v in snapshot.items() if k != "snapshot_id"})
                self.safe_submit("interpret_context", trigger["reason"], snapshot=snapshot, followup_of=trigger["episode_id"])
            entry = trigger["reason"] == "presence_changed" and trigger["details"].get("present")
            if entry:
                self.new_count_need()
            if variant == "B" and entry and request.get("monitor_count"):
                self.safe_submit("count_people", "radar_entry")
            if trigger["reason"] == "source_recovered" and trigger["details"].get("source_id") == "camera":
                self.vision_suspended = False
        already_visual = any(j["tool"] in ("count_people", "describe_image") for j in self.queue) or (self.current and self.current["tool"] in ("count_people", "describe_image"))
        if request.get("monitor_count") and not already_visual:
            if variant == "A" and elapsed >= self.periodic_due:
                self.periodic_due = elapsed+ACQUISITION_PROFILE["periodic_vision_interval_s"]
                self.safe_submit("count_people", "periodic_vision")
            if variant in ("C", "D") and not self.count_is_fresh() and elapsed >= self.followup_due and not self.vision_suspended:
                if self.count_need_started is None:
                    self.count_need_started = elapsed
                self.safe_submit("count_people", "count_missing_or_stale", followup_of=self.pending_count_parent)
        if not self.task and self.queue and not self.runtime.store.flag("slm_busy") and not self.runtime.store.flag("camera_busy") and not self.camera.failed_stop:
            self.current = self.queue.popleft()
            self.task = asyncio.create_task(self.execute(self.current))

    def safe_submit(self, *args, **kwargs):
        try:
            return self.submit(*args, **kwargs)
        except Conflict as error:
            self.engine.emit("action.deferred", {"reason": str(error), "tool": args[0]})
            self.followup_due = self.engine.elapsed+ACQUISITION_PROFILE["followup_interval_s"]

    def snapshot_at_capture(self, result):
        engine = self.engine
        snapshot = engine.snapshot()
        captured = result["timing"].get("capture_monotonic_ns")
        capture_elapsed = captured/1e9-self.runtime.start_monotonic if captured is not None else None
        for name in MQTT_SOURCES:
            source = engine.sources[name]
            candidates = [item for item in source.evidence_history if capture_elapsed is not None and item["elapsed_s"] <= capture_elapsed]
            latest = candidates[-1] if candidates else None
            usable = bool(latest and capture_elapsed-latest["elapsed_s"] < 7 and latest["availability_version"] == source.availability_version
                          and source.fault_mode not in ("disabled", "error"))
            snapshot["sources"][name].update(latest=latest, usable_for_reported_values=usable,
                                           receipt_age_s=capture_elapsed-latest["elapsed_s"] if latest else None,
                                           receipt_age_at_capture_s=capture_elapsed-latest["elapsed_s"] if latest else None)
        snapshot["confirmed_radar_presence"] = None
        snapshot["capture_elapsed_s"] = capture_elapsed
        snapshot["created_elapsed_s"] = self.engine.elapsed
        snapshot["elapsed_s"] = capture_elapsed
        snapshot["reference_time_basis"] = result["timing"]["time_basis"]
        snapshot["sources"]["camera"]["receipt_age_s"] = 0 if capture_elapsed is not None else None
        snapshot["temporal_comparison"] = self.comparison(snapshot, result)
        snapshot["snapshot_id"] = digest({k: v for k, v in snapshot.items() if k != "snapshot_id"})
        return json.loads(encoded(snapshot))

    def comparison(self, snapshot, result):
        settings, request = self.runtime.settings, self.engine.request
        radar = snapshot["sources"]["ld2410c"]
        limit = request.get("crossmodal_max_skew_s")
        timing = result["timing"]
        if not (request.get("overlap_verified") and limit is not None and radar["usable_for_reported_values"]
                and settings.radar_timestamp_is_measurement and settings.radar_uncertainty_s is not None
                and settings.camera_uncertainty_s is not None and timing.get("captured_at")):
            return {"status": "not_comparable", "reason": "scope_or_acquisition_clock_unverified"}
        skew = abs((aware_time(radar["latest"]["source_timestamp"])-aware_time(timing["captured_at"])).total_seconds())
        bound = skew+settings.radar_uncertainty_s+settings.camera_uncertainty_s
        if bound > limit:
            return {"status": "not_comparable", "reason": "temporal_skew_exceeded", "conservative_skew_s": bound}
        conflict = (radar["latest"]["values"]["state_code"] != 0) != (result.get("visible_person_count", 0) > 0)
        return {"status": "conflicting" if conflict else "consistent", "conservative_skew_s": bound}

    async def execute(self, job):
        engine = self.engine
        episode_id, tool = job["episode_id"], job["tool"]
        action_id = str(uuid4())
        source_name = "camera" if tool in ("count_people", "describe_image") else "slm"
        job["active_source"] = source_name
        action_tool = "capture_image" if tool == "describe_image" else tool
        source = engine.sources[source_name]
        version = source.availability_version
        snapshot = job["snapshot"] or engine.snapshot()
        engine.transition(State.ACQUIRE, job["reason"], episode_id)
        engine.emit("snapshot.created", snapshot, episode_id)
        engine.transition(State.ASSESS, "tool_guard", episode_id, snapshot["snapshot_id"])
        started = False
        artifact_id = None
        success = False
        monitor_job = tool == "count_people" and job["reason"] == "count_missing_or_stale"

        def remaining():
            budget = ACQUISITION_PROFILE["episode_deadline_s"]-(time.monotonic()-job["queued_monotonic"])
            if job["followup_deadline_elapsed_s"] is not None:
                budget = min(budget, job["followup_deadline_elapsed_s"]-engine.elapsed)
            if budget <= 0:
                raise TimeoutError("plazo del episodio o seguimiento agotado")
            return budget
        try:
            remaining()
            if time.monotonic()-job["queued_monotonic"] > ACQUISITION_PROFILE["episode_deadline_s"]:
                raise ValueError("plazo del episodio agotado en cola")
            if source.fault_mode in ("disabled", "error"):
                raise ValueError("fuente requerida indisponible")
            memory = psutil.virtual_memory()
            if memory.available < ACQUISITION_PROFILE["reserve_memory_bytes"]:
                raise ValueError("memoria disponible menor que reserva candidata de 512 MiB")
            try:
                temperatures = psutil.sensors_temperatures()
            except (OSError, AttributeError):
                temperatures = {}
            if any(item.current >= ACQUISITION_PROFILE["max_cpu_temperature_c"] for name, rows in temperatures.items() if name in ("cpu_thermal", "coretemp", "k10temp") for item in rows):
                raise ValueError("temperatura CPU excede guarda candidata de 80 °C")
            if source_name == "camera":
                wait = self.last_visual_start+ACQUISITION_PROFILE["vision_cooldown_s"]-engine.elapsed
                if wait > 0:
                    raise ValueError("cooldown de visión activo")
                if tool == "count_people" and not self.runtime.settings.vision_model:
                    raise ValueError("falta configurar exportación NCNN local")
            elif not all(snapshot["sources"][name]["usable_for_reported_values"] for name in MQTT_SOURCES):
                raise ValueError("evidencia insuficiente para interpretar contexto")
            engine.transition(State.VISION if source_name == "camera" else State.INTERPRET, job["reason"], episode_id, snapshot["snapshot_id"])
            started_at = time.monotonic()
            engine.emit("action.started", {"action_id": action_id, "tool": action_tool, "status": "running", "snapshot_id": snapshot["snapshot_id"],
                                          "queue_duration_s": started_at-job["queued_monotonic"]}, episode_id)
            started = True
            if source_name == "camera":
                self.last_visual_start = engine.elapsed
                artifact_id = str(uuid4())
                output = self.runtime.artifact_dir/(artifact_id+".jpg")
                input_path = self.runtime.store.artifact(job["artifact_id"])["path"] if job["artifact_id"] else None
                if input_path and not Path(input_path).is_file():
                    raise ValueError("imagen de entrada ya no disponible")
                budget = min(remaining(), ACQUISITION_PROFILE["vision_timeout_s"])
                self.runtime.store.flag("camera_busy", {"run_id": job["run_id"], "action_id": action_id, "boot_id": engine.boot_id,
                                                         "state": "request_in_flight"}, write=True)
                result = await self.camera.run({"kind": "count" if tool == "count_people" else "capture", "output_path": str(output),
                                                "artifact_id": artifact_id, "input_path": input_path}, budget)
                self.runtime.store.flag("camera_busy", None, write=True)
                self.runtime.store.artifact(artifact_id, output, {**result, "run_id": job["run_id"], "retained": engine.request.get("retain_images", False)})
            else:
                budget = remaining()
                self.runtime.store.flag("slm_busy", {"run_id": job["run_id"], "action_id": action_id, "state": "request_in_flight"}, write=True)
                async with asyncio.timeout(budget):
                    result = await self.slm.interpret(snapshot, "Explica únicamente los hechos y cambios respaldados por la evidencia.")
                self.runtime.store.flag("slm_busy", None, write=True)
            duration = time.monotonic()-started_at
            if self.stop_reason or source.availability_version != version or source.fault_mode in ("drop", "freeze", "disabled", "error"):
                engine.emit("action.suppressed", {"action_id": action_id, "tool": tool, "status": "suppressed",
                            "reason": "cancelled_or_availability_version_changed", "result": result, "duration_s": duration}, episode_id)
                raise ValueError("resultado tardío o suprimido; no se incorpora al contexto")
            if source_name == "camera":
                captured_ns = result["timing"].get("capture_monotonic_ns")
                captured_elapsed = captured_ns/1e9-self.runtime.start_monotonic if captured_ns else engine.elapsed
                reading = {"observation_id": artifact_id, "values": {k: result[k] for k in ("visible_person_count", "boxes") if k in result},
                                 "elapsed_s": captured_elapsed, "received_at": utc_now(), "source_timestamp": result["timing"].get("captured_at"),
                                 "quality_flags": result["quality_flags"]+[result["timing"]["time_basis"]], "artifact_id": artifact_id,
                                 "time_basis": result["timing"]["time_basis"]}
                if not input_path:
                    source.latest = reading
                    engine.availability("camera", "recent_receipt", "capture_completed")
                snapshot = self.snapshot_at_capture(result)
                if input_path:
                    snapshot["sources"]["camera"].update(latest=reading, usable_for_reported_values=True)
                snapshot["snapshot_id"] = digest({k: v for k, v in snapshot.items() if k != "snapshot_id"})
                engine.emit("snapshot.created", snapshot, episode_id)
                if tool == "count_people":
                    engine.emit("observation.accepted", {"source_id": "camera", "observation_id": artifact_id,
                                "source_timestamp": reading["source_timestamp"], "quality_flags": reading["quality_flags"],
                                "observations": [{"metric": "visible_person_count", "value": result["visible_person_count"], "unit": "people_detected"}]}, episode_id)
                else:
                    if engine.request.get("variant") != "E_visual":
                        raise ValueError("descripción de imagen requiere variante E_visual separada")
                    slm_source = engine.sources["slm"]
                    slm_version = slm_source.availability_version
                    if slm_source.fault_mode:
                        raise ValueError("intérprete indisponible")
                    engine.transition(State.INTERPRET, "explicit_image_description", episode_id, snapshot["snapshot_id"])
                    engine.emit("action.completed", {"action_id": action_id, "tool": "capture_image", "status": "completed", "duration_s": duration,
                                                       "result": result}, episode_id)
                    action_id = str(uuid4())
                    action_tool = "describe_image"
                    job["active_source"] = "slm"
                    started_at = time.monotonic()
                    engine.emit("action.started", {"action_id": action_id, "tool": "describe_image", "status": "running"}, episode_id)
                    budget = remaining()
                    self.runtime.store.flag("slm_busy", {"run_id": job["run_id"], "action_id": action_id, "state": "request_in_flight"}, write=True)
                    async with asyncio.timeout(budget):
                        result = await self.slm.interpret(snapshot, "Describe únicamente lo visible en la imagen; declara límites y ambigüedades.",
                                                          output, artifact_id, self.runtime.settings.slm_image_side)
                    self.runtime.store.flag("slm_busy", None, write=True)
                    if self.stop_reason or slm_source.availability_version != slm_version or slm_source.fault_mode:
                        raise ValueError("descripción tardía o suprimida por disponibilidad")
            engine.emit("action.completed", {"action_id": action_id, "tool": tool, "status": "completed", "duration_s": time.monotonic()-started_at,
                                               "result": result, "snapshot_id": snapshot["snapshot_id"]}, episode_id)
            engine.transition(State.REPORT, "tool_completed", episode_id, snapshot["snapshot_id"])
            stale = source_name == "camera" and tool == "count_people" and (job["artifact_id"] is not None or not self.count_is_fresh())
            historical = stale or job["source_run_id"] is not None
            answer = {"question": tool, "snapshot_id": snapshot["snapshot_id"], "source_run_id": job["source_run_id"],
                      "status": "historical" if historical else "supported_with_limitations",
                      "content_json": result, "evidence_hash": digest(model_evidence(snapshot)), "followup_of_episode_id": job["followup_of_episode_id"],
                      "followup_status": ("pending_followup" if monitor_job else "insufficient_evidence") if stale else "resolved_by_evidence"}
            engine.emit("answer.validated", answer, episode_id)
            engine.latest_answer = {**answer, "episode_id": episode_id}
            if tool in ("interpret_context", "describe_image"):
                interpreter = engine.sources["slm"]
                interpreter.latest = {"observation_id": action_id, "values": {"interpretation_status": result["validated"]["status"]},
                                      "elapsed_s": engine.elapsed, "source_timestamp": None, "received_at": utc_now(),
                                      "quality_flags": ["model_output_requires_human_evaluation"]}
                engine.availability("slm", "recent_receipt", "validated_interpretation_received")
            success = not (stale and monitor_job)
            if tool == "count_people" and not stale:
                self.vision_failures, self.vision_suspended, self.count_need_started, self.pending_count_parent = 0, False, None, None
            if tool == "count_people":
                comparison = snapshot["temporal_comparison"]["status"]
                if comparison == "consistent":
                    self.last_conflict_signature = None
                if comparison == "conflicting" and engine.request.get("variant") == "D":
                    signature = digest({"radar_present": snapshot["sources"]["ld2410c"]["latest"]["values"]["state_code"] != 0,
                                        "visible_person_count": result["visible_person_count"], "scope_id": result["scope_id"]})
                    if signature != self.last_conflict_signature:
                        queued = self.safe_submit("interpret_context", "crossmodal_conflict", snapshot=snapshot, followup_of=episode_id)
                        if queued:
                            self.last_conflict_signature = signature
                    else:
                        engine.emit("action.omitted", {"tool": "interpret_context", "reason": "unchanged_conflict_already_interpreted"}, episode_id)
        except asyncio.CancelledError:
            if not self.camera.failed_stop and self.camera.process is None:
                self.runtime.store.flag("camera_busy", None, write=True)
            remote = job.get("active_source") == "slm"
            engine.emit("action.cancel_pending" if remote else "action.cancelled",
                        {"action_id": action_id, "tool": action_tool, "status": "remote_stop_unconfirmed" if remote else "cancelled",
                         "reason": "transport_cancelled_remote_unknown" if remote else "worker_stopped"}, episode_id)
            raise
        except Exception as error:
            if not self.camera.failed_stop and self.camera.process is None:
                self.runtime.store.flag("camera_busy", None, write=True)
            if isinstance(error, (CompletedResponseError, NoRequestError)):
                self.runtime.store.flag("slm_busy", None, write=True)
            if self.runtime.store.flag("slm_busy") or self.runtime.store.flag("camera_busy"):
                engine.emit("resource.reservation_unconfirmed", {"action_id": action_id, "reason": "remote_inference_stop_not_acknowledged"}, episode_id)
            if started and not self.stop_reason:
                failed_source = "slm" if action_tool in ("interpret_context", "describe_image") else "camera"
                if engine.sources[failed_source].fault_mode is None:
                    engine.availability(failed_source, "error", "tool_failed")
            engine.emit("action.failed", {"action_id": action_id, "tool": action_tool, "status": "failed", "started": started,
                                          "reason": str(error)[:1000]}, episode_id)
            engine.transition(State.DEGRADED, "tool_failed_or_insufficient_evidence", episode_id, snapshot["snapshot_id"])
            engine.transition(State.REPORT, "abstain_without_fabricating_values", episode_id, snapshot["snapshot_id"])
            pending = monitor_job and self.vision_failures < ACQUISITION_PROFILE["max_followups"]
            answer = {"question": tool, "snapshot_id": snapshot["snapshot_id"], "status": "insufficient_evidence",
                      "content_json": {"reason": str(error)[:1000], "visible_person_count": None},
                      "followup_status": "pending_followup" if pending else "insufficient_evidence"}
            engine.emit("answer.validated", answer, episode_id)
            engine.latest_answer = {**answer, "episode_id": episode_id}
        finally:
            if artifact_id and not engine.request.get("retain_images", False):
                (self.runtime.artifact_dir/(artifact_id+".jpg")).unlink(missing_ok=True)
            engine.transition(State.WAIT, "episode_persisted", episode_id, snapshot["snapshot_id"])
            if not success and monitor_job and not self.stop_reason:
                self.vision_failures += 1
                self.pending_count_parent = episode_id
                self.count_need_started = self.count_need_started if self.count_need_started is not None else engine.elapsed
                self.followup_due = engine.elapsed+ACQUISITION_PROFILE["followup_interval_s"]
                self.vision_suspended = (self.vision_failures > ACQUISITION_PROFILE["max_followups"]
                                         or engine.elapsed-self.count_need_started >= ACQUISITION_PROFILE["max_followup_lifetime_s"])
                engine.emit("followup.expired" if self.vision_suspended else "followup.scheduled",
                            {"followup_of_episode_id": episode_id, "next_check_elapsed_s": None if self.vision_suspended else self.followup_due,
                             "attempts": self.vision_failures})

    async def stop(self, status, reason):
        if self.stop_reason is None:
            self.stop_reason = (status, reason)
            self.engine.emit("run.cancel_requested" if status == "cancelled" else "run.finish_requested", {"reason": reason})
            while self.queue:
                job = self.queue.popleft()
                self.engine.emit("job.cancelled", {"job_id": job["job_id"], "reason": reason})
            if self.task and self.current.get("active_source", "camera" if self.current["tool"] in ("count_people", "describe_image") else "slm") == "camera":
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
                self.task, self.current = None, None
        if not self.task:
            final_status, final_reason = self.stop_reason
            self.engine.finish(final_status, final_reason)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.camera.stop()
        reservation = self.runtime.store.flag("camera_busy")
        if reservation and reservation.get("boot_id") == self.engine.boot_id:
            self.runtime.store.flag("camera_busy", None, write=True)
