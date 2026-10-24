from __future__ import annotations

import json
from collections import deque
from datetime import datetime

from .contracts import Observation, Snapshot, identifier, utc_now
from .acquisition import FIELDS


def timestamp(value: str) -> float:
    if not isinstance(value, str):
        raise ValueError("Timestamp ausente o inválido.")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("El timestamp debe incluir zona horaria.")
    return date.timestamp()


class EnvironmentEvaluator:
    """Episodios con referencia congelada hasta recuperar; baseline de sesión intacta."""

    def __init__(self, config: dict):
        self.config = config
        self.history = {key: deque(maxlen=config["history_capacity"]) for key in FIELDS}
        self.baseline = {}
        self.conditions = {key: {"state": "NORMAL", "count": 0, "recovery": 0, "reference": None,
                                 "armed": False, "rearmed_epoch_s": None, "evaluable": False} for key in ("temperature", "humidity", "aqi", "eco2")}
        self.events = deque(maxlen=config["history_capacity"])
        self.last_update = None

    def update(self, observations: dict, captured: float) -> list[dict]:
        emitted = []
        if self.last_update is not None and captured - self.last_update > self.config["max_confirmation_gap_seconds"]:
            for condition in self.conditions.values():
                condition["count"] = condition["recovery"] = 0
                if condition["state"] == "CANDIDATE":
                    condition.update(state="NORMAL", reference=None)
                elif condition["state"] == "RECOVERING":
                    condition["state"] = "ACTIVE"
        self.last_update = captured
        codes = {"temperature": "TEMP_RISE", "humidity": "HUMIDITY_RISE", "aqi": "AQI_WORSENED", "eco2": "ECO2_THRESHOLD_CROSSED"}
        thresholds = {"temperature": "temperature_rise_c", "humidity": "humidity_rise_pp", "aqi": "aqi_increase_levels"}
        rearms = {"temperature": "temperature_rearm_c", "humidity": "humidity_rearm_pp", "aqi": "aqi_rearm_levels"}
        for key, observation in observations.items():
            history = self.history[key]
            if observation.status == "VALID":
                sample = {"captured_epoch_s": captured, "id": observation.observation_id, "value": observation.value}
                history.append(sample)
                self.baseline.setdefault(key, sample)
            if key not in self.conditions:
                continue
            condition = self.conditions[key]
            if observation.status != "VALID":
                condition["evaluable"] = False
                condition["count"] = condition["recovery"] = 0
                if condition["state"] == "CANDIDATE":
                    condition.update(state="NORMAL", reference=None)
                elif condition["state"] == "RECOVERING":
                    condition["state"] = "ACTIVE"
                continue
            value = observation.value
            if key == "eco2":
                condition["evaluable"] = True
                if condition["state"] == "NORMAL" and value < self.config["eco2_threshold_ppm_equiv"]:
                    condition["armed"] = True
                active = condition["armed"] and value >= self.config["eco2_threshold_ppm_equiv"]
                recovering = value <= self.config["eco2_rearm_threshold"]
                reference = condition["reference"] or (history[-2] if len(history) > 1 else sample)
                magnitude = value - self.config["eco2_threshold_ppm_equiv"]
            else:
                target = captured - self.config["window_seconds"]
                candidates = [s for s in history if abs(s["captured_epoch_s"] - target) <= self.config["reference_tolerance_seconds"]
                              and (condition["rearmed_epoch_s"] is None or s["captured_epoch_s"] >= condition["rearmed_epoch_s"])]
                reference = condition["reference"] or (min(candidates, key=lambda s: abs(s["captured_epoch_s"] - target)) if candidates else None)
                if reference is None or reference["id"] == observation.observation_id:
                    condition["evaluable"] = False
                    condition["count"] = 0
                    continue
                condition["evaluable"] = True
                magnitude = value - reference["value"]
                active = magnitude >= self.config[thresholds[key]]
                recovering = magnitude <= self.config[rearms[key]]
            state = condition["state"]
            if state in ("NORMAL", "CANDIDATE"):
                if not active:
                    condition.update(state="NORMAL", count=0, reference=None)
                    continue
                condition["reference"] = reference
                condition["state"] = "CANDIDATE"
                condition["count"] += 1
                if condition["count"] >= self.config["confirmation_samples"]:
                    condition["state"] = "ACTIVE"
                    event = {"event_id": identifier(), "event_type": codes[key], "field": key,
                             "captured_at": observation.captured_at, "magnitude": magnitude,
                             "reference": reference, "evidence_ids": [s["id"] for s in list(history)[-condition["count"]:]],
                             "observation_id": observation.observation_id}
                    self.events.append(event)
                    emitted.append(event)
            elif recovering:
                condition["state"] = "RECOVERING"
                condition["recovery"] += 1
                if condition["recovery"] >= self.config["confirmation_samples"]:
                    condition.update(state="NORMAL", count=0, recovery=0, reference=None,
                                     rearmed_epoch_s=captured, armed=True)
            else:
                condition.update(state="ACTIVE", recovery=0)
        return emitted


class ContextStore:
    def __init__(self, config: dict):
        self.config = config
        self.observations: dict[str, Observation] = {}
        self.received_monotonic = {}
        self.age_on_receipt = {}
        self.last_sensor_timestamp = None
        self.environment = EnvironmentEvaluator(config["environment"])
        self.presence_candidate = None
        self.presence_samples = 0
        self.confirmed_presence = None
        self.conflict = False

    def ingest(self, updated: dict[str, Observation], radar: Observation, now: float, wall: float) -> list[dict]:
        captured = timestamp(radar.captured_at)
        if captured > wall + self.config["sensors"]["max_future_skew_seconds"]:
            raise ValueError("Timestamp MQTT en el futuro; compruebe sincronización de relojes.")
        if self.last_sensor_timestamp is not None and captured <= self.last_sensor_timestamp:
            raise ValueError("Telemetría duplicada o fuera de orden.")
        if self.last_sensor_timestamp is not None and captured - self.last_sensor_timestamp > self.config["environment"]["max_confirmation_gap_seconds"]:
            self.presence_samples = 0
        self.last_sensor_timestamp = captured
        for key, observation in updated.items():
            self.put(key, observation, now, max(0, wall - captured))
        self.put("presence", radar, now, max(0, wall - captured))
        events = self.environment.update(updated, captured) if wall - captured <= self.config["sensors"]["environment_ttl_seconds"] else []
        if not events and wall - captured > self.config["sensors"]["environment_ttl_seconds"]:
            for condition in self.environment.conditions.values():
                condition["count"] = condition["recovery"] = 0
        if radar.status == "VALID" and wall - captured <= self.config["sensors"]["presence_ttl_seconds"]:
            if radar.value == self.presence_candidate:
                self.presence_samples += 1
            else:
                self.presence_candidate, self.presence_samples = radar.value, 1
            if self.presence_samples >= self.config["modes"]["reactive_debounce_samples"]:
                previous = self.confirmed_presence
                self.confirmed_presence = radar.value
                if previous is not None and previous != radar.value:
                    events.append({"event_id": identifier(), "event_type": "PRESENCE_CHANGED", "previous": previous,
                                   "value": radar.value, "evidence_ids": [radar.observation_id], "captured_at": radar.captured_at})
        else:
            self.presence_samples = 0
        return events

    def put(self, key: str, observation: Observation, now: float, age: float = 0) -> None:
        self.observations[key] = observation
        self.received_monotonic[key] = now
        self.age_on_receipt[key] = age

    def snapshot(self, now: float) -> Snapshot:
        observations = {}
        for key, observation in self.observations.items():
            document = observation.document()
            ttl = (self.config["vision"]["ttl_seconds"] if key == "count" else self.config["sensors"]["presence_ttl_seconds"]
                   if key == "presence" else self.config["sensors"]["environment_ttl_seconds"])
            age = max(0, now - self.received_monotonic[key] + self.age_on_receipt[key])
            document["age_seconds"] = round(age, 2)
            if document["status"] == "VALID" and age >= ttl:
                document["status"] = "STALE"
            observations[key] = document
        radar, count = observations.get("presence", {}), observations.get("count", {})
        self.conflict = bool(self.config["regions"]["radar_camera_comparable"] and radar.get("status") == count.get("status") == "VALID"
                             and abs(timestamp(radar["captured_at"]) - timestamp(count["captured_at"])) <= self.config["regions"]["comparison_max_skew_seconds"]
                             and bool(radar["value"]) != bool(count["value"]))
        if self.conflict:
            radar["status"] = count["status"] = "CONFLICTING"
        snapshot_id = identifier()
        created = utc_now()
        document = {"schema": "sense.v1", "snapshot_id": snapshot_id, "created_at": created,
                    "observations": observations, "environment_events": list(self.environment.events),
                    "environment_conditions": self.environment.conditions, "session_baseline": self.environment.baseline,
                    "conflict": self.conflict, "physical_state": "NOT_DIRECTLY_OBSERVABLE"}
        return Snapshot(snapshot_id, created, json.dumps(document, allow_nan=False))
