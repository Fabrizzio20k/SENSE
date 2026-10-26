#!/usr/bin/env python3
"""Panel local para sensores, cámara y modelos de la Raspberry Pi."""
from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import paho.mqtt.client as mqtt
import psutil
import requests
from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from sense.contracts import utc_now
from sense.inference import request_completion
from sense.service import ExperimentService

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
PREPARE_IMAGE = PUBLIC / "prepare_image.png"
YOLO_MODEL = ROOT / "yolo26n.pt"
YOLO_NCNN = ROOT / "yolo26n_ncnn_model"
LITERT_URL = os.environ.get("LITERT_URL", "http://127.0.0.1:8080/v1/chat/completions")
LITERT_MODEL = os.environ.get("LITERT_MODEL", "gemma4-e2b")
MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "rustio/rpi5-01/telemetry")

app = Flask(__name__, static_folder=str(PUBLIC), static_url_path="/public")
app.config["MAX_CONTENT_LENGTH"] = 65536
lock = threading.Lock()
worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rustio-work")
state = {
    "telemetry": {},
    "telemetry_at": None,
    "phases": {
        "yolo": {"status": "waiting", "detail": "Pendiente"},
        "text": {"status": "waiting", "detail": "Pendiente"},
        "vision": {"status": "waiting", "detail": "Pendiente"},
    },
    "tasks": {},
    "sandbox_busy": False,
}
yolo = None
last_capture: bytes | None = None
experiments: ExperimentService | None = None
service_lock = threading.Lock()
MODEL_NOT_RUNNING = "El modelo no está ejecutándose. Inicia run.sh y vuelve a intentar."


def set_phase(name: str, status: str, detail: str) -> None:
    with lock:
        state["phases"][name] = {"status": status, "detail": detail}


def set_task(name: str, status: str, detail: str, seconds: float | None = None) -> None:
    with lock:
        state["tasks"].pop(name, None)
        state["tasks"][name] = {"status": status, "detail": detail, "seconds": seconds}


def error_detail(error: Exception) -> str:
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return MODEL_NOT_RUNNING
    if isinstance(error, ModuleNotFoundError) and error.name == "pnnx":
        return "Falta pnnx para exportar NCNN. Ejecuta: uv pip install pnnx"
    return str(error)


def completion(prompt: str, image: Path | bytes | None = None) -> str:
    return request_completion(LITERT_URL, LITERT_MODEL, prompt, image)["content"]


def count_people(image: Path | bytes) -> int:
    global yolo
    if yolo is None:
        raise RuntimeError("YOLO todavía no está listo")
    if isinstance(image, bytes):
        from PIL import Image

        image = Image.open(io.BytesIO(image))
    results = yolo(str(image) if isinstance(image, Path) else image, imgsz=640, classes=[0], conf=0.15, device="cpu", verbose=False)
    boxes = results[0].boxes
    return 0 if boxes is None else len(boxes)


def warm_yolo() -> None:
    global yolo
    set_phase("yolo", "loading", "Exportando o cargando el modelo NCNN…")
    try:
        from ultralytics import YOLO

        if YOLO_NCNN.exists():
            yolo = YOLO(str(YOLO_NCNN))
        else:
            model = YOLO(str(YOLO_MODEL))
            exported = model.export(format="ncnn", imgsz=320, quantize=16)
            yolo = YOLO(str(exported))
        people = count_people(PREPARE_IMAGE)
        set_phase("yolo", "ready", f"Listo; imagen de prueba: {people} persona(s).")
    except Exception as error:
        set_phase("yolo", "error", error_detail(error))


def warm_text() -> None:
    set_phase("text", "loading", "Calentando Gemma de texto…")
    try:
        answer = completion("Responde exactamente OK.")
        set_phase("text", "ready", f"Listo; respondió: {answer[:80]}")
    except Exception as error:
        set_phase("text", "error", error_detail(error))


def warm_vision() -> None:
    set_phase("vision", "loading", "Calentando Gemma con imagen…")
    try:
        answer = completion("¿Cuántas personas hay? Responde solo con el número.", PREPARE_IMAGE)
        set_phase("vision", "ready", f"Listo; prueba: {answer[:80]}")
    except Exception as error:
        set_phase("vision", "error", error_detail(error))


def warm_all() -> None:
    warm_yolo()
    warm_text()
    warm_vision()


def capture_evidence() -> tuple[bytes, str]:
    from picamera2 import Picamera2

    temporary = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    temporary.close()
    photo = Path(temporary.name)
    camera = None
    try:
        camera = Picamera2()
        # YOLO procesa a 640 px; 1280×960 conserva detalle útil y evita transferir una foto de 8 MP.
        camera.configure(camera.create_still_configuration(main={"size": (1280, 960)}))
        camera.start()
        time.sleep(2)
        captured_at = utc_now()
        camera.capture_file(str(photo))
        return photo.read_bytes(), captured_at
    finally:
        try:
            if camera is not None:
                try:
                    camera.stop()
                finally:
                    camera.close()
        finally:
            photo.unlink(missing_ok=True)


def capture() -> bytes:
    global last_capture
    image, _ = capture_evidence()
    with lock:
        last_capture = image
    return image


def current_capture() -> bytes:
    with lock:
        image = last_capture
    if image is None:
        raise RuntimeError("Primero toma una foto.")
    return image


def timed_task(name: str, action) -> None:
    set_task(name, "loading", "En proceso…")
    started = time.monotonic()
    try:
        detail = action()
        set_task(name, "ready", detail, time.monotonic() - started)
    except Exception as error:
        set_task(name, "error", error_detail(error), time.monotonic() - started)


def enqueue_sandbox_task(name: str, action) -> str | None:
    with lock:
        if experiments is not None and experiments.reserved.is_set():
            return "Finaliza la medición y espera a que terminen sus workers antes de usar el sandbox."
        if not all(phase["status"] == "ready" for phase in state["phases"].values()):
            return "El sandbox estará disponible cuando terminen las tres preparaciones."
        if state["sandbox_busy"]:
            return "Ya hay una operación en proceso."
        state["sandbox_busy"] = True

    def run() -> None:
        try:
            timed_task(name, action)
        finally:
            with lock:
                state["sandbox_busy"] = False

    worker.submit(run)
    return None


def mqtt_message(_client, _userdata, message) -> None:
    if len(message.payload) > 65536:
        return
    try:
        def invalid_constant(value):
            raise ValueError("Número JSON no finito: " + value)

        telemetry = json.loads(message.payload, parse_constant=invalid_constant)
    except (ValueError, UnicodeDecodeError):
        return
    if not isinstance(telemetry, dict):
        return
    received, wall = time.monotonic(), time.time()
    with lock:
        state["telemetry"] = telemetry
        state["telemetry_at"] = wall
    if experiments is not None:
        experiments.ingest(telemetry, received, wall)


def get_experiments() -> ExperimentService:
    global experiments
    with service_lock:
        if experiments is None:
            def readiness():
                with lock:
                    return {key: value["status"] for key, value in state["phases"].items()}

            experiments = ExperimentService(
                ROOT, Path(os.environ.get("SENSE_DATA_DIR", str(ROOT / "data"))),
                Path(os.environ.get("SENSE_CONFIG", str(ROOT / "sense" / "pilot.yaml"))),
                capture_evidence, count_people,
                lambda prompt, image, **options: request_completion(LITERT_URL, LITERT_MODEL, prompt, image, temperature=0, **options),
                LITERT_MODEL, readiness,
            )
        return experiments


def start_mqtt() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = mqtt_message
    client.on_connect = lambda c, _u, _f, _r, _p: c.subscribe(MQTT_TOPIC)
    try:
        client.connect_async(MQTT_HOST, 1883, 60)
        client.loop_start()
    except OSError:
        pass


def snapshot() -> dict:
    with lock:
        payload = dict(state)
        payload["phases"] = dict(state["phases"])
        payload["tasks"] = dict(state["tasks"])
        payload["sandbox"] = {
            "ready": all(phase["status"] == "ready" for phase in state["phases"].values()),
            "busy": state["sandbox_busy"],
        }
        payload["has_capture"] = last_capture is not None
    payload["system"] = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
        "memory_used_mb": round(psutil.virtual_memory().used / 1024 / 1024),
    }
    payload["measurement"] = experiments.snapshot() if experiments is not None else {"running": False, "enabled_modes": list("ABCDE")}
    return payload


@app.post("/api/experiments/start")
def start_experiment():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("mode") not in list("ABCDE"):
        return jsonify(error="Selecciona un modo A–E."), 400
    for name in ("session_id", "scenario_id"):
        if name in body and (not isinstance(body[name], str) or not 1 <= len(body[name]) <= 100):
            return jsonify(error=f"{name} debe contener entre 1 y 100 caracteres."), 400
    try:
        service = get_experiments()
        with lock:
            if state["sandbox_busy"]:
                return jsonify(error="Espera a que termine la operación del sandbox."), 409
            service.reserve()
        run = service.call("start", body)
        return jsonify(run_id=run["run_id"]), 202
    except (ValueError, OSError, TimeoutError) as error:
        return jsonify(error=str(error)), 409


@app.post("/api/experiments/stop")
def stop_experiment():
    try:
        return jsonify(get_experiments().call("stop")), 202
    except (ValueError, TimeoutError) as error:
        return jsonify(error=str(error)), 409


@app.post("/api/experiments/query")
def query_experiment():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Se requiere question_id."), 400
    try:
        return jsonify(get_experiments().call("query", body)), 202
    except (ValueError, TimeoutError) as error:
        return jsonify(error=str(error)), 409


@app.post("/api/experiments/presence")
def set_experiment_presence():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("mode") not in ("auto", "manual"):
        return jsonify(error="Usa mode auto o manual."), 400
    detected = None if body["mode"] == "auto" else body.get("detected")
    if body["mode"] == "manual" and type(detected) is not bool:
        return jsonify(error="El modo manual requiere detected booleano."), 400
    try:
        return jsonify(get_experiments().call("presence", {"detected": detected})), 202
    except (ValueError, TimeoutError) as error:
        return jsonify(error=str(error)), 409


@app.get("/api/experiments")
def experiment_history():
    return jsonify(runs=get_experiments().log.runs())


@app.get("/api/experiments/<run_id>")
def experiment_details(run_id):
    log = get_experiments().log
    run = log.run(run_id)
    if run is None:
        return jsonify(error="Ejecución no encontrada."), 404
    try:
        after = max(0, int(request.args.get("after", 0)))
    except ValueError:
        return jsonify(error="Cursor inválido."), 400
    return jsonify(run=run, events=log.events(run_id, after))


@app.get("/api/experiments/<run_id>/export")
def export_experiment(run_id):
    log = get_experiments().log
    if log.run(run_id) is None:
        return jsonify(error="Ejecución no encontrada."), 404
    return Response(log.export(run_id), mimetype="application/x-ndjson",
                    headers={"Content-Disposition": f'attachment; filename="sense-{run_id}.ndjson"'})


@app.post("/api/experiments/<run_id>/human-records")
def record_ground_truth(run_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("kind") not in ("GROUND_TRUTH", "EXTERNAL_ENERGY"):
        return jsonify(error="Usa kind GROUND_TRUTH o EXTERNAL_ENERGY y un payload separado."), 400
    payload = body.get("payload")
    if not isinstance(payload, dict) or len(json.dumps(payload)) > 10000:
        return jsonify(error="payload debe ser un objeto de hasta 10 kB."), 400
    log = get_experiments().log
    if log.run(run_id) is None:
        return jsonify(error="Ejecución no encontrada."), 404
    try:
        from sense.context import timestamp

        timestamp(payload.get("observed_at"))
        if body["kind"] == "EXTERNAL_ENERGY":
            value = payload.get("value")
            if type(value) not in (int, float) or not 0 <= value < float("inf") or payload.get("unit") not in ("Wh", "J") or payload.get("scope") != "whole_run":
                raise ValueError("Energía externa: valor finito no negativo, unidad Wh o J y scope whole_run.")
        elif not isinstance(payload.get("region"), str) or not payload["region"]:
            raise ValueError("El ground truth debe indicar su región.")
        elif "visible_people" in payload and (type(payload["visible_people"]) is not int or payload["visible_people"] < 0):
            raise ValueError("visible_people debe ser un entero no negativo.")
        record_id = log.human_record(run_id, body["kind"], payload)
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    return jsonify(record_id=record_id), 201


@app.get("/")
def index():
    return send_from_directory(PUBLIC, "index.html")


@app.get("/events")
def events():
    def stream():
        while True:
            yield f"data: {json.dumps(snapshot())}\n\n"
            time.sleep(1)
    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.route("/api/capture", methods=["GET", "POST"])
def camera():
    if request.method == "GET":
        try:
            return send_file(io.BytesIO(current_capture()), mimetype="image/jpeg", max_age=0)
        except RuntimeError:
            return jsonify(error="No hay foto disponible."), 404
    error = enqueue_sandbox_task("capture", lambda: (capture(), "Foto lista.")[1])
    if error:
        return jsonify(error=error), 409
    return jsonify(ok=True), 202


@app.post("/api/yolo")
def test_yolo():
    error = enqueue_sandbox_task("yolo", lambda: f"{count_people(current_capture())} persona(s) detectada(s).")
    if error:
        return jsonify(error=error), 409
    return jsonify(ok=True), 202


@app.post("/api/chat")
def chat():
    prompt = request.get_json(silent=True) or {}
    question = str(prompt.get("question", ""))[:1000].strip()
    if not question:
        return jsonify(error="Escribe una pregunta."), 400
    error = enqueue_sandbox_task("chat", lambda: completion(question))
    if error:
        return jsonify(error=error), 409
    return jsonify(ok=True), 202


@app.post("/api/vision")
def vision_chat():
    prompt = request.get_json(silent=True) or {}
    question = str(prompt.get("question", ""))[:1000].strip()
    if not question:
        return jsonify(error="Escribe una pregunta sobre la foto."), 400
    error = enqueue_sandbox_task("vision", lambda: completion(question, current_capture()))
    if error:
        return jsonify(error=error), 409
    return jsonify(ok=True), 202


if __name__ == "__main__":
    PUBLIC.mkdir(exist_ok=True)
    start_mqtt()
    worker.submit(warm_all)
    try:
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:
        if experiments is not None:
            experiments.close()
