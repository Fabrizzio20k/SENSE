"""Salud observada por evidencia y resultados reales, independiente del inyector."""
from __future__ import annotations

from .contracts import utc_now
from .context import timestamp
import time
from .faults import COMPONENTS, SENSOR_FIELDS


class HealthMonitor:
    def __init__(self, record, started, config):
        self.record, self.started, self.config = record, started, config
        self.components = {component: dict(status="UNKNOWN", reason="NO_EVIDENCE", since=utc_now()) for component in COMPONENTS}
        self.evidence_times = {}
        self.retry_after = {}

    def change(self, component, status, reason, now):
        previous = self.components[component]
        if previous["status"] == status and previous["reason"] == reason:
            return
        current = dict(status=status, reason=reason, since=utc_now())
        self.components[component] = current
        self.record("COMPONENT_HEALTH_CHANGED", dict(component=component, previous=previous["status"], **current, elapsed_s=now - self.started))

    def sensors(self, observations, now):
        for component, fields in SENSOR_FIELDS.items():
            ttl = self.config["sensors"]["presence_ttl_seconds" if component == "radar" else "environment_ttl_seconds"]
            readings = [observations.get(key, {}) for key in fields]
            statuses = [r.get("status", "UNKNOWN") for r in readings]
            if all(s == "VALID" for s in statuses):
                self.change(component, "HEALTHY", "FRESH_EVIDENCE", now)
                self.evidence_times[component] = min(r["received_monotonic"] for r in readings)
            elif "ERROR" in statuses:
                self.change(component, "FAILED", "INVALID_READING", now)
            elif "STALE" in statuses:
                self.change(component, "STALE", "EVIDENCE_EXPIRED", now)
            elif "UNAVAILABLE" in statuses or now - self.started >= ttl:
                self.change(component, "UNAVAILABLE", "NO_SENSOR_DATA", now)

    def task_event(self, event, now):
        component = "camera" if event.source_agent == "VisionAgent" else "gemma"
        if event.event_type in ("TASK_FAILED", "TASK_TIMEOUT"):
            self.change(component, "FAILED", event.event_type, now)
            self.retry_after[component] = now + (self.config["vision"]["cooldown_seconds"] if component == "camera" else min(self.config["interpretation"][k]["cooldown_seconds"] for k in ("textual", "multimodal")))
        elif event.event_type == "TASK_STARTED" and self.components[component]["status"] == "FAILED":
            self.change(component, "RECOVERING", "PROBE_RUNNING", now)
        elif event.event_type == "TASK_COMPLETED" and not event.payload.get("late"):
            self.change(component, "HEALTHY", "TASK_SUCCEEDED", now)
            captured_at = (event.payload.get("result") or {}).get("captured_at") if component == "camera" else event.payload.get("started_at")
            self.evidence_times[component] = now - max(0, time.time() - timestamp(captured_at)) if captured_at else now

    def available(self, component, now):
        return now >= self.retry_after.get(component, float("-inf"))

    @property
    def degraded(self):
        return any(v["status"] in ("STALE", "UNAVAILABLE", "FAILED", "RECOVERING") for v in self.components.values())
