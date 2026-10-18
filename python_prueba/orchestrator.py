"""Un escritor lógico: ingesta, fallos y FSM ocurren en el mismo event loop."""

import json
from collections import deque
from enum import Enum
from uuid import uuid4

from context import (FIELDS, MQTT_SOURCES, PROFILE, SOURCES, ChangeDetector, Presence, Source,
                     aware_time, digest, encoded, parse_message, source_values)
from store import utc_now


class Conflict(ValueError):
    pass


class State(str, Enum):
    WAIT = "WAIT"
    ACQUIRE = "ACQUIRE"
    ASSESS = "ASSESS"
    VISION = "VISION"
    INTERPRET = "INTERPRET"
    DEGRADED = "DEGRADED"
    REPORT = "REPORT"


class Engine:
    def __init__(self, store):
        self.store = store
        self.boot_id = str(uuid4())
        self.run_id = None
        self.elapsed = 0.0
        self.state = State.WAIT
        self.sources = {name: Source() for name in SOURCES}
        self.detectors = {metric: ChangeDetector() for metric in PROFILE["change_delta"]}
        self.presence = Presence()
        self.faults = {}
        self.last_source_time = None
        self.last_message_hash = None
        self.latest_answer = None
        self.triggers = deque()
        self.episode_states = {}

    def emit(self, kind, payload, episode_id=None):
        return self.store.append(self.run_id, kind, payload, self.elapsed, self.boot_id, episode_id)

    def start(self, request, key, manifest):
        request_hash = digest(request)
        previous = self.store.by_key(key) if key else None
        if previous:
            if previous["request_hash"] != request_hash:
                raise Conflict("clave de idempotencia reutilizada con otro cuerpo")
            return previous["run_id"], False
        if self.run_id:
            raise Conflict("ya hay una sesión activa")
        run_id = str(uuid4())
        self.store.create(run_id, key, request_hash, manifest, self.boot_id)
        self.run_id, self.request, self.elapsed = run_id, request, 0.0
        self.sources = {name: Source() for name in SOURCES}
        self.detectors = {metric: ChangeDetector() for metric in PROFILE["change_delta"]}
        self.presence = Presence()
        self.faults, self.last_source_time, self.last_message_hash = {}, None, None
        self.latest_answer, self.state = None, State.WAIT
        self.triggers.clear()
        self.episode_states.clear()
        self.emit("run.started", {"state": self.state, "reason": "collecting_evidence"})
        return run_id, True

    def require_active(self, run_id):
        if self.run_id != run_id:
            self.store.run(run_id)
            raise Conflict("la sesión no está activa")

    def snapshot(self):
        data = {"elapsed_s": self.elapsed, "state": self.state,
                "active_episodes": dict(self.episode_states),
                "sources": {name: source.snapshot(self.elapsed) for name, source in self.sources.items()},
                "confirmed_radar_presence": self.presence.stable if self.sources["ld2410c"].usable else None,
                "measurement_freshness": "unknown", "profile_id": PROFILE["id"]}
        data["snapshot_id"] = digest(data)
        return json.loads(encoded(data))

    def transition(self, state, reason, episode_id, snapshot_id=None):
        previous = self.episode_states.get(episode_id, State.WAIT)
        self.emit("state.changed", {"from_state": previous, "to_state": state,
                                   "reason": reason, "snapshot_id": snapshot_id}, episode_id)
        self.state = state
        if state == State.WAIT:
            self.episode_states.pop(episode_id, None)
        else:
            self.episode_states[episode_id] = state

    def episode(self, reason, details=None, question="monitor"):
        episode_id = str(uuid4())
        self.transition(State.ACQUIRE, reason, episode_id)
        snapshot = self.snapshot()
        self.emit("snapshot.created", snapshot, episode_id)
        self.transition(State.ASSESS, "assess_reported_values", episode_id, snapshot["snapshot_id"])
        required = ("ld2410c",) if question == "presence" else (("sht40", "ens160") if question == "environment" else MQTT_SOURCES)
        missing = [name for name in required if not self.sources[name].usable]
        if question == "presence" and self.presence.stable is None:
            missing = list(set(missing) | {"ld2410c"})
        facts = {name: self.sources[name].latest["values"] if self.sources[name].usable else None for name in required}
        if missing:
            self.transition(State.DEGRADED, "insufficient_evidence", episode_id, snapshot["snapshot_id"])
        self.transition(State.REPORT, "rules_sufficient" if not missing else "partial_report", episode_id, snapshot["snapshot_id"])
        answer = {"snapshot_id": snapshot["snapshot_id"], "question": question,
                  "status": "partial" if missing else "reported_values",
                  "content_json": {"facts": facts, "confirmed_radar_presence": snapshot["confirmed_radar_presence"],
                                   "reason": reason, "trigger": details, "missing_sources": sorted(missing),
                                   "camera_calls": 0, "slm_calls": 0, "measurement_freshness": "unknown",
                                   "limitations": ["reported_sensor_values_not_ground_truth", "sensor_quality_unverified"]},
                  "followup_status": "insufficient_evidence" if missing else (
                      "pending_followup" if reason == "environment_change_persistent" else "resolved_by_evidence"),
                  "followup_of_episode_id": (details or {}).get("followup_of_episode_id")}
        self.emit("answer.validated", answer, episode_id)
        self.latest_answer = {**answer, "episode_id": episode_id}
        self.transition(State.WAIT, "episode_persisted", episode_id, snapshot["snapshot_id"])
        if reason in ("presence_changed", "environment_change_persistent", "source_recovered"):
            self.triggers.append({"reason": reason, "details": details, "snapshot": snapshot, "episode_id": episode_id})
        return self.latest_answer

    def _interrupt(self, name):
        self.sources[name].reset_history()
        if name == "ld2410c":
            self.presence.reset()
        for metric, detector in self.detectors.items():
            if metric in FIELDS.get(name, {}):
                detector.interrupt()

    def availability(self, name, status, reason):
        source = self.sources[name]
        if source.status != status:
            previous, source.status = source.status, status
            source.availability_version += 1
            self.emit("source.availability_changed", {"source_id": name, "previous": previous,
                      "status": status, "reason": reason, "availability_version": source.availability_version})
            return True
        return False

    def tick(self, elapsed):
        if not self.run_id:
            return
        if elapsed < self.elapsed:
            raise ValueError("el reloj lógico no puede retroceder")
        self.elapsed = elapsed
        for fault in list(self.faults.values()):
            if fault["status"] == "applied" and fault["end_elapsed_s"] is not None and elapsed >= fault["end_elapsed_s"]:
                self.clear_fault(fault["fault_id"])
        for fault in list(self.faults.values()):
            if fault["status"] == "scheduled" and elapsed >= fault["start_elapsed_s"]:
                if fault["end_elapsed_s"] is not None and elapsed >= fault["end_elapsed_s"]:
                    fault.update(status="cleared", missed_elapsed_s=elapsed)
                    self.emit("fault.missed", fault)
                    self.emit("protocol.deviation", {"reason": "scheduled_fault_window_missed", "fault_id": fault["fault_id"]})
                else:
                    self.apply_fault(fault)
        for name, source in self.sources.items():
            if name not in MQTT_SOURCES:
                continue
            last = source.latest["elapsed_s"] if source.latest else 0
            if source.status in ("recent_receipt", "never_observed") and elapsed-last >= PROFILE["telemetry_silence_s"]:
                if self.availability(name, "stale_receipt", "receipt_watchdog_expired"):
                    self._interrupt(name)
                    self.episode("source_silent", {"source_id": name})

    def ingest(self, raw, elapsed, received_at=None, receipt_elapsed=None, retained=False, qos=0):
        if not self.run_id:
            return
        self.tick(max(elapsed, self.elapsed))
        try:
            message = parse_message(raw)
        except (ValueError, OverflowError) as error:
            self.emit("message.rejected", {"reason": str(error)[:300], "bytes": len(raw)})
            return
        self.emit("mqtt.message", {"message": message, "received_at": received_at or utc_now(),
                                  "received_elapsed_s": receipt_elapsed, "retained": retained, "qos": qos})
        timestamp = aware_time(message["timestamp"])
        message_hash = digest(message)
        if retained:
            self.emit("message.rejected", {"reason": "retained_not_new_evidence", "source_timestamp": message["timestamp"]})
            return
        if self.last_source_time is not None and timestamp <= self.last_source_time:
            reason = "duplicate_timestamp" if timestamp == self.last_source_time and message_hash == self.last_message_hash else "nonincreasing_or_conflicting_source_timestamp"
            self.emit("message.rejected", {"reason": reason, "source_timestamp": message["timestamp"]})
            return
        self.last_source_time, self.last_message_hash = timestamp, message_hash
        for name in MQTT_SOURCES:
            source = self.sources[name]
            try:
                values = source_values(message, name)
            except ValueError as error:
                self.emit("observation.rejected", {"source_id": name, "reason": str(error), "source_timestamp": message["timestamp"]})
                if source.fault_mode not in ("disabled", "error", "drop", "freeze"):
                    if self.availability(name, "invalid", "invalid_source_block"):
                        self.episode("source_invalid", {"source_id": name})
                    self._interrupt(name)
                continue
            observations = [{"metric": metric, "value": value, "unit": FIELDS[name][metric]} for metric, value in values.items()]
            base = {"source_id": name, "source_timestamp": message["timestamp"], "observations": observations,
                    "received_at": received_at or utc_now(), "received_elapsed_s": receipt_elapsed}
            if self.elapsed-elapsed >= PROFILE["telemetry_silence_s"]:
                self.emit("observation.suppressed", {**base, "reason": "queued_sample_expired"})
                continue
            if source.fault_mode:
                self.emit("observation.suppressed", {**base, "fault_id": source.fault_id, "reason": source.fault_mode})
                continue
            previous = source.status
            if previous != "recent_receipt":
                self.availability(name, "recent_receipt", "new_nonretained_source_timestamp")
            overflow = source.accept(values, message["timestamp"], base["received_at"], elapsed, receipt_elapsed)
            self.emit("observation.accepted", {**base, "observation_id": source.latest["observation_id"],
                                               "quality_flags": source.latest["quality_flags"]})
            if overflow:
                self.emit("history.reset", {"source_id": name, "reason": "4096_sample_capacity"})
                if name == "ld2410c":
                    self.presence.reset()
                for metric, detector in self.detectors.items():
                    if metric in FIELDS[name]:
                        detector.interrupt()
            if previous in ("stale_receipt", "invalid", "awaiting_fresh_data", "error", "disabled"):
                self.episode("source_recovered", {"source_id": name})
            if name == "ld2410c":
                event = self.presence.evaluate(values["state_code"], elapsed)
                if event:
                    self.episode(event["kind"], event)
            else:
                for metric in values:
                    if metric not in self.detectors:
                        continue
                    event = self.detectors[metric].evaluate(metric, source, elapsed)
                    if event:
                        answer = self.episode(event["kind"], event)
                        if event["kind"] == "environment_change_persistent":
                            self.detectors[metric].opening_episode_id = answer["episode_id"]

    def add_fault(self, request):
        name = request["source_id"]
        start = self.elapsed+request["start_after_s"]
        duration = request["duration_s"]
        end = start+duration if duration is not None else float("inf")
        if any(f["source_id"] == name and f["status"] != "cleared" and start < (f["end_elapsed_s"] if f["end_elapsed_s"] is not None else float("inf"))
               and f["start_elapsed_s"] < end for f in self.faults.values()):
            raise Conflict("ya existe un fallo solapado para esta fuente")
        fault = {**request, "fault_id": str(uuid4()), "status": "scheduled", "start_elapsed_s": start,
                 "end_elapsed_s": start+duration if duration is not None else None}
        self.emit("fault.scheduled", fault)
        self.faults[fault["fault_id"]] = fault
        if request["start_after_s"] == 0:
            self.apply_fault(fault)
        return dict(fault)

    def apply_fault(self, fault):
        name = fault["source_id"]
        source = self.sources[name]
        source.fault_id, source.fault_mode = fault["fault_id"], fault["mode"]
        fault.update(status="applied", applied_elapsed_s=self.elapsed)
        self.emit("fault.applied", fault)
        source.availability_version += 1
        if fault["mode"] in ("disabled", "error"):
            self.availability(name, fault["mode"], "source_unavailable")
            self._interrupt(name)
            self.episode("source_unavailable", {"source_id": name})

    def clear_fault(self, fault_id):
        fault = self.faults[fault_id]
        if fault["status"] == "cleared":
            return dict(fault)
        if fault["status"] == "applied":
            source = self.sources[fault["source_id"]]
            source.fault_id = source.fault_mode = None
            source.availability_version += 1
            self.availability(fault["source_id"], "awaiting_fresh_data", "override_removed")
            self._interrupt(fault["source_id"])
        fault.update(status="cleared", cleared_elapsed_s=self.elapsed)
        self.emit("fault.cleared", fault)
        return dict(fault)

    def finish(self, status="completed", reason="duration_elapsed"):
        if not self.run_id:
            return
        for fault_id in self.faults:
            self.clear_fault(fault_id)
        for metric, detector in self.detectors.items():
            if detector.active:
                self.emit("followup.expired", {"metric": metric, "followup_of_episode_id": detector.opening_episode_id,
                          "reason": "run_ended_before_observed_recovery"})
        self.store.finish(self.run_id, status, {"reason": reason, "last_answer": self.latest_answer}, self.elapsed, self.boot_id)
        self.run_id = None
