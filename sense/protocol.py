"""Protocolo de observación externo; nunca alimenta las políticas de inferencia."""
from __future__ import annotations

import math
import time

from .context import timestamp

CHECKPOINTS = {"S1": (600, 900), "S2": (300, 600, 900, 1200, 1500), "S3": (600, 1200)}
PROTOCOL_VERSION = "sense-observer-1"


def validate_observation(payload: dict, fields: list[str]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("La observación debe ser un objeto.")
    if timestamp(payload.get("observed_at")) > time.time() + 5:
        raise ValueError("La hora observada no puede estar en el futuro.")
    for key in ("power_observed_at", "people_observed_at"):
        if key in payload and timestamp(payload[key]) > time.time() + 5:
            raise ValueError("La hora de lectura no puede estar en el futuro.")
    unavailable = payload.get("unavailable_fields", [])
    if not isinstance(unavailable, list) or any(f not in fields for f in unavailable) or len(set(unavailable)) != len(unavailable):
        raise ValueError("Campos no observados inválidos.")
    if unavailable and (not isinstance(payload.get("missing_reason"), str) or not payload["missing_reason"].strip()):
        raise ValueError("Explica por qué no pudiste observar los campos pendientes.")
    repeated = payload.get("repeated_fields", [])
    if (not isinstance(repeated, list) or any(f not in fields or f not in ("power_w", "visible_people") or f in unavailable for f in repeated)
            or len(set(repeated)) != len(repeated)):
        raise ValueError("Campos repetidos inválidos.")
    for field in fields:
        value = payload.get(field)
        if field in unavailable:
            if value is not None:
                raise ValueError("Un campo no observado debe quedar vacío.")
            continue
        if field == "power_w" and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError("Registra una potencia W finita y no negativa.")
        if field == "visible_people" and (type(value) is not int or value < 0):
            raise ValueError("Registra personas como entero no negativo.")
        if field == "action" and (not isinstance(value, str) or not value.strip()):
            raise ValueError("Describe la acción realmente realizada.")
    if "visible_people" in fields and (not isinstance(payload.get("region"), str) or not payload["region"].strip()):
        raise ValueError("Indica la región observada.")
    for key in ("region", "notes", "missing_reason", "action", "observer", "instrument", "equipment"):
        if key in payload and (not isinstance(payload[key], str) or len(payload[key]) > 2000):
            raise ValueError(f"{key}: texto de hasta 2000 caracteres.")


def validate_guided_start(body: dict) -> None:
    if type(body.get("guided", False)) is not bool:
        raise ValueError("guided debe ser booleano.")
    if not body.get("guided"):
        return
    if body.get("scenario_id") not in CHECKPOINTS or type(body.get("repetition")) is not int or not 1 <= body["repetition"] <= 3:
        raise ValueError("Selecciona escenario S1–S3 y repetición 1–3.")
    initial = body.get("initial_observation")
    validate_observation(initial, ["power_w", "visible_people"])
    for key in ("observer", "instrument", "equipment"):
        if not initial.get(key, "").strip():
            raise ValueError("Completa observador, vatímetro y equipos medidos.")
