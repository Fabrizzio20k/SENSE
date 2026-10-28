"""Fallas por software y su trazabilidad; sus banderas no alimentan las reglas."""
from __future__ import annotations

from .contracts import identifier, utc_now

SENSOR_FIELDS = {"sht40": ("temperature", "humidity"), "ens160": ("aqi", "tvoc", "eco2"), "radar": ("presence",)}
COMPONENTS = (*SENSOR_FIELDS, "camera", "gemma")


class FaultInjector:
    def __init__(self, record, started: float):
        self.record, self.started = record, started
        self.records = {}
        self.disabled = {}
        self.timeouts = {}

    def emit(self, kind, fault, now):
        self.record(kind, {k: v for k, v in fault.items() if not k.endswith("_monotonic")} | {"event_id": identifier(), "elapsed_s": round(now - self.started, 3)})

    def begin(self, component, kind, now, baseline_status="UNKNOWN"):
        fault = dict(fault_id=identifier(), component=component, kind=kind, simulated=True,
                     activated_at=utc_now(), activated_elapsed_s=now - self.started, activated_monotonic=now,
                     detected_at=None, restored_at=None, recovered_at=None, task_id=None,
                     baseline_status=baseline_status, preexisting_failure=baseline_status in ("FAILED", "STALE", "UNAVAILABLE"))
        self.emit("FAULT_INJECTED", fault, now)
        self.records[fault["fault_id"]] = fault
        return fault

    def set_enabled(self, component, enabled, now, baseline_status="UNKNOWN"):
        if component not in (*SENSOR_FIELDS, "camera") or type(enabled) is not bool:
            raise ValueError("Selecciona sht40, ens160, radar o camera y enabled booleano.")
        if enabled:
            fault = self.disabled.pop(component, None)
            if fault:
                fault.update(restored_at=utc_now(), restored_elapsed_s=now - self.started, restored_monotonic=now)
                self.emit("FAULT_RESTORED", fault, now)
        elif component not in self.disabled:
            self.disabled[component] = self.begin(component, "CAMERA_UNAVAILABLE" if component == "camera" else "DATA_LOSS", now, baseline_status)

    def arm_timeout(self, lane, now, baseline_status="UNKNOWN"):
        if lane not in ("vision", "gemma"):
            raise ValueError("Selecciona vision o gemma para provocar timeout.")
        if lane in self.timeouts:
            raise ValueError("Ya hay un timeout armado o en curso para ese worker.")
        self.timeouts[lane] = self.begin("camera" if lane == "vision" else "gemma", "TIMEOUT", now, baseline_status)

    def task_fault(self, lane):
        if lane == "vision" and "camera" in self.disabled:
            return self.disabled["camera"]
        fault = self.timeouts.get(lane)
        return fault if fault and fault["task_id"] is None else None

    def accepted(self, fault, command, now):
        if fault:
            fault["task_id"] = command.command_id
            fault.update(applied_at=utc_now(), applied_monotonic=now)
            self.emit("FAULT_APPLIED", fault, now)

    def observe(self, health, now, evidence_times):
        for fault in self.records.values():
            if fault["recovered_at"] or fault.get("not_executed_reason"):
                continue
            component = fault["component"]
            if fault["kind"] == "DATA_LOSS" and not fault["detected_at"] and health[component]["status"] in ("STALE", "UNAVAILABLE", "FAILED"):
                fault.update(detected_at=utc_now(), detection_latency_s=None if fault["preexisting_failure"] else max(0, now - fault["activated_monotonic"]))
                self.emit("FAULT_DETECTED", fault, now)
            if fault["restored_at"] and not fault["recovered_at"] and health[component]["status"] == "HEALTHY" and evidence_times.get(component, float("-inf")) > fault["restored_monotonic"]:
                fault.update(recovered_at=utc_now(), recovery_latency_s=now - fault["restored_monotonic"])
                self.emit("FAULT_RECOVERED", fault, now)

    def task_event(self, event, now):
        fault_id = event.payload["command"]["parameters"].get("fault_id")
        fault = self.records.get(fault_id)
        if not fault:
            return
        if event.event_type == "TASK_STARTED":
            fault.update(task_started_at=event.payload["started_at"],
                         task_started_monotonic=fault["applied_monotonic"] + event.payload["queue_seconds"])
            self.emit("FAULT_TASK_STARTED", fault, now)
        if fault["kind"] == "TIMEOUT" and event.event_type == "TASK_TIMEOUT" and event.payload.get("reason"):
            fault.update(restored_at=utc_now(), restored_elapsed_s=now - self.started, restored_monotonic=now,
                         not_executed_reason=event.payload["reason"])
            self.emit("FAULT_NOT_EXECUTED", fault, now)
            self.timeouts = {lane: f for lane, f in self.timeouts.items() if f is not fault}
            return
        if event.event_type == "TASK_TIMEOUT" or event.event_type == "TASK_FAILED" and fault["kind"] == "CAMERA_UNAVAILABLE":
            if not fault["detected_at"]:
                since = fault.get("task_started_monotonic", fault["activated_monotonic"]) if fault["kind"] == "TIMEOUT" else fault["activated_monotonic"]
                fault.update(detected_at=utc_now(), detection_latency_s=None if fault["preexisting_failure"] else now - since)
                self.emit("FAULT_DETECTED", fault, now)
        if fault["kind"] == "TIMEOUT" and event.event_type == "TASK_FAILED":
            fault.update(restored_at=utc_now(), restored_elapsed_s=now - self.started, restored_monotonic=now)
            self.emit("FAULT_RESTORED", fault, now)
            self.timeouts = {lane: f for lane, f in self.timeouts.items() if f is not fault}

    def finish(self, now):
        for fault in self.records.values():
            if not fault["recovered_at"] and not fault.get("not_executed_reason"):
                self.emit("FAULT_RUN_ENDED", fault, now)
        self.disabled.clear()
        self.timeouts.clear()

    def view(self):
        return dict(disabled=list(self.disabled), timeouts={lane: "ARMED" if f["task_id"] is None else "RUNNING" if f.get("task_started_at") else "QUEUED" for lane, f in self.timeouts.items()},
                    faults=[{k: v for k, v in f.items() if not k.endswith("_monotonic")} for f in self.records.values()])
