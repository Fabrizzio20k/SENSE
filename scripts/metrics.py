"""Cálculos descriptivos; ninguna muestra por segundo se considera una réplica."""
from collections import Counter, defaultdict
import math

from common import boolean, decode, number, stats, timestamp


def power_analysis(rows, start, end, max_gap, corrections=None):
    points, quality = [], []
    for row in rows:
        t = timestamp(row.get("power_observed_at"))
        value = number(row.get("power_w"))
        correction = (corrections or {}).get(row.get("record_id"))
        if correction:
            corrected = number(correction["corrected_w"])
            if value != number(correction["original_w"]) or corrected is None or corrected < 0:
                raise ValueError(f"Corrección de potencia incompatible: {row.get('record_id')}")
            value = corrected
        reason = "VALID"
        if row.get("kind") == "EXTERNAL_ENERGY":
            reason = "ENERGY_IS_NOT_POWER"
        elif "power_w" in decode(row.get("unavailable_fields"), []):
            reason = "UNAVAILABLE"
        elif t is None:
            reason = "NO_POWER_OBSERVATION_TIME"
        elif value is None or value < 0:
            reason = "INVALID_POWER"
        elif not row.get("scope") or not row.get("equipment") or not row.get("instrument"):
            reason = "UNKNOWN_ELECTRICAL_BOUNDARY"
        entry = {**row, "analysis_power_w": value, "power_correction_applied": bool(correction),
                 "analysis_status": reason, "observed_epoch": t,
                 "reconfirmed_repeated": "power_w" in decode(row.get("repeated_fields"), [])}
        quality.append(entry)
        if reason == "VALID":
            points.append((t, value, (row["scope"], row["equipment"], row["instrument"]), row["record_id"]))
    by_time = defaultdict(list)
    for point in points:
        by_time[point[0]].append(point)
    unique = []
    for t, group in sorted(by_time.items()):
        if len({(point[1], point[2]) for point in group}) > 1:
            for entry in quality:
                if entry["observed_epoch"] == t and entry["analysis_status"] == "VALID":
                    entry["analysis_status"] = "CONFLICTING_TIMESTAMP"
        else:
            unique.append(group[0])
            for duplicate in group[1:]:
                for entry in quality:
                    if entry["record_id"] == duplicate[3]:
                        entry["analysis_status"] = "DUPLICATE_TIMESTAMP"
    segments = []
    conflicts = {entry["observed_epoch"] for entry in quality if entry["analysis_status"] == "CONFLICTING_TIMESTAMP"}
    for a, b in zip(unique, unique[1:]):
        if b[0] - a[0] > max_gap or a[2] != b[2] or any(a[0] < t < b[0] for t in conflicts):
            continue
        left, right = max(start, a[0]), min(end, b[0])
        if right <= left:
            continue
        slope = (b[1] - a[1]) / (b[0] - a[0])
        pa, pb = a[1] + slope * (left - a[0]), a[1] + slope * (right - a[0])
        segments.append({"from_epoch": left, "to_epoch": right, "from_record_id": a[3],
                         "to_record_id": b[3], "from_w": pa, "to_w": pb,
                         "seconds": right - left, "estimated_wh": (pa + pb) / 2 * (right - left) / 3600,
                         "scope": a[2][0], "equipment": a[2][1], "instrument": a[2][2]})
    covered = sum(s["seconds"] for s in segments)
    energy = sum(s["estimated_wh"] for s in segments) if segments else None
    summary = {"power_records": len(rows), "power_valid_unique": len(unique),
               "power_corrections_applied": sum(q["power_correction_applied"] for q in quality),
               "power_repeated": sum(q["reconfirmed_repeated"] for q in quality),
               "power_conflicting_timestamps": len(conflicts), "power_max_gap_s": max_gap,
               "power_covered_s": covered, "power_coverage_fraction": covered / (end-start),
               "energy_estimated_wh_covered": energy,
               "power_time_weighted_w_covered": energy * 3600 / covered if covered else None,
               "power_uncovered_s": end-start-covered}
    return summary, quality, segments


def count_pairs(ground_truth, tasks, config, start, end):
    candidates, by_id = [], {}
    for task in tasks:
        result = decode(task.get("result_json"), {})
        if (task.get("action") != "vision" or task.get("status") != "TASK_COMPLETED"
                or boolean(task.get("simulated")) is not False or boolean(task.get("model_executed")) is False):
            continue
        captured = timestamp(result.get("captured_at"))
        count = number(result.get("count"))
        if captured is not None and count is not None and count >= 0 and count.is_integer():
            candidate = {"task_id": task["task_id"], "image_id": result.get("image_id"),
                         "count": count, "time": captured, "region": result.get("region")}
            candidates.append(candidate)
            by_id[task["task_id"]] = candidate
    skew = number(config.get("regions", {}).get("comparison_max_skew_seconds"))
    skew = 3. if skew is None else skew
    results = []
    for row in ground_truth:
        observed = timestamp(row.get("people_observed_at"))
        value = number(row.get("visible_people"))
        output = {"record_id": row["record_id"], "human_task_id": row.get("task_id"),
                  "human_count": value, "human_time": row.get("people_observed_at"),
                  "human_region": row.get("region"), "notes": row.get("notes"),
                  "tolerance_s": skew, "pair_status": "NO_COMPARABLE_CAPTURE",
                  "reconfirmed_repeated": "visible_people" in decode(row.get("repeated_fields"), [])}
        linked = row.get("task_id", "")
        if "visible_people" in decode(row.get("unavailable_fields"), []):
            output["pair_status"] = "UNAVAILABLE"
        elif not row.get("visible_people"):
            output["pair_status"] = "NO_COUNT_FIELD"
        elif value is None or value < 0 or not value.is_integer():
            output["pair_status"] = "INVALID_HUMAN_COUNT"
        elif observed is None:
            output["pair_status"] = "NO_PEOPLE_OBSERVATION_TIME"
        elif not linked and not start <= observed <= end:
            output["pair_status"] = "OUTSIDE_RUN"
        else:
            choices = ([by_id[linked]] if linked in by_id else []) if linked else candidates
            if choices:
                chosen = min(choices, key=lambda c: abs(c["time"]-observed))
                delta = observed-chosen["time"]
                output.update({"task_id": chosen["task_id"], "image_id": chosen["image_id"],
                               "predicted_count": chosen["count"], "delta_s": delta,
                               "capture_epoch": chosen["time"], "camera_region": chosen["region"],
                               "link_method": "task_id" if linked else "nearest_capture",
                               "recording_delay_s": timestamp(row.get("recorded_at"))-chosen["time"]
                               if timestamp(row.get("recorded_at")) is not None else None})
                if chosen["region"] != row.get("region") or not chosen["region"]:
                    output["pair_status"] = "REGION_MISMATCH"
                elif not start <= chosen["time"] <= end:
                    output["pair_status"] = "CAPTURE_OUTSIDE_RUN"
                elif not linked and abs(delta) > skew:
                    output["pair_status"] = "TIME_SKEW"
                else:
                    # Task-linked counts refer to that captured scene; observers confirmed typing delays.
                    output.update(pair_status="PAIRED", error=chosen["count"]-value,
                                  absolute_error=abs(chosen["count"]-value))
        results.append(output)
    used = set()
    for row in sorted((r for r in results if r["pair_status"] == "PAIRED"),
                      key=lambda r: (r["link_method"] != "task_id", abs(r["delta_s"]))):
        if row["task_id"] in used:
            row["pair_status"] = "DUPLICATE_CAPTURE_REFERENCE"
            row.pop("error", None)
            row.pop("absolute_error", None)
        used.add(row["task_id"])
    paired = [r for r in results if r["pair_status"] == "PAIRED"]
    errors = [r["error"] for r in paired]
    summary = {"count_reference_records": len(results),
               "count_explicit_records": sum(r["human_count"] is not None for r in results),
               "count_pairs_n": len(paired),
               "count_pairs_task_linked": sum(r["link_method"] == "task_id" for r in paired),
               "count_pairs_within_time_tolerance": sum(abs(r["delta_s"]) <= skew for r in paired),
               "count_mae": sum(map(abs, errors))/len(errors) if errors else None,
               "count_rmse": math.sqrt(sum(e*e for e in errors)/len(errors)) if errors else None,
               "count_bias": sum(errors)/len(errors) if errors else None,
               "count_exact_fraction": sum(e == 0 for e in errors)/len(errors) if errors else None}
    return summary, results


def task_metrics(tasks, start, end):
    summary, latencies, quality = {}, [], []
    for action in ("vision", "text", "multimodal"):
        selected = [t for t in tasks if t.get("action") == action]
        completed = [t for t in selected if t.get("status") == "TASK_COMPLETED"
                     and boolean(t.get("simulated")) is False and boolean(t.get("model_executed")) is not False]
        prefix = action + "_"
        summary.update({prefix+"requested": len(selected), prefix+"started": sum(bool(t.get("started_at")) for t in selected),
                        prefix+"completed_nonsimulated": len(completed),
                        prefix+"simulated": sum(boolean(t.get("simulated")) is True for t in selected),
                        prefix+"model_executed_unknown": sum(boolean(t.get("model_executed")) is None for t in selected),
                        prefix+"model_executed_true": sum(boolean(t.get("model_executed")) is True for t in selected),
                        prefix+"timeout_flag": sum(boolean(t.get("timed_out")) is True for t in selected),
                        prefix+"cancelled": sum(t.get("status") == "TASK_CANCELLED" for t in selected),
                        prefix+"failed": sum(t.get("status") == "TASK_FAILED" for t in selected),
                        prefix+"late": sum(boolean(t.get("late")) is True for t in selected),
                        prefix+"completed_after_end": sum((timestamp(t.get("completed_at")) or -math.inf) > end for t in selected),
                        prefix+"completed_per_hour": len(completed)*3600/(end-start)})
        for field in ("queue_seconds", "duration_seconds", "capture_seconds", "inference_seconds"):
            valid = []
            for task in completed:
                value = number(task.get(field))
                if value is not None and value >= 0:
                    valid.append(value)
                elif task.get(field):
                    quality.append({"task_id": task["task_id"], "field": field, "issue": "INVALID_LATENCY"})
            row = {"action": action, "metric": field, **stats(valid)}
            latencies.append(row)
            if field == "duration_seconds":
                summary.update({prefix+"duration_median_s": row["median"], prefix+"duration_p95_s": row["p95"]})
    return summary, latencies, quality


def question_metrics(rows, start, end, max_gap):
    grouped = defaultdict(list)
    for row in rows:
        t = timestamp(row.get("timestamp_utc"))
        if t is not None and start <= t <= end:
            grouped[row["question_id"]].append((t, row))
    output = []
    for question in [f"Q{i}" for i in range(1, 8)]:
        values = sorted(grouped[question], key=lambda p: p[0])
        seconds, statuses = Counter(), Counter(r.get("status") for _, r in values)
        fingerprints, interpretations = set(), set()
        for _, r in values:
            fingerprints.add(tuple(r.get(k, "") for k in ("status", "answer", "evidence_ids", "interpretation_id", "source_snapshot_id")))
            if r.get("interpretation_id"):
                interpretations.add(r["interpretation_id"])
        # No extension past the last publication or across gaps larger than the declared analysis limit.
        for (a, row), (b, _) in zip(values, values[1:]):
            if 0 < b-a <= max_gap:
                seconds[row.get("status", "UNKNOWN")] += b-a
        known = sum(seconds.values())
        for status in sorted(set(statuses) | set(seconds) | {"UNOBSERVED"}):
            duration = max(0., end-start-known) if status == "UNOBSERVED" else seconds[status]
            output.append({"question_id": question, "status": status, "publications": statuses[status],
                           "seconds": duration, "run_fraction": duration/(end-start),
                           "all_publications": len(values), "unique_payload_states": len(fingerprints),
                           "unique_interpretations": len(interpretations), "max_publication_gap_s": max_gap})
    return output


def resource_metrics(samples, interval, expected):
    seen, fresh, valid_rows = set(), [], 0
    for row in samples:
        age = number(row.get("resource_age_s"))
        key = row.get("resource_timestamp_utc")
        if age is not None and 0 <= age <= 2*interval and key:
            valid_rows += 1
            if key not in seen:
                seen.add(key)
                fresh.append(row)
    fields = ("cpu_percent", "ram_used_mb", "ram_available_mb", "process_cpu_percent",
              "process_rss_mb", "process_peak_rss_mb", "process_swap_mb", "swap_mb", "pi_temp_c")
    metrics = {"resource_unique_samples": len(fresh), "resource_sample_coverage_fraction": valid_rows/expected}
    for field in fields:
        result = stats(row.get(field) for row in fresh)
        for suffix in ("n", "median", "p95", "max"):
            metrics[field+"_"+suffix] = result[suffix]
    worker_rss, worker_cpu = [], []
    for row in fresh:
        workers = decode(row.get("gemma_processes"), [])
        if workers:
            worker_rss.append(sum(number(w.get("rss_mb")) or 0 for w in workers))
            worker_cpu.append(sum(number(w.get("cpu_percent")) or 0 for w in workers))
    metrics["gemma_detected_resource_samples"] = len(worker_rss)
    metrics["gemma_detected_rss_median_mib"] = stats(worker_rss)["median"]
    metrics["gemma_detected_cpu_median_reported"] = stats(worker_cpu)["median"]
    return metrics


def fault_metrics(rows, start, end):
    output = []
    for row in rows:
        a, b = timestamp(row.get("activated_at")), timestamp(row.get("restored_at"))
        detection = number(row.get("detection_latency_s"))
        recovery = number(row.get("recovery_latency_s"))
        overlaps = []
        if a is not None:
            for other in rows:
                c, d = timestamp(other.get("activated_at")), timestamp(other.get("restored_at"))
                if other["fault_id"] != row["fault_id"] and c is not None and max(a, c) < min(b or end, d or end):
                    overlaps.append(other["fault_id"])
        output.append({**row, "activation_s": a-start if a is not None else None,
                       "restore_s": b-start if b is not None else None,
                       "overlapping_fault_ids": overlaps,
                       "applied_to_task": bool(row.get("applied_at")),
                       "detection_observed": bool(row.get("detected_at")),
                       "recovery_observed": bool(row.get("recovered_at")),
                       "preexisting_failure_decoded": boolean(row.get("preexisting_failure")),
                       "negative_latency": any(v is not None and v < 0 for v in (detection, recovery)),
                       "detection_latency_numeric_s": detection if detection is not None and detection >= 0 and a is not None and row.get("detected_at") else None,
                       "recovery_latency_numeric_s": recovery if recovery is not None and recovery >= 0 and b is not None and row.get("recovered_at") else None})
    return output
