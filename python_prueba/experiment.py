"""Instrumentación del host y potencia manual, separadas de la política."""

import os
import time
from uuid import uuid4

import psutil

from context import PROFILE


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
