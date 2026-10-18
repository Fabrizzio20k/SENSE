"""Preparación NCNN anterior al experimento; se ejecuta en un proceso separado."""

import argparse
import fcntl
import importlib.metadata
import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from store import utc_now
from vision import file_hash, validate_ncnn


@contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def ensure_yolo(model_dir, weights, input_size):
    target, weights = Path(model_dir).resolve(), Path(weights).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if weights == target or target in weights.parents:
        raise ValueError("los pesos .pt deben estar fuera del directorio de exportación")
    with (target.parent/("."+target.name+".prepare.lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.exists():
            return {**validate_ncnn(target, input_size), "preparation": "reused_existing_export"}
        if not weights.is_file() and weights.name != "yolo26n.pt":
            raise FileNotFoundError(f"no existen los pesos locales {weights}; solo yolo26n.pt admite descarga automática")
        started = time.monotonic()
        # Solo este subproceso puede descargar pesos; las dependencias se instalan antes.
        os.environ["YOLO_AUTOINSTALL"] = "false"
        import ncnn
        from ultralytics import YOLO
        with tempfile.TemporaryDirectory(prefix=".yolo-prepare-", dir=target.parent) as temporary:
            workspace = Path(temporary)
            staged_weights = workspace/weights.name
            if weights.is_file():
                shutil.copy2(weights, staged_weights)
            with working_directory(workspace):
                model = YOLO(weights.name)
                exported = Path(model.export(format="ncnn", imgsz=input_size, quantize=16, device="cpu")).resolve()
            validate_ncnn(exported, input_size)
            if not staged_weights.is_file():
                raise RuntimeError("Ultralytics no dejó los pesos en el área de preparación esperada")
            report = {"preparation": "exported_before_startup", "format": "ncnn", "imgsz": input_size, "quantize": 16,
                      "weights_sha256": file_hash(staged_weights), "prepared_at": utc_now(),
                      "duration_s": time.monotonic()-started, "ultralytics_version": importlib.metadata.version("ultralytics"),
                      "ncnn_version": importlib.metadata.version("ncnn"), "measurement_scope": "setup_outside_experimental_runs"}
            if not weights.exists():
                weights.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=weights.parent, prefix=".weights-", delete=False) as cached:
                    cached_path = Path(cached.name)
                try:
                    shutil.copy2(staged_weights, cached_path)
                    os.link(cached_path, weights)
                except FileExistsError:
                    pass
                finally:
                    cached_path.unlink(missing_ok=True)
            (exported/"preparation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            if target.exists():
                raise FileExistsError(f"el destino apareció durante la conversión; no se sobrescribe: {target}")
            exported.rename(target)
        return {**validate_ncnn(target, input_size), **report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--input-size", type=int, choices=(320, 640), required=True)
    args = parser.parse_args()
    try:
        report = ensure_yolo(args.model_dir, args.weights, args.input_size)
    except Exception as error:
        parser.exit(1, f"Preparación YOLO fallida: {error}\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
