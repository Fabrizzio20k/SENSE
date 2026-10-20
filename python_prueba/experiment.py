"""Instrumentación del host y potencia manual, separadas de la política."""

import os
import time
from uuid import uuid4

import psutil

from context import PROFILE


POWER_PROTOCOL = {"id": "manual-power-v1", "interval_s": 30,
                  "periodic_window": "due_inclusive_next_due_exclusive", "final_window_s": 30}


def measurement_state(run, events, elapsed):
    """Cola derivada del plan persistido y sus resoluciones; nunca inventa W."""
    protocol = run["manifest"].get("power_protocol")
    if run["manifest"]["source_mode"] != "live" or not protocol:
        return {"status": "not_required" if run["manifest"]["source_mode"] != "live" else "legacy",
                "tasks": [], "pending_count": 0, "omitted_count": 0, "can_close": False}
    stopped = run["status"] != "running"
    if stopped:
        terminal = next(e for e in reversed(events) if e["type"] == "run."+run["status"])
        elapsed = terminal["elapsed_s"]
    period = protocol["interval_s"]
    duration = run["manifest"]["request"]["duration_s"]
    tasks = []
    for due in range(0, int(min(elapsed, duration))//period*period+1, period):
        if due >= duration or (stopped and due >= elapsed and due != 0):
            continue
        tasks.append({"task_id": f"power-{due}", "due_elapsed_s": due,
                      "window_start_s": due, "window_end_s": min(due+period, elapsed),
                      "status": "pending"})
    if stopped:
        tasks.append({"task_id": "final", "due_elapsed_s": elapsed,
                      "window_start_s": max(0, elapsed-protocol["final_window_s"]),
                      "window_end_s": elapsed, "status": "pending"})
    by_id = {task["task_id"]: task for task in tasks}
    readings = active_readings([e["payload"] for e in events if e["type"] == "power.reading_recorded"])
    active_ids = {r["reading_id"] for r in readings}
    for event in events:
        value = event["payload"]
        task = by_id.get(value.get("task_id"))
        if not task:
            continue
        if event["type"] == "power.task_omitted":
            task.update(status="omitted", reason=value["reason"], observer_id=value["observer_id"])
        elif event["type"] == "power.reading_recorded" and value["reading_id"] in active_ids and value["quantity"] == "power":
            observed = value["observed_elapsed_s"]
            if task["window_start_s"] <= observed <= elapsed and (task["task_id"] == "final" or observed < task["due_elapsed_s"]+period):
                task.update(status="recorded", reading_id=value["reading_id"], observed_elapsed_s=observed)
                task.pop("reason", None)
    pending = sum(task["status"] == "pending" for task in tasks)
    omitted = sum(task["status"] == "omitted" for task in tasks)
    closed = any(e["type"] == "measurement.closed" for e in events)
    return {"status": ("closed_with_omissions" if omitted else "closed") if closed else "recording" if not stopped else "pending_review",
            "elapsed_s": elapsed, "interval_s": period, "tasks": tasks, "pending_count": pending, "omitted_count": omitted,
            "next_due_elapsed_s": min((int(elapsed)//period+1)*period, duration) if not stopped and elapsed < duration else None,
            "can_close": stopped and not pending and not closed}


def active_readings(readings):
    superseded = {r["supersedes_reading_id"] for r in readings if r.get("supersedes_reading_id")}
    return [r for r in readings if r["reading_id"] not in superseded]


def energy_estimate(readings, duration_s):
    active = active_readings(readings)
    powers = sorted((r for r in active if r["quantity"] == "power"), key=lambda r: r["observed_elapsed_s"])
    joules = covered = 0.0
    for first, second in zip(powers, powers[1:]):
        gap = second["observed_elapsed_s"]-first["observed_elapsed_s"]
        if 0 < gap <= PROFILE["power_max_gap_s"]:
            joules += (first["value"]+second["value"])*.5*gap
            covered += gap
    counters = {}
    for instrument in {r.get("instrument_id", "unspecified") for r in active if r["quantity"] == "energy_counter"}:
        points = sorted((r for r in active if r["quantity"] == "energy_counter" and r.get("instrument_id", "unspecified") == instrument),
                        key=lambda r: r["observed_elapsed_s"])
        ordered = all(a["observed_elapsed_s"] < b["observed_elapsed_s"] for a, b in zip(points, points[1:]))
        reset = any(a["normalized_value"] > b["normalized_value"] for a, b in zip(points, points[1:]))
        valid = len(points) >= 2 and ordered and not reset
        counters[instrument] = {"delta_Wh": points[-1]["normalized_value"]-points[0]["normalized_value"] if valid else None,
                                "covered_duration_s": points[-1]["observed_elapsed_s"]-points[0]["observed_elapsed_s"] if valid else 0,
                                "reset_detected": reset, "method": "normalized_counter_difference_no_reset_unwrap"}
    return {"estimated_Wh": joules/3600 if covered else None, "covered_duration_s": covered,
            "coverage_ratio": covered/duration_s if duration_s > 0 else 0,
            "method": "trapezoids_no_extrapolation_max_gap_60s", "samples": len(powers), "counter_estimates": counters}


class Sampler:
    def __init__(self):
        self.last_time = time.monotonic()
        self.processes = {}
        self.extra_pids = {}
        psutil.cpu_percent(percpu=True)

    def sample(self, mode):
        now = time.monotonic()
        interval, self.last_time = now-self.last_time, now
        errors = []
        memory = swap = None
        cores = []
        try:
            memory = psutil.virtual_memory()
        except (OSError, psutil.Error) as error:
            errors.append("memory:"+type(error).__name__)
        try:
            swap = psutil.swap_memory()
        except (OSError, psutil.Error) as error:
            errors.append("swap:"+type(error).__name__)
        try:
            cores = psutil.cpu_percent(percpu=True)
        except (OSError, psutil.Error) as error:
            errors.append("cpu:"+type(error).__name__)
        temperature = frequency = None
        try:
            sensors = psutil.sensors_temperatures()
            # Raspberry Pi/Linux: no confundir un sensor de batería/disco con CPU.
            cpu_sensors = [s for key, values in sensors.items() if key in ("cpu_thermal", "coretemp", "k10temp") for s in values]
            temperature = cpu_sensors[0].current if cpu_sensors else None
        except (AttributeError, OSError):
            pass
        try:
            freq = psutil.cpu_freq()
            frequency = freq.current if freq else None
        except (AttributeError, NotImplementedError, OSError):
            pass
        processes, seen = [], set()
        try:
            candidates = list(psutil.process_iter(["pid", "name", "create_time"]))
        except (OSError, psutil.Error) as error:
            errors.append("processes:"+type(error).__name__)
            candidates = []
        for item in candidates:
            try:
                role = self.extra_pids.get(item.pid) or ("backend" if item.pid == os.getpid() else ("broker" if item.info["name"] == "mosquitto" else None))
                if role is None:
                    continue
                key = (item.pid, item.info["create_time"])
                seen.add(key)
                process = self.processes.get(key)
                if process is None:
                    process = psutil.Process(item.pid)
                    process.cpu_percent()
                    self.processes[key] = process
                    cpu = None
                else:
                    cpu = process.cpu_percent()
                processes.append({"role": role, "pid": item.pid, "process_instance_id": f"{item.pid}:{key[1]}",
                                  "process_cpu_percent": cpu, "rss_bytes": process.memory_info().rss})
            except (OSError, psutil.Error):
                continue
        self.processes = {key: process for key, process in self.processes.items() if key in seen}
        return {"sample_id": str(uuid4()), "interval_s": interval,
                "system_cpu_percent": sum(cores)/len(cores) if cores else None, "per_cpu_percent": cores,
                "ram_used_bytes": memory.used if memory else None, "ram_available_bytes": memory.available if memory else None,
                "swap_used_bytes": swap.used if swap else None, "cpu_temperature_c": temperature, "cpu_frequency_mhz": frequency,
                "scope": "host_live_runtime" if mode == "live" else "host_replay_runtime_not_original_pi",
                "throttling": None, "processes": processes, "collection_errors": errors}
