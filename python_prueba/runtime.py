"""Tiempo vivo y replay explícito; un proceso, una sesión activa."""

import asyncio
import fcntl
import hashlib
import importlib.metadata
import json
import logging
import os
import platform
import queue
import signal
import sqlite3
import sys
import time
from dataclasses import dataclass
from contextlib import suppress
from pathlib import Path

from dotenv import load_dotenv

from context import ACQUISITION_PROFILE, PROFILE, aware_time, digest
from actions import Actions
from experiment import Sampler
from mqtt_ingest import MQTTInput
from orchestrator import Conflict, Engine
from slm import CompletedResponseError, NoRequestError, WARMUP_PROFILE
from store import Store, utc_now


ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "docs/data/2026-10-17-baseline-recibido.txt"
FIXTURE_HASH = "2b47eda963f45490bedda4590f637f8cd6a700a47e6e0ee2f313c7eb920a3ce7"


def package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


@dataclass
class Settings:
    mode: str = "live"
    data_dir: Path = ROOT / "data"
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    replay_speed: float = 1
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    vision_model: str = ""
    vision_weights: str = ""
    vision_input_size: int = 320
    vision_tile_size: int = 0
    vision_tile_overlap: int = 160
    camera_clock_is_boottime: bool = False
    radar_timestamp_is_measurement: bool = False
    radar_uncertainty_s: float | None = None
    camera_uncertainty_s: float | None = None
    slm_url: str = "http://127.0.0.1:8080"
    slm_model: str = "gemma4-e2b"
    slm_pid: int | None = None
    slm_image_side: int = 480
    slm_warmup: bool = True

    @classmethod
    def environment(cls):
        load_dotenv(ROOT/".env", override=False, encoding="utf-8")
        result = cls(mode=os.getenv("SENSE_INPUT_MODE", "live"),
                     data_dir=Path(os.getenv("SENSE_DATA_DIR", str(ROOT/"data"))),
                     mqtt_host=os.getenv("SENSE_MQTT_HOST", "127.0.0.1"),
                     mqtt_port=int(os.getenv("SENSE_MQTT_PORT", "1883")),
                     replay_speed=float(os.getenv("SENSE_REPLAY_SPEED", "1")),
                     mqtt_username=os.getenv("SENSE_MQTT_USERNAME"), mqtt_password=os.getenv("SENSE_MQTT_PASSWORD"),
                     vision_model=os.getenv("SENSE_VISION_MODEL", ""), vision_weights=os.getenv("SENSE_VISION_WEIGHTS", ""),
                     vision_input_size=int(os.getenv("SENSE_VISION_INPUT_SIZE", "320")),
                     vision_tile_size=int(os.getenv("SENSE_VISION_TILE_SIZE", "0")),
                     vision_tile_overlap=int(os.getenv("SENSE_VISION_TILE_OVERLAP", "160")),
                     camera_clock_is_boottime=os.getenv("SENSE_CAMERA_CLOCK_IS_BOOTTIME", "0") == "1",
                     radar_timestamp_is_measurement=os.getenv("SENSE_RADAR_TIMESTAMP_IS_MEASUREMENT", "0") == "1",
                     radar_uncertainty_s=float(os.environ["SENSE_RADAR_UNCERTAINTY_S"]) if "SENSE_RADAR_UNCERTAINTY_S" in os.environ else None,
                     camera_uncertainty_s=float(os.environ["SENSE_CAMERA_UNCERTAINTY_S"]) if "SENSE_CAMERA_UNCERTAINTY_S" in os.environ else None,
                     slm_url=os.getenv("SENSE_SLM_URL", "http://127.0.0.1:8080"), slm_model=os.getenv("SENSE_SLM_MODEL", "gemma4-e2b"),
                     slm_pid=int(os.environ["SENSE_SLM_PID"]) if "SENSE_SLM_PID" in os.environ else None,
                     slm_image_side=int(os.getenv("SENSE_SLM_IMAGE_SIDE", "480")),
                     slm_warmup=os.getenv("SENSE_SLM_WARMUP", "1") == "1")
        if os.getenv("SENSE_SLM_WARMUP", "1") not in ("0", "1"):
            raise ValueError("SENSE_SLM_WARMUP debe ser 0 o 1")
        if result.mode not in ("live", "replay") or not 1 <= result.mqtt_port <= 65535 or not 0 < result.replay_speed <= 1000:
            raise ValueError("configuración SENSE inválida")
        if result.vision_input_size not in (320, 640) or (result.vision_tile_size and not 0 <= result.vision_tile_overlap < result.vision_tile_size):
            raise ValueError("tamaño NCNN o solapamiento inválido")
        if result.slm_image_side not in (320, 480, 640):
            raise ValueError("lado mayor para Gemma debe ser 320, 480 o 640")
        from urllib.parse import urlsplit
        target = urlsplit(result.slm_url)
        if target.scheme != "http" or target.hostname not in ("127.0.0.1", "localhost", "::1") or target.username or target.password or target.query or target.fragment:
            raise ValueError("LiteRT-LM debe usar una URL HTTP local sin credenciales ni query")
        for uncertainty in (result.radar_uncertainty_s, result.camera_uncertainty_s):
            if uncertainty is not None and not 0 <= uncertainty <= 60:
                raise ValueError("incertidumbre temporal inválida")
        return result

    def camera_config(self):
        return {"model_dir": self.vision_model, "input_size": self.vision_input_size, "capture_size": [3280, 2464],
                "max_image_side": 1600, "settle_s": 2, "scope_id": "camera-roi-1", "confidence": .15, "fusion_iou": .45,
                "tile_size": self.vision_tile_size, "tile_overlap": self.vision_tile_overlap,
                "clock_is_boottime": self.camera_clock_is_boottime}


def replay_records():
    raw = FIXTURE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_HASH:
        raise ValueError("el fixture de replay cambió: verificar procedencia antes de usarlo")
    # Solo esta captura conocida tiene una cola truncada, preservada para auditoría.
    lines = raw.splitlines()
    records = [json.loads(line) for line in lines[:-1]]
    if len(records) != 490:
        raise ValueError("fixture incompleto")
    return records


class Runtime:
    def __init__(self, settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.instance_lock = (settings.data_dir/"runtime.lock").open("a")
        try:
            fcntl.flock(self.instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.instance_lock.close()
            raise RuntimeError("ya existe un backend con este directorio; usar un solo worker ASGI")
        self.store = Store(settings.data_dir/"sense.sqlite3")
        self.engine = Engine(self.store)
        self.input = MQTTInput(settings.mqtt_host, settings.mqtt_port, settings.mqtt_username, settings.mqtt_password) if settings.mode == "live" else None
        self.task = None
        self.replay_task = None
        self.failure = None
        self.start_monotonic = None
        self.sampler = Sampler()
        self.artifact_dir = settings.data_dir/"artifacts"
        self.artifact_dir.mkdir(exist_ok=True)
        self.actions = Actions(self)
        self.preflight = {"status": "not_checked"}
        self.admission_lock = asyncio.Lock()

    async def open(self):
        if self.settings.mode == "live":
            await self.prepare_dependencies()
        else:
            self.preflight = {"status": "not_required", "reason": "mqtt_only_replay"}
        if self.input:
            self.input.start()
        self.task = asyncio.create_task(self.loop())

    async def prepare_dependencies(self, need_yolo=True, need_gemma=True):
        async with self.admission_lock:
            return await self._prepare_dependencies(need_yolo, need_gemma, warmup=True)

    async def _prepare_dependencies(self, need_yolo=True, need_gemma=True, warmup=False):
        if self.settings.mode != "live":
            raise Conflict("el replay MQTT no prepara modelos de hardware")
        if self.engine.run_id or (self.actions.task and not self.actions.task.done()):
            raise Conflict("la preparación solo se permite fuera de una sesión")
        if self.store.flag("slm_busy") or self.store.flag("camera_busy") or self.actions.camera.failed_stop:
            self.preflight = {**self.preflight, "status": "blocked", "reason": "heavy_slot_reserved_confirm_idle_before_preparation"}
            return self.preflight
        report = dict(self.preflight)
        report.pop("reason", None)
        self.preflight = {**report, "status": "preparing"}
        if need_gemma:
            report["gemma"] = await self.actions.slm.probe()
        if need_yolo:
            from vision import validate_ncnn
            target = Path(self.settings.vision_model).expanduser().resolve() if self.settings.vision_model else (
                self.settings.data_dir/"models"/f"yolo26n_{self.settings.vision_input_size}_ncnn_model").resolve()
            weights = Path(self.settings.vision_weights).expanduser().resolve() if self.settings.vision_weights else (self.settings.data_dir/"models/yolo26n.pt").resolve()
            self.settings.vision_model, self.settings.vision_weights = str(target), str(weights)
            try:
                prepared = False
                if not target.exists():
                    process = await asyncio.create_subprocess_exec(sys.executable, str(ROOT/"prepare.py"),
                        "--model-dir", str(target), "--weights", str(weights), "--input-size", str(self.settings.vision_input_size),
                        start_new_session=True)
                    try:
                        code = await process.wait()
                    except BaseException:
                        # El exportador puede tener hijos pnnx; cancelar todo su grupo.
                        with suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGTERM)
                        try:
                            await asyncio.wait_for(process.wait(), 5)
                        except asyncio.TimeoutError:
                            pass
                        finally:
                            with suppress(ProcessLookupError):
                                os.killpg(process.pid, signal.SIGKILL)
                            await process.wait()
                        raise
                    if code:
                        raise RuntimeError("falló la preparación NCNN; revisar el registro de conversión y las dependencias vision")
                    prepared = True
                validated = await asyncio.to_thread(validate_ncnn, target, self.settings.vision_input_size)
                report["yolo"] = {**validated, "status": "ready", "preparation": "created_before_session" if prepared else "reused_existing_export"}
                preparation_file = target/"preparation.json"
                if preparation_file.is_file():
                    report["yolo"]["export_provenance"] = json.loads(preparation_file.read_text())
                self.actions.camera.config = self.settings.camera_config()
            except (OSError, RuntimeError, ValueError, ImportError) as error:
                report["yolo"] = {"status": "unavailable", "model_dir": str(target), "error": str(error)[:700],
                                  "hint": "Una ruta existente inválida se conserva; corregirla o seleccionar otra ruta."}
        if need_gemma:
            if not self.settings.slm_warmup:
                report["gemma_warmup"] = {"status": "disabled", "generation_verified": False}
            elif report["gemma"]["status"] != "ready":
                report["gemma_warmup"] = {"status": "not_run", "reason": "gemma_unavailable", "generation_verified": False}
            elif warmup or report.get("gemma_warmup", {}).get("status") != "ready":
                await self._warmup_gemma(report)
        report["status"] = self._preflight_status(report)
        self.preflight = report
        (self.settings.data_dir/"preflight.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        logging.info("SENSE preparación previa: %s", report)
        return report

    async def _warmup_gemma(self, report):
        started = time.monotonic()
        details = {"status": "running", "started_at": utc_now(), "generation_verified": False,
                   "profile_id": WARMUP_PROFILE, "image_path": str(ROOT/"static/image.png"),
                   "measurement_scope": "setup_outside_experimental_runs"}
        report["gemma_warmup"] = details
        self.preflight = {**report, "status": "preparing"}
        self.store.flag("slm_busy", {"state": "warmup_in_flight", "started_at": details["started_at"]}, write=True)
        try:
            async with asyncio.timeout(ACQUISITION_PROFILE["slm_timeout_s"]):
                report["gemma_warmup"] = await self.actions.slm.warmup(ROOT/"static/image.png", self.settings.slm_image_side)
            self.store.flag("slm_busy", None, write=True)
        except BaseException as error:
            # Un HTTP cancelado no confirma la detención del cálculo remoto.
            if isinstance(error, (CompletedResponseError, NoRequestError)):
                self.store.flag("slm_busy", None, write=True)
            report["gemma_warmup"] = {**details, "status": "failed", "duration_s": time.monotonic()-started,
                                      "error": f"{type(error).__name__}: {error}"[:700],
                                      "remote_stop_unconfirmed": bool(self.store.flag("slm_busy"))}
            if not isinstance(error, Exception):
                self.preflight = {**report, "status": self._preflight_status(report)}
                (self.settings.data_dir/"preflight.json").write_text(json.dumps(self.preflight, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
                raise

    def _preflight_status(self, report):
        if self.store.flag("slm_busy") or self.store.flag("camera_busy") or self.actions.camera.failed_stop:
            return "blocked"
        ready = all(report.get(name, {}).get("status") == "ready" for name in ("gemma", "yolo"))
        if self.settings.slm_warmup:
            ready = ready and report.get("gemma_warmup", {}).get("status") == "ready"
        return "ready" if ready else "degraded"

    async def dependency_health(self):
        if self.settings.mode != "live":
            return dict(self.preflight)
        if self.admission_lock.locked() or self.engine.run_id or self.store.flag("slm_busy"):
            return {**self.preflight, "gemma_probe_skipped": "preparation_active_session_or_unconfirmed_stop; last_result_only"}
        async with self.admission_lock:
            self.preflight["gemma"] = await self.actions.slm.probe()
            if self.preflight["gemma"]["status"] != "ready":
                self.preflight["gemma_warmup"] = {"status": "not_run", "reason": "gemma_unavailable", "generation_verified": False}
            self.preflight["status"] = self._preflight_status(self.preflight)
            return dict(self.preflight)

    async def admit(self, request, key=None):
        # Preparación y admisión comparten exclusión para no contaminar otra sesión.
        async with self.admission_lock:
            if key and self.store.by_key(key):
                return self.start(request, key)
            self._check_admission(request)
            variant = request.get("variant", "rules-v1")
            if variant != "rules-v1":
                await self._prepare_dependencies(need_yolo=variant != "E_visual", need_gemma=variant in ("D", "E_visual"))
            return self.start(request, key)

    def _check_admission(self, request):
        if self.failure:
            raise Conflict("backend detenido por error de registro; revisar almacenamiento y reiniciar")
        if request["source_mode"] != self.settings.mode:
            raise Conflict(f"este backend está en modo {self.settings.mode}")
        variant = request.get("variant", "rules-v1")
        if variant != "rules-v1" and self.settings.mode != "live":
            raise Conflict("A–D/E_visual requieren evidencia real; este replay solo contiene MQTT")
        if variant != "rules-v1" and (self.store.flag("slm_busy") or self.store.flag("camera_busy") or self.actions.camera.failed_stop):
            raise Conflict("slot pesado reservado hasta confirmar detención del runtime anterior")
        if self.engine.run_id:
            raise Conflict("ya existe una sesión activa")

    def start(self, request, key=None):
        if key and self.store.by_key(key):
            return self.engine.start(request, key, {})[0]
        self._check_admission(request)
        variant = request.get("variant", "rules-v1")
        if variant in ("A", "B", "C", "D") and self.preflight.get("yolo", {}).get("status") != "ready":
            raise Conflict("YOLO no preparado: consultar /health y POST /v1/runtime/prepare antes de iniciar")
        if variant in ("D", "E_visual") and self.preflight.get("gemma", {}).get("status") != "ready":
            raise Conflict("Gemma local no disponible: levantar run-litert.sh y repetir la preparación")
        if variant in ("D", "E_visual") and self.settings.slm_warmup and self.preflight.get("gemma_warmup", {}).get("status") != "ready":
            raise Conflict("calentamiento de Gemma sin completar: consultar /health y repetir la preparación")
        profile = {**PROFILE, "variant": variant, "camera_enabled": variant != "rules-v1",
                   "slm_enabled": variant in ("D", "E_visual"), "acquisition": ACQUISITION_PROFILE,
                   "camera_config": self.settings.camera_config()}
        manifest = {"schema_version": 1, "application_version": "0.1.0", "profile": profile,
                    "profile_hash": digest(profile), "acquisition_hash": digest({"thresholds": PROFILE, "acquisition": ACQUISITION_PROFILE,
                        "camera": self.settings.camera_config(), "monitor_count": request.get("monitor_count"),
                        "overlap_verified": request.get("overlap_verified"), "crossmodal_max_skew_s": request.get("crossmodal_max_skew_s"),
                        "fault_plan": request.get("fault_plan", []), "slm_warmup_enabled": self.settings.slm_warmup,
                        "slm_warmup_profile": WARMUP_PROFILE,
                        "slm_warmup_image_sha256": self.preflight.get("gemma_warmup", {}).get("image_input", {}).get("sha256")}),
                    "source_mode": self.settings.mode,
                    "measurement_class": "exploratory_live" if self.settings.mode == "live" else "simulation",
                    "request": request, "python": platform.python_version(), "platform": platform.platform(),
                    "packages": {name: package_version(name) for name in (
                        "fastapi", "uvicorn", "paho-mqtt", "psutil", "httpx", "pydantic", "python-dotenv", "pillow", "pyyaml",
                        "ultralytics", "ncnn", "pnnx", "torch", "numpy", "opencv-python")},
                    "clock_basis": PROFILE["timing_basis_live"] if self.settings.mode == "live" else "source_timestamp_deltas_simulated_receipt",
                    "mqtt_topic": "rustio/rpi5-01/telemetry", "mqtt_subscription_qos": 0,
                    "sensor_quality": "unverified", "final_evaluation_eligible": False,
                    "slm": {"url": self.settings.slm_url, "model": self.settings.slm_model, "reasoning_effort": "none",
                            "image_side": self.settings.slm_image_side, "thinking_effective_verified": False,
                            "warmup_enabled": self.settings.slm_warmup},
                    "camera_model_resident_before_run": bool(self.actions.camera.process and self.actions.camera.process.is_alive()),
                    "preflight": self.preflight,
                    "last_idle_confirmation": self.store.flag("last_idle_confirmation"),
                    "radar_time_declared_measurement": self.settings.radar_timestamp_is_measurement,
                    "radar_uncertainty_s": self.settings.radar_uncertainty_s, "camera_uncertainty_s": self.settings.camera_uncertainty_s,
                    "limitations": ["hardware_integration_not_verified", "measurement_times_unverified", "sensor_quality_unknown",
                                    "candidate_profile_not_frozen", "manual_reference_required"]}
        if self.settings.mode == "replay":
            replay_records()
            manifest.update(fixture_sha256=FIXTURE_HASH, replay_speed=self.settings.replay_speed,
                            excluded_tail_line=491, source_receipt_latency_measurable=False)
        run_id, created = self.engine.start(request, key, manifest)
        if created:
            self.actions.reset()
            self.start_monotonic = time.monotonic()
            self.sampler = Sampler()
            for step in request.get("fault_plan", []):
                self.engine.add_fault({"source_id": step["source_id"], "mode": step["mode"],
                                       "start_after_s": step["start_elapsed_s"], "duration_s": step["duration_s"], "reason": step["reason"]})
            if self.settings.mode == "replay":
                if self.replay_task and not self.replay_task.done():
                    self.replay_task.cancel()
                self.replay_task = asyncio.create_task(self.replay(run_id))
        return run_id

    async def replay(self, run_id):
        records = replay_records()
        first = aware_time(records[0]["timestamp"])
        previous = 0
        for record in records:
            elapsed = (aware_time(record["timestamp"])-first).total_seconds()
            if elapsed > self.engine.request["duration_s"]:
                break
            await asyncio.sleep((elapsed-previous)/self.settings.replay_speed)
            if self.engine.run_id != run_id:
                return
            self.engine.ingest(json.dumps(record).encode(), elapsed,
                               receipt_elapsed=time.monotonic()-self.start_monotonic)
            previous = elapsed
        if self.engine.run_id == run_id:
            self.engine.finish(reason="replay_duration_or_input_exhausted")

    async def loop(self):
        next_sample = time.monotonic()+1
        while True:
            try:
                if self.replay_task and self.replay_task.done():
                    error = self.replay_task.exception() if not self.replay_task.cancelled() else None
                    self.replay_task = None
                    if error:
                        raise error
                if self.input:
                    for _ in range(64):
                        try:
                            raw, received_mono, received_at, retained, qos = self.input.queue.get_nowait()
                        except queue.Empty:
                            break
                        if self.engine.run_id and received_mono >= self.start_monotonic:
                            elapsed = received_mono-self.start_monotonic
                            if elapsed > self.engine.request["duration_s"]:
                                self.engine.tick(max(self.engine.elapsed, self.engine.request["duration_s"]))
                                await self.actions.stop("completed", "duration_elapsed")
                                break
                            # Una muestra en cola conserva su tiempo de recepción; tick no la adelanta.
                            self.engine.ingest(raw, elapsed, received_at, elapsed, retained, qos)
                    dropped = self.input.take_dropped()
                    if dropped and self.engine.run_id:
                        self.engine.emit("input.overflow", {"dropped_messages": dropped, "reason": "queue_capacity_or_payload_limit"})
                    if self.engine.run_id and self.input.queue.empty():
                        elapsed = time.monotonic()-self.start_monotonic
                        self.engine.tick(elapsed if self.actions.stop_reason else min(elapsed, self.engine.request["duration_s"]))
                        if elapsed >= self.engine.request["duration_s"]:
                            await self.actions.stop("completed", "duration_elapsed")
                self.actions.tick()
                now = time.monotonic()
                if now >= next_sample:
                    next_sample = now+1
                    if self.engine.run_id:
                        self.sampler.extra_pids = {}
                        if self.actions.camera.process and self.actions.camera.process.is_alive():
                            self.sampler.extra_pids[self.actions.camera.process.pid] = "vision_worker"
                        if self.settings.slm_pid:
                            self.sampler.extra_pids[self.settings.slm_pid] = "litert_lm"
                        sample = self.sampler.sample(self.settings.mode)
                        sample["recorded_elapsed_s"] = now-self.start_monotonic
                        self.engine.emit("resource.sample", sample)
            except Exception as error:
                logging.exception("SENSE: ciclo detenido; sesión no evaluable")
                await self.fail(error)
                return
            await asyncio.sleep(.1)

    async def close(self):
        for task in (self.task, self.replay_task):
            if task:
                task.cancel()
        await asyncio.gather(*(task for task in (self.task, self.replay_task) if task), return_exceptions=True)
        await self.actions.close()
        if self.engine.run_id:
            self.engine.finish("interrupted", "backend_shutdown")
        if self.input:
            self.input.stop()
        self.store.close()
        self.instance_lock.close()

    async def fail(self, error):
        self.failure = f"{type(error).__name__}: {error}"
        try:
            await self.actions.close()
        except Exception:
            logging.exception("No se confirmó cierre del worker")
        if self.engine.run_id:
            try:
                self.engine.finish("failed", "runtime_or_persistence_error")
            except sqlite3.Error:
                self.engine.run_id = None

    def ask(self, question):
        kind = question["type"]
        if kind in ("presence", "environment", "monitor"):
            return self.engine.episode("manual_question", question=kind)
        if kind == "environment_trend":
            trends = {}
            import statistics
            for source_id in ("sht40", "ens160"):
                source = self.engine.sources[source_id]
                for metric in PROFILE["change_delta"]:
                    recent = [v[metric] for t, v in source.history if metric in v and self.engine.elapsed-30 < t <= self.engine.elapsed]
                    baseline = [v[metric] for t, v in source.history if metric in v and self.engine.elapsed-150 < t <= self.engine.elapsed-30]
                    if source.usable and len(recent) >= 12 and len(baseline) >= 48:
                        trends[metric] = {"recent_median": statistics.median(recent), "baseline_median": statistics.median(baseline),
                                          "delta": statistics.median(recent)-statistics.median(baseline)}
            answer = self.engine.episode("deterministic_environment_trend", {"trends": trends}, question="environment")
            return {**answer, "trends": trends}
        variant = self.engine.request.get("variant", "rules-v1")
        if variant == "rules-v1":
            raise Conflict("seleccionar A/B/C/D/E_visual para usar herramientas pesadas")
        if kind == "count_people" and self.actions.count_is_fresh() and not question.get("artifact_id"):
            return self.engine.episode("count_answered_by_cached_vision", {"observation": self.engine.sources["camera"].latest}, question="monitor")
        if kind == "count_people":
            self.actions.new_count_need()
        if kind == "describe_image" and variant != "E_visual":
            raise Conflict("la descripción directa requiere E_visual para separar el experimento")
        if kind == "interpret_context" and variant != "D":
            return self.engine.episode("interpretation_by_rules", question="monitor")
        snapshot = None
        source_run_id = question.get("source_run_id")
        if question.get("snapshot_id"):
            source_run_id = source_run_id or self.engine.run_id
            snapshot = self.store.snapshot(source_run_id, question["snapshot_id"])
        return self.actions.submit(kind, "explicit_request", snapshot=snapshot, artifact_id=question.get("artifact_id"),
                                   source_run_id=source_run_id)
