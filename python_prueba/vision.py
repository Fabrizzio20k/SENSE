"""Un proceso posee Picamera2 y NCNN; sin descargas ni comandos shell."""

import asyncio
import hashlib
import multiprocessing
import time
import traceback
from pathlib import Path


def file_hash(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def validate_ncnn(model_dir, input_size):
    """La preparación y el worker comparten el mismo contrato de artefacto."""
    import yaml
    model_dir = Path(model_dir)
    parameters = sorted(model_dir.glob("*.param"))
    weights = sorted(model_dir.glob("*.bin"))
    metadata_file = model_dir/"metadata.yaml"
    if not model_dir.is_dir() or not parameters or not weights or not metadata_file.is_file():
        raise ValueError(f"exportación NCNN incompleta en {model_dir}: faltan .param, .bin o metadata.yaml")
    files = [*parameters, *weights, metadata_file]
    if any(not path.is_file() or path.stat().st_size == 0 for path in files):
        raise ValueError(f"exportación NCNN contiene archivos vacíos en {model_dir}")
    try:
        with metadata_file.open(encoding="utf-8") as handle:
            metadata = yaml.safe_load(handle)
    except yaml.YAMLError as error:
        raise ValueError("metadata.yaml no es YAML válido") from error
    if not isinstance(metadata, dict):
        raise ValueError("metadata.yaml debe contener un objeto")
    dimensions = metadata.get("imgsz")
    if type(dimensions) is int:
        dimensions = [dimensions, dimensions]
    if dimensions != [input_size, input_size]:
        raise ValueError(f"imgsz NCNN {dimensions} no coincide con el solicitado {input_size}")
    names = metadata.get("names", {})
    label = names[0] if isinstance(names, list) and names else (names.get(0, names.get("0")) if isinstance(names, dict) else None)
    if label != "person":
        raise ValueError("la exportación no identifica person como clase 0")
    return {"status": "artifact_validated", "model_dir": str(model_dir.resolve()), "model_input_size": input_size,
            "files_sha256": {path.name: file_hash(path) for path in files}, "inference_verified": False}


def validate_count_capture(path, result):
    """Comprobar el archivo producido y el contrato del conteo antes de admitir sesiones."""
    from PIL import Image
    with Image.open(path) as photo:
        photo.load()
        if photo.format != "JPEG" or list(photo.size) != result.get("image_size"):
            raise ValueError("la foto de comprobación no coincide con el resultado del worker")
    count, boxes = result.get("visible_person_count"), result.get("boxes")
    if type(count) is not int or count < 0 or not isinstance(boxes, list) or count != len(boxes):
        raise ValueError("el detector no devolvió un conteo válido")
    if not result.get("model_ref") or file_hash(path) != result.get("sha256"):
        raise ValueError("hash de foto o referencia del detector inválidos")


def fuse_boxes(boxes, threshold):
    """Fusión entre mosaicos; utiliza el argumento, no un umbral global."""
    kept = []
    for box in sorted(boxes, key=lambda b: b[4], reverse=True):
        x1, y1, x2, y2, _ = box
        area = max(0, x2-x1)*max(0, y2-y1)
        duplicate = False
        for other in kept:
            intersection = max(0, min(x2, other[2])-max(x1, other[0]))*max(0, min(y2, other[3])-max(y1, other[1]))
            union = area+max(0, other[2]-other[0])*max(0, other[3]-other[1])-intersection
            if union and intersection/union > threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(box)
    return kept


def tile_origins(length, tile, overlap):
    if length <= tile:
        return [0]
    return sorted(set([*range(0, length-tile+1, tile-overlap), length-tile]))


def _worker(connection, config):
    import os
    import math
    os.environ["YOLO_AUTOINSTALL"] = "false"
    model = None
    model_ref = None
    while True:
        try:
            job = connection.recv()
        except EOFError:
            return
        camera = None
        try:
            from PIL import Image
            if job["kind"] == "count" and model is None:
                import ncnn  # Fallar explícitamente antes de que Ultralytics intente instalarlo.
                from ultralytics import YOLO
                model_dir = Path(config["model_dir"])
                validated = validate_ncnn(model_dir, config["input_size"])
                model = YOLO(str(model_dir), task="detect")
                model_ref = validated["files_sha256"]
            metadata = {}
            if job.get("input_path"):
                image = Image.open(job["input_path"]).convert("RGB")
                timing = {"captured_at": None, "capture_monotonic_ns": None, "time_basis": "uploaded_image_unknown_capture_time"}
            else:
                from picamera2 import Picamera2
                from store import utc_now
                camera = Picamera2()
                camera.configure(camera.create_still_configuration(main={"size": tuple(config["capture_size"]), "format": "RGB888"}))
                camera.start()
                time.sleep(config["settle_s"])
                requested_at = utc_now()
                anchor_mono = time.monotonic_ns()
                anchor_boot = time.clock_gettime_ns(time.CLOCK_BOOTTIME) if hasattr(time, "CLOCK_BOOTTIME") else None
                capture = camera.capture_request(flush=True)
                try:
                    array = capture.make_array("main")
                    metadata = capture.get_metadata()
                    # Picamera2 RGB888 se presenta en orden BGR en el array de libcamera.
                    image = Image.fromarray(array[:, :, ::-1].copy())
                finally:
                    capture.release()
                returned_mono = time.monotonic_ns()
                timing = {"capture_requested_at": requested_at, "capture_returned_at": utc_now(),
                          "captured_at": None, "capture_monotonic_ns": returned_mono,
                          "time_basis": "capture_return_receipt_proxy", "sensor_timestamp_ns": metadata.get("SensorTimestamp")}
                if config["clock_is_boottime"] and anchor_boot is not None and metadata.get("SensorTimestamp") is not None:
                    from datetime import datetime, timedelta
                    sensor_delta_ns = int(metadata["SensorTimestamp"])-anchor_boot
                    timing.update(capture_monotonic_ns=anchor_mono+sensor_delta_ns,
                                  captured_at=(datetime.fromisoformat(requested_at)+timedelta(microseconds=sensor_delta_ns/1000)).isoformat(),
                                  time_basis="sensor_boottime_mapping_declared_by_operator")
            if camera:
                camera.stop()
                camera.close()
                camera = None
            image.thumbnail((config["max_image_side"], config["max_image_side"]))
            size = image.size
            image.save(job["output_path"], "JPEG", quality=90)
            result = {"artifact_id": job["artifact_id"], "sha256": file_hash(job["output_path"]), "image_size": list(size),
                      "scope_id": config["scope_id"], "timing": timing,
                      "capture_metadata": {k: metadata.get(k) for k in ("SensorTimestamp", "ExposureTime", "AnalogueGain", "FrameDuration")},
                      "quality_flags": ["detector_not_calibrated", "occlusions_not_measured"]}
            if job["kind"] == "count":
                boxes = []
                tile = config["tile_size"]
                positions = [(0, 0)] if not tile else [(x, y) for y in tile_origins(size[1], tile, config["tile_overlap"])
                                                       for x in tile_origins(size[0], tile, config["tile_overlap"])]
                if len(positions) > 64:
                    raise ValueError("perfil excede 64 mosaicos")
                for x, y in positions:
                    view = image if not tile else image.crop((x, y, min(x+tile, size[0]), min(y+tile, size[1])))
                    prediction = model.predict(view, imgsz=config["input_size"], conf=config["confidence"], classes=[0], device="cpu", verbose=False)[0]
                    if prediction.boxes is not None:
                        for box, confidence in zip(prediction.boxes.xyxy.tolist(), prediction.boxes.conf.tolist()):
                            if not all(math.isfinite(value) for value in [*box, confidence]) or not 0 <= confidence <= 1:
                                raise ValueError("salida del detector contiene coordenadas o scores inválidos")
                            boxes.append([box[0]+x, box[1]+y, box[2]+x, box[3]+y, float(confidence)])
                            if len(boxes) > 5000:
                                raise ValueError("salida excede 5000 cajas; revisar perfil de mosaicos")
                fused = fuse_boxes(boxes, config["fusion_iou"]) if tile else boxes
                result.update(visible_person_count=len(fused), boxes=fused, raw_boxes=boxes, coordinate_space="saved_image_pixels",
                              tile_count=len(positions), model_input_size=config["input_size"], model_ref=model_ref)
            connection.send({"ok": True, "result": result})
        except Exception as error:
            connection.send({"ok": False, "error": f"{type(error).__name__}: {error}", "trace": traceback.format_exc(limit=5)})
        finally:
            if camera:
                camera.stop()
                camera.close()


class CameraWorker:
    def __init__(self, config):
        self.config = config
        self.process = self.connection = None
        self.lock = asyncio.Lock()
        self.failed_stop = False

    async def run(self, job, timeout):
        async with self.lock:
            if self.process is None or not self.process.is_alive():
                await self.stop()
                context = multiprocessing.get_context("spawn")
                parent, child = context.Pipe()
                self.process = context.Process(target=_worker, args=(child, self.config), daemon=True)
                self.process.start()
                child.close()
                self.connection = parent
            self.connection.send(job)
            deadline = time.monotonic()+timeout
            try:
                while not self.connection.poll():
                    if not self.process.is_alive():
                        raise RuntimeError("worker de cámara terminó sin resultado")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("plazo de cámara/detector agotado")
                    await asyncio.sleep(.05)
                message = self.connection.recv()
                if not message["ok"]:
                    raise RuntimeError(message["error"])
                return message["result"]
            except BaseException:
                await self.stop()
                raise

    async def stop(self):
        if self.process:
            if self.process.is_alive():
                self.process.terminate()
            await asyncio.to_thread(self.process.join, 3)
            if self.process.is_alive():
                self.process.kill()
                await asyncio.to_thread(self.process.join, 3)
            if self.process.is_alive():
                self.failed_stop = True
                raise RuntimeError("no se confirmó la detención del worker; recurso ocupado")
            self.process.close()
            self.process = None
            self.failed_stop = False
        if self.connection:
            self.connection.close()
            self.connection = None
