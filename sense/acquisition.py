"""Adaptadores de los agentes físicos existentes, publicados por Rust mediante MQTT."""
from __future__ import annotations

import math

from .contracts import Observation, identifier

FIELDS = {
    "temperature": ("sht40", "temperature_c", "°C", -40, 125),
    "humidity": ("sht40", "humidity_percent", "%RH", 0, 100),
    "aqi": ("ens160", "aqi", "ENS160 AQI", 1, 5),
    "tvoc": ("ens160", "tvoc_ppb", "ppb", 0, 100000),
    "eco2": ("ens160", "eco2_ppm", "ppm equivalent", 0, 100000),
}


class EnvironmentAgent:
    @staticmethod
    def observe(payload: dict, received_at: str, region: str) -> dict[str, Observation]:
        env = payload.get("environment")
        env = env if isinstance(env, dict) else {}
        observations = {}
        for key, (sensor, field, unit, low, high) in FIELDS.items():
            source = env.get(sensor)
            value = source.get(field) if isinstance(source, dict) else None
            valid = type(value) in (float, int) and math.isfinite(value) and low <= value <= high
            if key == "aqi" and valid:
                valid = int(value) == value
            observations[key] = Observation(
                identifier(), "EnvironmentAgent", payload["timestamp"], received_at, region, value if valid else None,
                unit, "sensor_reported" if valid else "missing_or_invalid",
                "VALID" if valid else ("UNAVAILABLE" if value is None else "ERROR"),
                (("device_id", payload.get("device_id")), ("field", field)),
            )
        return observations


class PresenceAgent:
    @staticmethod
    def observe(payload: dict, received_at: str, region: str) -> Observation:
        source = payload.get("presence")
        code = source.get("state_code") if isinstance(source, dict) else None
        valid = type(code) is int and code in (0, 1, 2, 3)
        metadata = {"state_code": code}
        for field in ("motion_distance_cm", "static_distance_cm", "total_distance_cm", "motion_energy", "static_energy"):
            value = source.get(field) if isinstance(source, dict) else None
            metadata[field] = value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 65535 else None
        fields = ("motion_distance_cm",) if code == 1 else ("static_distance_cm",) if code == 2 else ("motion_distance_cm", "static_distance_cm") if code == 3 else ()
        usable = fields and all(metadata[field] is not None and metadata[field] > 0 for field in fields)
        selected = min(fields, key=lambda field: metadata[field]) if usable else None
        metadata["trigger_distance_cm"] = metadata[selected] if selected else None
        metadata["trigger_distance_source"] = selected
        return Observation(identifier(), "PresenceAgent", payload["timestamp"], received_at, region,
                           int(code != 0) if valid else None, "presence", "coverage_limited",
                           "VALID" if valid else ("UNAVAILABLE" if code is None else "ERROR"), tuple(metadata.items()))
