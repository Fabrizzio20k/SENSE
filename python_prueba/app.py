"""Ejecutar: uv run uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1."""

import asyncio
import json
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from context import PROFILE, decode_json, encoded
from experiment import active_readings, energy_estimate
from orchestrator import Conflict
from runtime import ROOT, Runtime, Settings


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class FaultStep(Command):
    source_id: Literal["sht40", "ens160", "ld2410c", "camera", "slm"]
    mode: Literal["disabled", "drop", "freeze", "error"]
    start_elapsed_s: float = Field(ge=0)
    duration_s: float = Field(gt=0)
    reason: str = Field(default="Plan experimental", max_length=300)


class RunCommand(Command):
    variant: Literal["rules-v1", "A", "B", "C", "D", "E_visual"] = "rules-v1"
    source_mode: Literal["live", "replay"] = "live"
    duration_s: float = Field(default=600, ge=1, le=7200)
    profile_id: Literal["rules-pilot-v1"] = "rules-pilot-v1"
    scenario_id: str = Field(default="exploration", min_length=1, max_length=100)
    block_id: str = Field(default="unassigned", max_length=100)
    space_id: str = Field(default="unassigned", max_length=100)
    phase: Literal["development", "pilot"] = "development"
    monitor_count: bool = False
    retain_images: bool = False
    overlap_verified: bool = False
    crossmodal_max_skew_s: float | None = Field(default=None, gt=0, le=60)
    fault_plan: list[FaultStep] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def consistent_plan(self):
        if self.monitor_count and self.variant not in ("A", "B", "C", "D"):
            raise ValueError("monitor_count requiere una variante de monitoreo A–D")
        for source in {step.source_id for step in self.fault_plan}:
            steps = sorted((step for step in self.fault_plan if step.source_id == source), key=lambda s: s.start_elapsed_s)
            previous_end = -1
            for step in steps:
                if step.start_elapsed_s < previous_end or step.start_elapsed_s+step.duration_s > self.duration_s:
                    raise ValueError("fallos solapados o fuera de la sesión")
                previous_end = step.start_elapsed_s+step.duration_s
        return self


class FaultCommand(Command):
    source_id: Literal["sht40", "ens160", "ld2410c", "camera", "slm"]
    mode: Literal["disabled", "drop", "freeze", "error"]
    start_after_s: float = Field(default=0, ge=0, le=7200)
    duration_s: float | None = Field(default=45, gt=0, le=7200)
    reason: str = Field(default="Prueba interactiva", max_length=300)


class Question(Command):
    type: Literal["presence", "environment", "monitor", "environment_trend", "count_people", "interpret_context", "describe_image"]
    artifact_id: str | None = Field(default=None, max_length=100)
    snapshot_id: str | None = Field(default=None, max_length=100)
    source_run_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def consistent_evidence(self):
        if self.artifact_id and self.type not in ("count_people", "describe_image"):
            raise ValueError("artifact_id solo corresponde a conteo o descripción de imagen")
        if (self.snapshot_id or self.source_run_id) and self.type != "interpret_context":
            raise ValueError("snapshot persistido solo corresponde a interpretación")
        if self.source_run_id and not self.snapshot_id:
            raise ValueError("source_run_id requiere snapshot_id")
        return self


class PowerCommand(Command):
    quantity: Literal["power", "energy_counter"] = "power"
    value: float = Field(ge=0, le=1000000)
    unit: Literal["W", "Wh", "kWh"] = "W"
    observed_elapsed_s: float | None = Field(default=None, ge=0)
    time_uncertainty_s: float = Field(default=3, ge=0, le=7200)
    instrument_id: str = Field(default="unspecified", min_length=1, max_length=100)
    observer_id: str = Field(default="operator-01", min_length=1, max_length=100)
    note: str = Field(default="", max_length=500)
    supersedes_reading_id: str | None = Field(default=None, max_length=100)


class Annotation(Command):
    label: str = Field(min_length=1, max_length=500)
    presence: bool | None = None
    count: int | None = Field(default=None, ge=0, le=10000)
    observed_elapsed_s: float | None = Field(default=None, ge=0)
    observer_id: str = Field(default="operator-01", max_length=100)


class Evaluation(Command):
    episode_id: str = Field(min_length=1, max_length=100)
    evaluator_id: str = Field(min_length=1, max_length=100)
    rubric_version: str = Field(default="pilot-v1", max_length=100)
    supported: bool | None = None
    correct: bool | None = None
    score: float | None = Field(default=None, ge=0, le=4)
    note: str = Field(default="", max_length=2000)


class IdleConfirmation(Command):
    confirmed_idle: Literal[True]
    note: str = Field(min_length=10, max_length=1000)


class CommandBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        is_image = scope["path"] == "/v1/artifacts"
        limit = 8*1024**2 if is_image else 32768
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > limit:
                return await JSONResponse({"detail": "cuerpo demasiado grande"}, status_code=413)(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        if body and not is_image:
            try:
                decode_json(body)
            except (ValueError, UnicodeError, RecursionError):
                return await JSONResponse({"detail": "JSON inválido, duplicado o no finito"}, status_code=400)(scope, receive, send)
        delivered = False

        async def replay_body():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_body, send)


def create_app(settings=None):
    @asynccontextmanager
    async def lifespan(application):
        runtime = Runtime(settings or Settings.environment())
        application.state.runtime = runtime
        try:
            await runtime.open()
            yield
        finally:
            await runtime.close()

    application = FastAPI(title="SENSE · prototipo de reglas", version="0.1.0", lifespan=lifespan)
    application.add_middleware(CommandBoundary)

    @application.middleware("http")
    async def boundary(request, call_next):
        if request.method in ("POST", "DELETE"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "origen no autorizado"}, status_code=403)
            length = request.headers.get("content-length")
            limit = 8*1024**2 if request.url.path == "/v1/artifacts" else 32768
            if length and (not length.isdigit() or int(length) > limit):
                return JSONResponse({"detail": "cuerpo demasiado grande"}, status_code=413)
        try:
            return await call_next(request)
        except KeyError:
            return JSONResponse({"detail": "registro no encontrado"}, status_code=404)
        except Conflict as error:
            return JSONResponse({"detail": str(error)}, status_code=409)
        except sqlite3.Error as error:
            await rt().fail(error)
            return JSONResponse({"detail": "fallo del registro; sesión detenida y no evaluable"}, status_code=503)

    def rt():
        return application.state.runtime

    def public_run(run_id):
        run = rt().store.run(run_id)
        rows = rt().store.db.execute("SELECT event_json FROM events WHERE run_id=? AND type='answer.validated' ORDER BY sequence DESC LIMIT 1", (run_id,)).fetchone()
        return {"run_id": run_id, "status": run["status"], "started_at": run["started_at"], "ended_at": run["ended_at"],
                "manifest": run["manifest"], "last_sequence": rt().store.last_sequence(run_id),
                "last_answer": json.loads(rows[0])["payload"] if rows else None,
                "closing_requested": bool(rt().engine.run_id == run_id and rt().actions.stop_reason),
                "urls": {"events": f"/v1/runs/{run_id}/events", "export": f"/v1/runs/{run_id}/export.zip"}}

    @application.get("/")
    async def index():
        return FileResponse(ROOT/"static/index.html")

    @application.get("/health")
    async def health():
        runtime = rt()
        dependencies = await runtime.dependency_health()
        data = {"status": "failed" if runtime.failure else ("degraded" if dependencies.get("status") not in ("ready", "not_required") else "ok"), "failure": runtime.failure,
                "mode": runtime.settings.mode, "mqtt_connected": runtime.input.connected if runtime.input else None,
                "active_run_id": runtime.engine.run_id, "profile": PROFILE,
                "camera": "configured" if runtime.settings.vision_model else "capture_available_detector_not_configured",
                "slm": dependencies.get("gemma", {"status": "not_required"}), "preflight": dependencies,
                "heavy_slot_reserved": runtime.store.flag("slm_busy") or runtime.store.flag("camera_busy"),
                "camera_stop_unconfirmed": runtime.actions.camera.failed_stop,
                "queued_jobs": len(runtime.actions.queue), "current_job": runtime.actions.current["job_id"] if runtime.actions.current else None}
        return JSONResponse(data, status_code=503 if runtime.failure else 200)

    @application.get("/v1/runs")
    async def runs():
        return [public_run(run["run_id"]) for run in rt().store.runs()]

    @application.post("/v1/runs", status_code=202)
    async def create(command: RunCommand, idempotency_key: str | None = Header(default=None, max_length=128)):
        run_id = await rt().admit(command.model_dump(), idempotency_key)
        return public_run(run_id)

    @application.get("/v1/runs/{run_id}")
    async def run(run_id: str):
        return public_run(run_id)

    @application.get("/v1/runs/{run_id}/metrics")
    async def metrics(run_id: str):
        return rt().store.summary(run_id)

    @application.get("/v1/context")
    async def context():
        engine = rt().engine
        return {"active": engine.run_id is not None, "run_id": engine.run_id,
                "snapshot": engine.snapshot() if engine.run_id else None}

    @application.get("/v1/runs/{run_id}/sources")
    async def sources(run_id: str):
        rt().engine.require_active(run_id)
        return rt().engine.snapshot()["sources"]

    @application.post("/v1/runs/{run_id}/questions")
    async def question(run_id: str, command: Question):
        rt().engine.require_active(run_id)
        return rt().ask(command.model_dump())

    @application.post("/v1/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        run = rt().store.run(run_id)
        if run["status"] == "running":
            rt().engine.require_active(run_id)
            await rt().actions.stop("cancelled", "explicit_cancel")
        return public_run(run_id)

    @application.post("/v1/runs/{run_id}/finish")
    async def finish(run_id: str):
        run = rt().store.run(run_id)
        if run["status"] == "running":
            rt().engine.require_active(run_id)
            await rt().actions.stop("completed", "explicit_finish")
        return public_run(run_id)

    @application.post("/v1/runs/{run_id}/faults")
    async def fault(run_id: str, command: FaultCommand):
        rt().engine.require_active(run_id)
        if rt().engine.request.get("fault_plan"):
            rt().engine.emit("protocol.deviation", {"reason": "manual_fault_outside_frozen_plan"})
        return rt().engine.add_fault(command.model_dump())

    @application.post("/v1/runs/{run_id}/faults/{fault_id}/clear")
    async def clear(run_id: str, fault_id: str):
        rt().engine.require_active(run_id)
        result = rt().engine.clear_fault(fault_id)
        if result["source_id"] == "camera":
            rt().actions.new_count_need()
        return result

    def history(run_id, kind):
        return [json.loads(r[0])["payload"] for r in rt().store.db.execute(
            "SELECT event_json FROM events WHERE run_id=? AND type=? ORDER BY sequence", (run_id, kind))]

    def observed_time(run_id, supplied):
        run = rt().store.run(run_id)
        if rt().engine.run_id == run_id:
            limit = rt().engine.elapsed
        else:
            if supplied is None:
                raise HTTPException(422, "sesión cerrada: indicar explícitamente el instante observado")
            events = rt().store.events(run_id, after=max(0, rt().store.last_sequence(run_id)-1))
            limit = events[-1]["elapsed_s"] if events else 0
        if supplied is not None and supplied > limit:
            raise HTTPException(422, "instante observado fuera del intervalo registrado de la sesión")
        return supplied if supplied is not None else limit, limit, run

    @application.post("/v1/runs/{run_id}/power-readings")
    async def power(run_id: str, command: PowerCommand):
        observed, limit, run = observed_time(run_id, command.observed_elapsed_s)
        if run["manifest"]["source_mode"] != "live":
            raise Conflict("no registrar W físicos sobre el reloj simulado de un replay")
        if (command.quantity == "power") != (command.unit == "W"):
            raise HTTPException(422, "unidad incompatible con quantity")
        readings = history(run_id, "power.reading_recorded")
        active = active_readings(readings)
        if command.supersedes_reading_id:
            previous = next((r for r in active if r["reading_id"] == command.supersedes_reading_id), None)
            if previous is None or not command.note.strip() or previous["quantity"] != command.quantity:
                raise HTTPException(422, "corrección requiere lectura activa de la misma cantidad y motivo")
        if command.quantity == "power" and any(r["quantity"] == "power" and r["observed_elapsed_s"] == observed
                                               and r["reading_id"] != command.supersedes_reading_id for r in active):
            raise Conflict("ya existe una lectura W activa para ese instante; usar corrección")
        reading = {**command.model_dump(), "reading_id": str(uuid4()), "observed_elapsed_s": observed,
                   "recorded_elapsed_s": time.monotonic()-rt().start_monotonic if rt().start_monotonic is not None and rt().engine.run_id == run_id else None,
                   "time_basis": "operator_elapsed" if command.observed_elapsed_s is not None else "entry_time_proxy",
                   "normalized_unit": "W" if command.quantity == "power" else "Wh",
                   "normalized_value": command.value*(1000 if command.unit == "kWh" else 1)}
        event = rt().store.append(run_id, "power.reading_recorded", reading, limit, rt().engine.boot_id)
        estimate = energy_estimate(readings+[reading], limit)
        rt().store.append(run_id, "metrics.updated", {"name": "estimated_energy", "value": estimate["estimated_Wh"],
                          "unit": "Wh", "method": estimate["method"], "details_json": estimate}, limit, rt().engine.boot_id)
        return {"event": event, "energy": estimate}

    @application.post("/v1/runs/{run_id}/annotations")
    async def annotation(run_id: str, command: Annotation):
        observed, limit, _ = observed_time(run_id, command.observed_elapsed_s)
        value = {**command.model_dump(), "annotation_id": str(uuid4()), "observed_elapsed_s": observed}
        return rt().store.append(run_id, "annotation.recorded", value, limit, rt().engine.boot_id)

    @application.post("/v1/runs/{run_id}/evaluations")
    async def evaluation(run_id: str, command: Evaluation):
        run = rt().store.run(run_id)
        found = any(json.loads(row[0]).get("episode_id") == command.episode_id for row in rt().store.db.execute(
            "SELECT event_json FROM events WHERE run_id=? AND type='answer.validated'", (run_id,)))
        if not found:
            raise HTTPException(422, "episodio sin respuesta registrada en esta sesión")
        last = rt().store.events(run_id, max(0, rt().store.last_sequence(run_id)-1))
        elapsed = last[-1]["elapsed_s"] if last else 0
        value = {**command.model_dump(), "evaluation_id": str(uuid4()), "run_status_at_entry": run["status"]}
        return rt().store.append(run_id, "evaluation.recorded", value, elapsed, rt().engine.boot_id, command.episode_id)

    @application.post("/v1/runtime/confirm-idle")
    async def confirm_idle(command: IdleConfirmation):
        if rt().actions.task and not rt().actions.task.done():
            raise Conflict("todavía existe una llamada local activa; no se libera el slot")
        if rt().actions.camera.failed_stop:
            raise Conflict("worker de cámara sin detención confirmada; no se libera el slot")
        previous = {"slm": rt().store.flag("slm_busy"), "camera": rt().store.flag("camera_busy")}
        confirmation = {"note": command.note, "confirmed_at": time.time(), "previous_reservation": previous,
                        "basis": "operator_attestation_not_remote_cancellation_ack"}
        rt().store.flag("slm_busy", None, write=True)
        rt().store.flag("camera_busy", None, write=True)
        rt().store.flag("last_idle_confirmation", confirmation, write=True)
        if rt().engine.run_id:
            rt().engine.emit("runtime.idle_confirmed", confirmation)
        return confirmation

    @application.post("/v1/runtime/prepare")
    async def prepare_runtime(command: Command):
        return await rt().prepare_dependencies()

    @application.post("/v1/artifacts", status_code=201)
    async def upload_artifact(request: Request):
        import io
        import warnings
        from PIL import Image, UnidentifiedImageError
        data = await request.body()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format not in ("JPEG", "PNG") or image.width*image.height > 16000000:
                        raise ValueError("solo JPEG/PNG de hasta 16 megapíxeles")
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    from PIL import ImageOps
                    normalized = ImageOps.exif_transpose(image).convert("RGB")
                    artifact_id = str(uuid4())
                    path = rt().artifact_dir/(artifact_id+".jpg")
                    normalized.save(path, "JPEG", quality=90)
                    size = list(normalized.size)
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
            raise HTTPException(422, str(error))
        from vision import file_hash
        metadata = {"origin": "explicit_upload", "image_size": size, "sha256": file_hash(path), "captured_at": None,
                    "time_basis": "unknown_capture_time", "retained": True}
        rt().store.artifact(artifact_id, path, metadata)
        return {"artifact_id": artifact_id, "metadata": metadata}

    @application.get("/v1/artifacts/{artifact_id}")
    async def image_artifact(artifact_id: str):
        from pathlib import Path
        artifact = rt().store.artifact(artifact_id)
        if not Path(artifact["path"]).is_file():
            raise HTTPException(404, "bytes eliminados; referencia histórica conservada")
        return FileResponse(artifact["path"], media_type="image/jpeg")

    @application.delete("/v1/artifacts/{artifact_id}")
    async def delete_artifact(artifact_id: str):
        from pathlib import Path
        artifact = rt().store.artifact(artifact_id)
        Path(artifact["path"]).unlink(missing_ok=True)
        return {"artifact_id": artifact_id, "bytes_deleted": True, "historical_reference_preserved": True}

    @application.get("/v1/runs/{run_id}/events")
    async def events(run_id: str, request: Request, after: int = 0, last_event_id: str | None = Header(default=None)):
        rt().store.run(run_id)
        cursor = after
        if last_event_id:
            try:
                identifier, number = last_event_id.rsplit(":", 1)
                if identifier != run_id:
                    raise ValueError()
                cursor = int(number)
            except ValueError:
                raise HTTPException(400, "Last-Event-ID inválido")
        if cursor < 0 or cursor > rt().store.last_sequence(run_id):
            raise HTTPException(400, "cursor fuera del historial")

        async def stream():
            nonlocal cursor
            heartbeat = time.monotonic()
            while not await request.is_disconnected():
                batch = rt().store.events(run_id, cursor, 100)
                for event in batch:
                    cursor = event["sequence"]
                    yield f"id: {event['event_id']}\nevent: {event['type']}\ndata: {encoded(event)}\n\n"
                if not batch and rt().store.run(run_id)["status"] != "running":
                    yield "event: stream.closed\ndata: {}\n\n"
                    return
                if time.monotonic()-heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(.1 if batch else .25)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @application.get("/v1/runs/{run_id}/exports/{table}.csv")
    async def csv_export(run_id: str, table: str):
        from store import TABLES
        if table not in TABLES:
            raise HTTPException(404, "tabla no soportada")
        try:
            data = rt().store.export(run_id)[f"{table}.csv"]
        except ValueError as error:
            raise HTTPException(413, str(error))
        return Response(data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{table}.csv"'})

    @application.get("/v1/runs/{run_id}/export.zip")
    async def zip_export(run_id: str):
        try:
            data = rt().store.zip_export(run_id)
        except ValueError as error:
            raise HTTPException(413, str(error))
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="sense-{run_id}.zip"'})

    return application


app = create_app()
