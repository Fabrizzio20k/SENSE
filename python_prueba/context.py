"""Contrato real, contexto temporal y detectores del perfil exploratorio."""

import hashlib
import json
import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


MQTT_SOURCES = ("sht40", "ens160", "ld2410c")
SOURCES = (*MQTT_SOURCES, "camera", "slm")
LABELS = {0: "Sin presencia", 1: "Persona en movimiento", 2: "Persona estática",
          3: "Movimiento y presencia estática"}
FIELDS = {
    "sht40": {"temperature_c": "degC", "humidity_percent": "%RH"},
    "ens160": {"aqi": "index", "tvoc_ppb": "ppb", "eco2_ppm": "ppm_estimated"},
    "ld2410c": {"state_code": "code", "motion_distance_cm": "cm", "motion_energy": "radar_score",
                 "static_distance_cm": "cm", "static_energy": "radar_score", "total_distance_cm": "cm"},
}
PROFILE = {
    "id": "rules-pilot-v1", "status": "pilot_candidate", "variant": "rules-v1",
    "thinking": False, "telemetry_silence_s": 7, "presence_debounce_s": 2,
    "recent_window_s": 30, "baseline_window_s": 120,
    "min_recent_samples": 12, "min_baseline_samples": 48,
    "persistence_s": 10, "recovery_persistence_s": 20,
    "change_delta": {"temperature_c": .5, "humidity_percent": 3, "tvoc_ppb": 50, "eco2_ppm": 100},
    "recovery_delta": {"temperature_c": .25, "humidity_percent": 1.5, "tvoc_ppb": 25, "eco2_ppm": 50},
    "timing_basis_live": "receipt_monotonic_proxy", "measurement_freshness": "unknown",
    "allow_unverified_sensor_quality": True, "resource_sample_period_s": 1,
    "power_max_gap_s": 60, "crossmodal_max_skew_s": None,
    "camera_enabled": False, "slm_enabled": False,
}

ACQUISITION_PROFILE = {
    "status": "pilot_candidate", "periodic_vision_interval_s": 30, "visual_count_ttl_s": 30,
    "vision_cooldown_s": 5, "vision_timeout_s": 90, "slm_timeout_s": 120, "episode_deadline_s": 240,
    "max_visual_calls_per_episode": 1, "max_slm_calls_per_episode": 1, "heavy_action_concurrency": 1,
    "heavy_queue_capacity": 8, "max_followups": 2, "followup_interval_s": 30,
    "slm_max_completion_tokens": 384, "max_followup_lifetime_s": 180,
    "reserve_memory_bytes": 512*1024**2, "max_cpu_temperature_c": 80,
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def finite_number(value, integer=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("se requiere número finito; booleanos no admitidos")
    if integer and type(value) is not int:
        raise ValueError("se requiere entero")
    return value


def aware_time(value):
    if not isinstance(value, str):
        raise ValueError("timestamp debe ser texto ISO 8601")
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("timestamp sin zona horaria")
    return result


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"clave JSON duplicada: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"constante JSON no finita: {value}")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("número JSON fuera del rango finito")
    return result


def decode_json(raw):
    return json.loads(raw, object_pairs_hook=_object, parse_constant=_invalid_constant, parse_float=_finite_float)


def parse_message(raw):
    if len(raw) > 16384:
        raise ValueError("payload excede 16384 bytes")
    try:
        result = decode_json(raw)
        if result["schema"] != "rustio.iot.telemetry.v1" or result["device_id"] != "rpi5-01":
            raise ValueError("esquema o dispositivo no soportado")
        aware_time(result["timestamp"])
    except (KeyError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("sobre MQTT inválido") from error
    return result


def source_values(message, source):
    try:
        block = message["presence"] if source == "ld2410c" else message["environment"][source]
        values = {name: finite_number(block[name], integer=source != "sht40") for name in FIELDS[source]}
        if source == "sht40" and not 0 <= values["humidity_percent"] <= 100:
            raise ValueError("humedad fuera de [0,100]")
        if source != "sht40" and any(value < 0 for value in values.values()):
            raise ValueError("valor negativo no soportado")
        if source == "ens160" and values["aqi"] not in range(1, 6):
            raise ValueError("AQI fuera de 1..5")
        if source == "ld2410c":
            if LABELS.get(values["state_code"]) != block["state"]:
                raise ValueError("código/etiqueta radar desconocido o inconsistente")
            if max(values["motion_energy"], values["static_energy"]) > 100:
                raise ValueError("score radar fuera de [0,100]")
        return values
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError(f"bloque {source} inválido") from error


@dataclass
class Source:
    latest: dict | None = None
    status: str = "never_observed"
    fault_id: str | None = None
    fault_mode: str | None = None
    availability_version: int = 0
    history: deque = field(default_factory=deque)
    history_started: float | None = None
    evidence_history: deque = field(default_factory=lambda: deque(maxlen=512))

    @property
    def usable(self):
        return self.status == "recent_receipt" and self.latest is not None

    def reset_history(self):
        self.history.clear()
        self.history_started = None

    def accept(self, values, timestamp, received_at, elapsed, receipt_elapsed):
        if self.latest and elapsed - self.latest["elapsed_s"] >= PROFILE["telemetry_silence_s"]:
            self.reset_history()
        overflow = len(self.history) >= 4096
        if overflow:
            self.reset_history()
        if self.history_started is None:
            self.history_started = elapsed
        self.history.append((elapsed, values))
        span = PROFILE["recent_window_s"]+PROFILE["baseline_window_s"]
        while self.history and self.history[0][0] < elapsed-span:
            self.history.popleft()
        self.latest = {"observation_id": str(uuid4()), "values": values,
                       "source_timestamp": timestamp, "received_at": received_at,
                       "elapsed_s": elapsed, "received_elapsed_s": receipt_elapsed,
                       "quality_flags": ["sensor_quality_unverified", "source_timestamp_semantics_unknown"]}
        self.latest["availability_version"] = self.availability_version
        self.evidence_history.append(self.latest)
        self.status = "recent_receipt"
        return overflow

    def snapshot(self, elapsed):
        return {"status": self.status, "usable_for_reported_values": self.usable,
                "measurement_freshness": "unknown", "availability_version": self.availability_version,
                "fault_id": self.fault_id, "fault_mode": self.fault_mode,
                "receipt_age_s": max(0, elapsed-self.latest["elapsed_s"]) if self.latest else None,
                "latest": self.latest}


@dataclass
class ChangeDetector:
    reference: float | None = None
    since: float | None = None
    active: bool = False
    recovery_since: float | None = None
    opening_episode_id: str | None = None

    def interrupt(self):
        self.since = self.recovery_since = None
        if not self.active:
            self.reference = None

    def evaluate(self, metric, source, elapsed):
        recent_span = PROFILE["recent_window_s"]
        total_span = recent_span+PROFILE["baseline_window_s"]
        if source.history_started is None or elapsed-source.history_started < total_span:
            return None
        recent = [v[metric] for t, v in source.history if elapsed-recent_span < t <= elapsed]
        baseline = [v[metric] for t, v in source.history if elapsed-total_span < t <= elapsed-recent_span]
        if len(recent) < PROFILE["min_recent_samples"] or len(baseline) < PROFILE["min_baseline_samples"]:
            self.interrupt()
            return None
        current = statistics.median(recent)
        reference = self.reference if self.reference is not None else statistics.median(baseline)
        delta = current-reference
        details = {"metric": metric, "reference": reference, "recent_median": current,
                   "delta": delta, "unit": next(fields[metric] for fields in FIELDS.values() if metric in fields),
                   "quality": "unverified_exploratory", "recent_samples": len(recent),
                   "baseline_samples": len(baseline)}
        if not self.active:
            if abs(delta) < PROFILE["change_delta"][metric]:
                self.interrupt()
                return None
            if self.since is None:
                self.since, self.reference = elapsed, reference
            if elapsed-self.since >= PROFILE["persistence_s"]:
                self.active = True
                return {"kind": "environment_change_persistent", **details}
        elif abs(delta) <= PROFILE["recovery_delta"][metric]:
            if self.recovery_since is None:
                self.recovery_since = elapsed
            if elapsed-self.recovery_since >= PROFILE["recovery_persistence_s"]:
                followup = self.opening_episode_id
                self.active = False
                self.opening_episode_id = None
                self.interrupt()
                return {"kind": "environment_recovered", "followup_of_episode_id": followup, **details}
        else:
            self.recovery_since = None
        return None


@dataclass
class Presence:
    stable: bool | None = None
    candidate: bool | None = None
    since: float | None = None

    def reset(self):
        self.stable = self.candidate = self.since = None

    def evaluate(self, state_code, elapsed):
        present = state_code in (1, 2, 3)
        if present != self.candidate:
            self.candidate, self.since = present, elapsed
        if elapsed-self.since < PROFILE["presence_debounce_s"] or present == self.stable:
            return None
        old, self.stable = self.stable, present
        return {"kind": "presence_initialized" if old is None else "presence_changed",
                "previous": old, "present": present, "state_code": state_code,
                "transition": "initial" if old is None else ("entry" if present else "exit")}
