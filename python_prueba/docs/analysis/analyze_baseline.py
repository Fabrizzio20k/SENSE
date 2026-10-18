"""Análisis descriptivo offline; no modifica ni corrige tiempos del productor."""

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path


METRICS = {
    "temperature_c": ("environment", "sht40", "temperature_c"),
    "humidity_percent": ("environment", "sht40", "humidity_percent"),
    "tvoc_ppb": ("environment", "ens160", "tvoc_ppb"),
    "eco2_ppm": ("environment", "ens160", "eco2_ppm"),
}
LABELS = {0: "Sin presencia", 1: "Persona en movimiento",
          2: "Persona estática", 3: "Movimiento y presencia estática"}
RADAR_FIELDS = ("motion_distance_cm", "motion_energy", "static_distance_cm",
                "static_energy", "total_distance_cm")


def quantile(values, p):
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    lo, hi = math.floor(rank), math.ceil(rank)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def describe(values):
    return {"n": len(values), "min": min(values), "median": statistics.median(values),
            "mean": statistics.mean(values), "p95": quantile(values, .95),
            "p99": quantile(values, .99), "max": max(values),
            "population_stdev": statistics.pstdev(values)}


def value_at(record, path):
    for key in path:
        record = record[key]
    return record


def number(value, integer=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("valor numérico no finito o tipo inválido")
    if integer and type(value) is not int:
        raise ValueError("se requiere entero")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"clave JSON duplicada: {key}")
        result[key] = value
    return result


def validate(record):
    if record["schema"] != "rustio.iot.telemetry.v1" or record["device_id"] != "rpi5-01":
        raise ValueError("esquema/dispositivo fuera del alcance de este análisis")
    when = datetime.fromisoformat(record["timestamp"])
    if when.utcoffset() is None:
        raise ValueError("timestamp sin zona horaria")
    for path in METRICS.values():
        number(value_at(record, path))
    if not 0 <= record["environment"]["sht40"]["humidity_percent"] <= 100:
        raise ValueError("humedad fuera de [0,100]")
    number(record["environment"]["ens160"]["aqi"], integer=True)
    presence = record["presence"]
    number(presence["state_code"], integer=True)
    if LABELS.get(presence["state_code"]) != presence["state"]:
        raise ValueError("código/etiqueta radar no soportado o inconsistente")
    for key in RADAR_FIELDS:
        number(presence[key], integer=True)
        if presence[key] < 0:
            raise ValueError(f"radar negativo: {key}")
    return when


def read_records(raw, allow_truncated_tail=False):
    lines = raw.decode("utf-8").splitlines()
    records, rejected = [], []
    for line_number, line in enumerate(lines, 1):
        try:
            record = json.loads(line, object_pairs_hook=unique_object)
        except json.JSONDecodeError as error:
            # La excepción exige consentimiento explícito y solo cubre la última línea.
            if not (allow_truncated_tail and line_number == len(lines)):
                raise ValueError(f"JSON inválido en línea {line_number}: {error}") from error
            rejected.append({"line": line_number, "reason": str(error),
                             "treatment": "excluded_unparseable_tail_not_repaired"})
            continue
        try:
            when = validate(record)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"Contrato inválido en línea {line_number}: {error}") from error
        records.append((line_number, record, when))
    if len(records) < 2:
        raise ValueError("se necesitan al menos dos registros completos")
    return records, rejected


def analyze(raw, allow_truncated_tail=False):
    records, rejected = read_records(raw, allow_truncated_tail)
    intervals, transitions = [], []
    for previous, current in zip(records, records[1:]):
        delta = (current[2] - previous[2]).total_seconds()
        intervals.append({"previous_line": previous[0], "line": current[0],
                          "source_timestamp": current[1]["timestamp"], "interval_s": delta})
        before, after = previous[1]["presence"]["state_code"], current[1]["presence"]["state_code"]
        if before != after:
            transitions.append({"previous_line": previous[0], "line": current[0],
                                "source_timestamp": current[1]["timestamp"],
                                "from_code": before, "to_code": after,
                                "binary_presence_changed": (before != 0) != (after != 0)})
    periods = [row["interval_s"] for row in intervals]
    if min(periods) <= 0:
        raise ValueError("tiempos duplicados o decrecientes; no ordenar/corregir silenciosamente")
    metrics = {}
    for key, path in METRICS.items():
        values = [value_at(record, path) for _, record, _ in records]
        metrics[key] = {**describe(values), "first": values[0], "last": values[-1],
                        "endpoint_delta": values[-1] - values[0],
                        "absolute_adjacent_step": describe([abs(b-a) for a, b in zip(values, values[1:])])}
    states = [record["presence"]["state_code"] for _, record, _ in records]
    aqi = [record["environment"]["ens160"]["aqi"] for _, record, _ in records]
    segments, start = [], 0
    for end in range(1, len(records) + 1):
        if end < len(records) and (states[end] != 0) == (states[start] != 0):
            continue
        first, last = records[start], records[end-1]
        next_record = records[end] if end < len(records) else None
        segments.append({"first_line": first[0], "last_line": last[0],
                         "present": states[start] != 0, "sample_count": end-start,
                         "first_source_timestamp": first[1]["timestamp"],
                         "last_source_timestamp": last[1]["timestamp"],
                         "next_transition_timestamp": next_record[1]["timestamp"] if next_record else None,
                         "observed_span_s": (last[2]-first[2]).total_seconds(),
                         "held_until_next_s": ((next_record or last)[2]-first[2]).total_seconds(),
                         "right_censored": next_record is None})
        start = end
    summary = {
        "source_sha256": hashlib.sha256(raw).hexdigest(), "source_bytes": len(raw),
        "valid_records": len(records), "rejected_lines": rejected,
        "schema": records[0][1]["schema"], "device_id": records[0][1]["device_id"],
        "first_source_timestamp": records[0][1]["timestamp"],
        "last_source_timestamp": records[-1][1]["timestamp"],
        "duration_s": (records[-1][2]-records[0][2]).total_seconds(),
        "interval_s": describe(periods),
        "excess_over_assumed_2s_grid_s": sum(periods)-2*len(periods),
        "duplicate_timestamps": periods.count(0),
        "backwards_timestamps": sum(t < 0 for t in periods),
        "intervals_above_1_5_median": sum(t > 1.5*statistics.median(periods) for t in periods),
        "metrics": metrics, "state_counts": dict(sorted(Counter(states).items())),
        "state_labels": LABELS, "aqi_counts": dict(sorted(Counter(aqi).items())),
        "raw_state_changes": len(transitions),
        "binary_presence_changes": sum(t["binary_presence_changed"] for t in transitions),
        "absence_to_presence_changes": sum(t["from_code"] == 0 for t in transitions),
        "aqi_changes": sum(a != b for a, b in zip(aqi, aqi[1:])),
        "radar_field_changes": {key: sum(a[1]["presence"][key] != b[1]["presence"][key]
                                        for a, b in zip(records, records[1:])) for key in RADAR_FIELDS},
        "static_state_with_positive_motion_energy": sum(r["presence"]["state_code"] == 2
                                                         and r["presence"]["motion_energy"] > 0
                                                         for _, r, _ in records),
        "zero_total_distance_with_presence": sum(r["presence"]["state_code"] != 0
                                                 and r["presence"]["total_distance_cm"] == 0
                                                 for _, r, _ in records),
        "radar_ranges": {key: [min(r["presence"][key] for _, r, _ in records),
                                max(r["presence"][key] for _, r, _ in records)] for key in RADAR_FIELDS},
        "method": {"quantiles": "linear interpolation at (n-1)*p", "stdev": "population",
                   "timestamps": "source only, no receipt or per-sensor measurement time",
                   "segments": "observed labels; hold-last-value durations are not physical ground truth",
                   "large_gap_heuristic": "interval > 1.5 * median; does not prove delivery completeness"},
    }
    return summary, intervals, transitions, segments


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--allow-truncated-tail", action="store_true",
                        help="excluir un JSON no parseable solo en la última línea; dejar constancia")
    args = parser.parse_args()
    summary, intervals, transitions, segments = analyze(args.source.read_bytes(), args.allow_truncated_tail)
    if args.output.resolve() == args.source.resolve() or args.source.resolve().parent == args.output.resolve():
        parser.error("usar un directorio de resultados separado del original")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2,
                                                       allow_nan=False)+"\n", encoding="utf-8")
    write_csv(args.output / "intervals.csv", intervals, intervals[0].keys())
    write_csv(args.output / "state_transitions.csv", transitions,
              ["previous_line", "line", "source_timestamp", "from_code", "to_code", "binary_presence_changed"])
    write_csv(args.output / "presence_segments.csv", segments, segments[0].keys())
    print(json.dumps({"valid_records": summary["valid_records"], "rejected_lines": summary["rejected_lines"],
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
