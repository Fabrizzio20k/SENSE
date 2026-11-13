"""Lectura sin inferir ceros/booleanos y escritura de derivados reproducibles."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path

TABLES = ("events", "observations", "inference_tasks", "images", "question_results",
          "faults", "observer_requests", "ground_truth", "power_readings", "samples_1s")
IDENTITY = ("run_id", "scenario", "mode", "repetition", "folder")


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def boolean(value):
    if value is True or value == "True":
        return True
    if value is False or value == "False":
        return False
    return None


def timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, OverflowError, OSError):
        return None


def decode(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    return json.loads(value)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def csv_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"Cabecera ausente o duplicada: {path}")
        for row_index, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Fila CSV incompleta: {path}:{row_index}")
            yield row


def read_csv(path):
    return list(csv_rows(path))


def write_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def write_json(path, content):
    write_text(path, json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_csv(path, rows, fields=None):
    rows = list(rows)
    if fields is None:
        fields = list(dict.fromkeys(key for row in rows for key in row))
    fields = fields or ["sin_registros"]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: (json.dumps(value, ensure_ascii=False, allow_nan=False)
                                  if isinstance(value, (list, dict)) else value)
                             for key, value in row.items()})
    os.replace(temporary, path)


def tagged(identity, row):
    return {**identity, **row}


def safe_image(folder, image_id):
    if not image_id or not all(c.isalnum() or c in "-_" for c in image_id):
        return None
    candidate = (folder / "images" / f"{image_id}.jpg").resolve()
    return candidate if candidate.is_relative_to(folder.resolve()) else None


def stats(values):
    import pandas as pd
    values = [value for item in values if (value := number(item)) is not None]
    if not values:
        return {"n": 0, "median": None, "p95": None, "min": None, "max": None, "mean": None}
    series = pd.Series(values, dtype=float)
    return {"n": len(values), "median": float(series.median()),
            "p95": float(series.quantile(.95)), "min": min(values), "max": max(values),
            "mean": float(series.mean())}
