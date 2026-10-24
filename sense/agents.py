from __future__ import annotations

import json
import time

from .contracts import Command, Snapshot, identifier, utc_now
from .policy import QUESTIONS


class VisionAgent:
    def __init__(self, capture, detector):
        self.capture, self.detector = capture, detector

    def execute(self, command: Command, max_bytes: int) -> dict:
        started = time.monotonic()
        image, captured_at = self.capture()
        capture_seconds = time.monotonic() - started
        if len(image) > max_bytes:
            raise ValueError("La imagen excede el límite de memoria autorizado.")
        infer = time.monotonic()
        count = self.detector(image)
        if type(count) is not int or count < 0:
            raise ValueError("YOLO devolvió un conteo inválido.")
        return {"count": count, "image_id": identifier(), "captured_at": captured_at, "image": image,
                "region": command.parameters["region"], "capture_seconds": capture_seconds,
                "inference_seconds": time.monotonic() - infer, "quality": "uncalibrated_camera_coverage"}


class InterpretationAgent:
    def __init__(self, completion, model: str):
        self.completion, self.model = completion, model

    def prompt(self, question: str, snapshot: Snapshot, image_id: str | None) -> str:
        document = snapshot.document()
        # No se envían historiales completos ni imágenes al intérprete textual.
        evidence = {"snapshot_id": snapshot.snapshot_id, "observations": document["observations"],
                    "environment_events": document["environment_events"][-4:], "image_id": image_id}
        return (
            "Eres el intérprete contextual SENSE. Devuelve únicamente JSON, sin Markdown. "
            "No identifiques personas ni uses reconocimiento facial. No atribuyas causalidad a coincidencias. "
            "No reemplaces conteos YOLO ni inventes mediciones. Las descripciones de la imagen son inferencias. "
            "Recomendaciones solo no críticas. Usa este esquema exacto: "
            '{"observed_facts":[{"evidence_id":"id de observación","value":0}],'
            '"inferences":["texto"],"unknowns":["texto"],"recommendations":["texto"],'
            '"evidence_references":["id de observación o image_id"]}. '
            "Los observed_facts deben copiar exactamente valores de observaciones VALID del snapshot. "
            "Usa listas vacías si no hay evidencia. Pregunta: " + QUESTIONS[question] + "\n" + json.dumps(evidence)
        )

    def execute(self, command: Command, snapshot: Snapshot, image: bytes | None, config: dict, prompt: str) -> dict:
        started_at = utc_now()
        started_monotonic = time.monotonic()
        response = self.completion(prompt, image, max_tokens=config["max_tokens"], timeout=config["timeout_seconds"])
        result = {"interpretation_id": identifier(), "request_id": command.command_id, "snapshot_id": snapshot.snapshot_id,
                  "image_id": command.parameters.get("image_id"), "model_id": self.model,
                  "runtime_model_id": response.get("model", self.model),
                  "started_at": started_at, "completed_at": utc_now(), "question_id": command.parameters["question_id"],
                  "inference_seconds": time.monotonic() - started_monotonic,
                  "raw_output": response["content"], "tokens": response.get("usage"), "validation_status": "REJECTED"}
        try:
            parsed = json.loads(response["content"])
            fields = ("observed_facts", "inferences", "unknowns", "recommendations", "evidence_references")
            if not isinstance(parsed, dict) or any(not isinstance(parsed.get(field), list) for field in fields):
                raise ValueError("Contrato de interpretación incompleto.")
            observations = {value["observation_id"]: value for value in snapshot.document()["observations"].values()}
            references = set(observations)
            if result["image_id"]:
                references.add(result["image_id"])
            if not parsed["evidence_references"] or any(not isinstance(ref, str) or ref not in references for ref in parsed["evidence_references"]):
                raise ValueError("Referencias de evidencia ausentes o desconocidas.")
            for fact in parsed["observed_facts"]:
                if not isinstance(fact, dict):
                    raise ValueError("Hecho observado inválido.")
                evidence = observations.get(fact.get("evidence_id"))
                if not evidence or evidence["status"] != "VALID" or type(fact.get("value")) is not type(evidence["value"]) or fact["value"] != evidence["value"]:
                    raise ValueError("El modelo alteró o inventó una observación.")
                if fact["evidence_id"] not in parsed["evidence_references"]:
                    raise ValueError("Hecho sin referencia declarada.")
            if any(not isinstance(item, str) or len(item) > 2000 for field in ("inferences", "unknowns", "recommendations") for item in parsed[field]):
                raise ValueError("La interpretación contiene texto inválido.")
            if result["question_id"] == "Q7" and result["image_id"] not in parsed["evidence_references"]:
                raise ValueError("La descripción multimodal debe referenciar su imagen.")
            result.update({field: parsed[field] for field in fields}, validation_status="VALIDATED")
        except (ValueError, TypeError) as error:
            result["validation_error"] = str(error)
        return result
