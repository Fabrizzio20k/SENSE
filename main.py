#!/usr/bin/env python3
"""Panel local para sensores, cámara y modelos de la Raspberry Pi."""
from __future__ import annotations

import base64
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
    content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
    if image:
        image_bytes = image.read_bytes() if isinstance(image, Path) else image
        mime_type = "image/png" if isinstance(image, Path) else "image/jpeg"
        encoded = base64.b64encode(image_bytes).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}})
    response = requests.post(
        LITERT_URL,
        json={"model": LITERT_MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": 64},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


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


def capture() -> bytes:
    global last_capture
    from picamera2 import Picamera2

    temporary = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    temporary.close()
    photo = Path(temporary.name)
    camera = Picamera2()
    try:
        # YOLO procesa a 640 px; 1280×960 conserva detalle útil y evita transferir una foto de 8 MP.
        camera.configure(camera.create_still_configuration(main={"size": (1280, 960)}))
        camera.start()
        time.sleep(2)
        camera.capture_file(str(photo))
    finally:
        camera.stop()
        camera.close()
    try:
        image = photo.read_bytes()
    finally:
        photo.unlink(missing_ok=True)
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
    try:
        telemetry = json.loads(message.payload)
    except json.JSONDecodeError:
        return
    with lock:
        state["telemetry"] = telemetry
        state["telemetry_at"] = time.time()


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
    return payload


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
    app.run(host="0.0.0.0", port=5000, threaded=True)
