from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil
from .contracts import utc_now


class ResourceMonitor:
    def __init__(self, database: Path):
        self.database = database
        self.process = psutil.Process()
        self.external = {}
        self.peak_rss = 0
        self.process.cpu_percent()
        psutil.cpu_percent()

    def sample(self) -> dict:
        memory = self.process.memory_info()
        self.peak_rss = max(self.peak_rss, memory.rss)
        workers = []
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = process.info["name"] or ""
                command = " ".join(process.info["cmdline"] or [])
                if process.pid != os.getpid() and ("litert" in name.lower() or "litert-lm" in command):
                    monitored = self.external.setdefault(process.pid, process)
                    workers.append({"pid": process.pid, "name": name, "cpu_percent": monitored.cpu_percent(),
                                    "rss_mb": round(monitored.memory_info().rss / 1048576, 1)})
            except (psutil.Error, OSError):
                continue
        self.external = {p["pid"]: self.external[p["pid"]] for p in workers}
        swap_process = None
        peak_os = None
        try:
            status = Path("/proc/self/status").read_text()
            for line in status.splitlines():
                if line.startswith("VmSwap:"):
                    swap_process = int(line.split()[1]) / 1024
                if line.startswith("VmHWM:"):
                    peak_os = int(line.split()[1]) / 1024
        except OSError:
            pass
        temperature = None
        try:
            temperature = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
        except (OSError, ValueError):
            pass
        throttled = None
        if sys.platform == "linux" and shutil.which("vcgencmd"):
            try:
                throttled = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=0.5).stdout.strip() or None
            except (OSError, subprocess.TimeoutExpired):
                pass
        size = sum(path.stat().st_size for path in self.database.parent.glob(self.database.name + "*") if path.is_file())
        system_memory = psutil.virtual_memory()
        return {"sampled_at": utc_now(), "sampled_monotonic": time.monotonic(), "cpu_total_percent": psutil.cpu_percent(), "available_mb": round(system_memory.available / 1048576),
                "ram_used_mb": round(system_memory.used / 1048576, 1), "ram_total_mb": round(system_memory.total / 1048576, 1),
                "main": {"pid": os.getpid(), "cpu_percent": self.process.cpu_percent(), "rss_mb": round(memory.rss / 1048576, 1),
                         "peak_rss_mb": peak_os or round(self.peak_rss / 1048576, 1), "swap_mb": swap_process},
                "gemma_processes": workers, "swap_used_mb": round(psutil.swap_memory().used / 1048576, 1),
                "temperature_c": temperature, "throttled": throttled, "database_mb": round(size / 1048576, 2),
                "disk_free_mb": round(shutil.disk_usage(self.database.parent).free / 1048576)}


def budget_reason(resources: dict, config: dict) -> str | None:
    if resources["available_mb"] < config["min_available_mb"] or resources["main"]["rss_mb"] > config["max_rss_mb"]:
        return "INSUFFICIENT_MEMORY"
    if resources["cpu_total_percent"] >= config["max_cpu_percent"]:
        return "CPU_BUDGET"
    if resources["database_mb"] >= config["max_database_mb"] or resources["disk_free_mb"] < config["min_disk_free_mb"]:
        return "STORAGE_BUDGET"
    return None
