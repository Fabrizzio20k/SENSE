from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import queue
import threading
import time
from concurrent.futures import Future
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .agents import InterpretationAgent, VisionAgent
from .config import load_config
from .contracts import utc_now
from .orchestrator import SenseOrchestrator
from .runtime import TaskManager
from .storage import ExperimentLog
from .telemetry import ResourceMonitor


def software_metadata(root: Path, model: str) -> dict:
    source_hash = hashlib.sha256()
    for path in sorted([root / "main.py", root / "run.sh", *root.joinpath("sense").glob("*.py"),
                        *root.joinpath("public").glob("*.html"), *root.joinpath("public").glob("*.js"), *root.joinpath("public").glob("*.css")]):
        source_hash.update(path.name.encode() + path.read_bytes())
    dependencies = {}
    for name in ("flask", "ultralytics", "ncnn", "psutil", "paho-mqtt", "requests"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = "unavailable"
    model_hash = hashlib.sha256()
    files = sorted(root.joinpath("yolo26n_ncnn_model").glob("*"))
    for path in files:
        if path.is_file():
            with path.open("rb") as source:
                while chunk := source.read(1048576):
                    model_hash.update(chunk)
    return {"software_version": source_hash.hexdigest(), "python_version": platform.python_version(),
            "platform": platform.platform(), "dependencies": dependencies,
            "model_version": {"yolo": "yolo26n/NCNN", "yolo_artifact_hash": model_hash.hexdigest() if files else None,
                              "gemma": model},
            "detector_parameters": {"imgsz": 640, "classes": [0], "confidence": 0.15, "device": "cpu"}}


class ExperimentService:
    """Dispatcher limitado; solo el hilo coordinador modifica el dominio."""

    def __init__(self, root: Path, data: Path, config_path: Path, capture, detector, completion, model, readiness):
        self.root, self.config_path, self.model = root, config_path, model
        self.config = load_config(config_path)
        self.log = ExperimentLog(data / "experiments.sqlite3")
        self.resources = ResourceMonitor(self.log.path)
        self.tasks = TaskManager(self.config["interpretation"]["queue_capacity"])
        self.controller = SenseOrchestrator(self.config, self.log, self.tasks, VisionAgent(capture, detector),
                                            InterpretationAgent(completion, model), readiness, {})
        self.inbox = queue.Queue(maxsize=self.config["runtime"]["inbox_capacity"])
        self.controls = queue.Queue(maxsize=8)
        self.reserved = threading.Event()
        self.lease_lock = threading.Lock()
        self.starting = False
        self.shutdown = threading.Event()
        self.dropped = 0
        self.error = None
        self.view_lock = threading.Lock()
        self.published = "{}"
        self.session_id = utc_now()
        self.thread = threading.Thread(target=lambda: asyncio.run(self._loop()), daemon=True, name="sense-orchestrator")
        self.thread.start()

    def reserve(self):
        with self.lease_lock:
            if self.reserved.is_set():
                raise ValueError("Ya hay una medición o un worker pendiente de finalizar.")
            self.starting = True
            self.reserved.set()

    def close(self):
        self.shutdown.set()
        self.thread.join(timeout=2)
        for executor in self.tasks.executors.values():
            executor.shutdown(wait=False, cancel_futures=True)
        if not self.thread.is_alive():
            self.log.db.close()

    def ingest(self, payload, received: float, wall: float):
        run = self.controller.run
        if not run or run["status"] != "RUNNING":
            return
        try:
            self.inbox.put_nowait((payload, received, wall, run["run_id"]))
        except queue.Full:
            self.dropped += 1

    def drain_observations(self):
        for _ in range(self.inbox.maxsize):
            try:
                payload, received, wall, run_id = self.inbox.get_nowait()
            except queue.Empty:
                break
            with self.log.transaction():
                if self.controller.running and self.controller.run["run_id"] == run_id:
                    self.controller.ingest(payload, received, wall)
                else:
                    self.log.event(run_id, "DISPATCHER_DISCARDED", {"reason": "RUN_ALREADY_ENDED"})

    def call(self, action: str, payload: dict | None = None):
        future = Future()
        try:
            self.controls.put_nowait((action, payload or {}, future))
        except queue.Full:
            if action == "start":
                with self.lease_lock:
                    self.starting = False
                    if not self.controller.running and not self.tasks.busy:
                        self.reserved.clear()
            raise ValueError("Cola de control ocupada; vuelva a intentar.") from None
        try:
            return future.result(timeout=10)
        except TimeoutError:
            future.cancel()
            raise ValueError("El comando tardó demasiado; comprueba el estado de la ejecución antes de reintentar.") from None

    def snapshot(self) -> dict:
        with self.view_lock:
            return json.loads(self.published)

    async def _loop(self):
        sampled_at = float("-inf")
        published_at = float("-inf")
        resources = {}
        reported_drops = 0
        while not self.shutdown.is_set():
            now = time.monotonic()
            try:
                if now - sampled_at >= self.config["runtime"]["resource_interval_seconds"]:
                    resources = self.resources.sample()
                    sampled_at = now
                    self.controller.resources = resources
                    if self.controller.running:
                        self.controller.record("RESOURCE_SAMPLE", resources)
                for _ in range(self.controls.maxsize):
                    try:
                        action, payload, future = self.controls.get_nowait()
                    except queue.Empty:
                        break
                    if not future.set_running_or_notify_cancel():
                        if action == "start":
                            with self.lease_lock:
                                self.starting = False
                        continue
                    try:
                        if action == "start":
                            config = load_config(self.config_path)
                            if config["runtime"]["inbox_capacity"] != self.inbox.maxsize:
                                if self.controller.running or self.tasks.busy:
                                    raise ValueError("No se puede cambiar capacidad durante una ejecución.")
                                self.inbox = queue.Queue(maxsize=config["runtime"]["inbox_capacity"])
                            self.config = self.controller.config = config
                            self.tasks.capacity = config["interpretation"]["queue_capacity"]
                            self.controller.metadata = software_metadata(self.root, self.model)
                            self.controller.resources = self.resources.sample()
                            resources = self.controller.resources
                            result = self.controller.start(payload["mode"], now, payload.get("session_id", self.session_id), payload.get("scenario_id", "pilot-classroom"))
                            self.error = None
                        elif action == "stop":
                            self.drain_observations()
                            self.controller.stop("USER_STOP", now)
                            result = {"ok": True}
                        elif action == "query":
                            self.controller.query(payload.get("question_id"))
                            result = {"ok": True}
                        elif action == "presence":
                            self.controller.set_presence(payload.get("detected"), now)
                            result = {"ok": True}
                        else:
                            raise ValueError("Comando no reconocido.")
                        future.set_result(result)
                    except Exception as failure:
                        future.set_exception(failure)
                    finally:
                        if action == "start":
                            with self.lease_lock:
                                self.starting = False
                self.drain_observations()
                if self.dropped != reported_drops and self.controller.running:
                    self.controller.record("DISPATCHER_DROPPED", {"total": self.dropped, "policy": "REJECT_NEWEST"})
                    reported_drops = self.dropped
                with self.log.transaction():
                    self.controller.tick(now, resources)
                with self.lease_lock:
                    if not self.starting and not self.controller.running and not self.tasks.busy and self.controls.empty():
                        self.reserved.clear()
            except Exception as failure:
                self.error = str(failure)
                try:
                    self.controller.stop("INTERNAL_OR_STORAGE_ERROR", now)
                except Exception:
                    # Si la persistencia falla, no se continúan experimentos sin trazabilidad.
                    if self.controller.run:
                        self.controller.run["status"] = "FAILED"
                    self.tasks.cancel(self.controller.run["run_id"] if self.controller.run else "")
            if now - published_at >= self.config["runtime"]["publish_interval_seconds"]:
                view = self.controller.view(now)
                view.update(error=self.error, dispatcher={"queued": self.inbox.qsize(), "capacity": self.inbox.maxsize,
                                                          "dropped": self.dropped}, reserved=self.reserved.is_set())
                with self.view_lock:
                    self.published = json.dumps(view, allow_nan=False)
                published_at = now
            await asyncio.sleep(self.config["runtime"]["tick_seconds"])
        try:
            self.controller.stop("PROCESS_SHUTDOWN", time.monotonic())
        except Exception:
            pass
