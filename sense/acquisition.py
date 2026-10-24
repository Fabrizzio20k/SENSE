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
        return Observation(identifier(), "PresenceAgent", payload["timestamp"], received_at, region,
                           int(code != 0) if valid else None, "presence", "coverage_limited",
                           "VALID" if valid else ("UNAVAILABLE" if code is None else "ERROR"), (("state_code", code),))
