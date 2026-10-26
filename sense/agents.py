from __future__ import annotations

import json
import time

from .contracts import Command, Snapshot, identifier, utc_now
from .policy import QUESTIONS


def parse_json_object(text: str) -> dict:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Clave JSON duplicada: {key}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=reject_duplicates)


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
        evidence = {
            key: value["value"] if value["status"] == "VALID" else None
            for key, value in document["observations"].items()
        }
        events = [event["event_type"] for event in document["environment_events"][-4:]]
        if question == "Q6":
            event_text = " y ".join(events) if events else "sin eventos ambientales confirmados"
            return f"Valores: <presence>={evidence.get('presence')}; <count>={evidence.get('count')}; <events>={event_text}."
        return "Q7. Contexto: " + json.dumps({"observations": evidence, "events": events}, separators=(",", ":"))

    @staticmethod
    def system_prompt(question: str) -> str | None:
        if question == "Q7":
            return ('JSON: {"inferences":[""],"unknowns":[""],"recommendations":[""]}. '
                    'Una frase breve por lista. La imagen adjunta es evidencia. Describe solo una observación visual '
                    'no identificatoria; no nombres personas, no infieras cantidad ni reemplaces el conteo YOLO. '
                    'No afirmes causalidad. Si la imagen no basta, indícalo en unknowns. Recomendación solo no crítica.')
        return None
        return ('JSON: {"inferences":[""],"unknowns":[""],"recommendations":[""]}. '
                'Una frase por lista. Copia esta estructura de inferencia: "Radar presence=<presence>; cámara count=<count>; '
                'eventos=<events> coinciden temporalmente, sin probar causalidad." No añadas etiquetas ni hechos. '
                'Unknowns: "Radar y cámara no determinan la ocupación total." Recomendación no crítica: monitorear los eventos listados.')

    def execute(self, command: Command, snapshot: Snapshot, image: bytes | None, config: dict, prompt: str) -> dict:
        started_at = utc_now()
        started_monotonic = time.monotonic()
        response = self.completion(prompt, image, max_tokens=config["max_tokens"], timeout=config["timeout_seconds"],
                                   response_format={"type": "json_object"},
                                   system_prompt=self.system_prompt(command.parameters["question_id"]))
        result = {"interpretation_id": identifier(), "request_id": command.command_id, "snapshot_id": snapshot.snapshot_id,
                  "image_id": command.parameters.get("image_id"), "model_id": self.model,
                  "runtime_model_id": response.get("model", self.model),
                  "started_at": started_at, "completed_at": utc_now(), "question_id": command.parameters["question_id"],
                  "inference_seconds": time.monotonic() - started_monotonic,
                  "raw_output": response["content"], "tokens": response.get("usage"), "validation_status": "REJECTED"}
        try:
            parsed = parse_json_object(response["content"])
            fields = ("inferences", "unknowns", "recommendations")
            if not isinstance(parsed, dict) or any(not isinstance(parsed.get(field), list) for field in fields):
                raise ValueError("Contrato de interpretación incompleto.")
            if any(not isinstance(item, str) or len(item) > 2000 for field in fields for item in parsed[field]):
                raise ValueError("La interpretación contiene texto inválido.")
            facts = [{"evidence_id": value["observation_id"], "value": value["value"]}
                     for value in snapshot.document()["observations"].values() if value["status"] == "VALID"]
            references = [fact["evidence_id"] for fact in facts]
            if command.action == "multimodal":
                if image is None or not result["image_id"]:
                    raise ValueError("La interpretación multimodal requiere imagen autorizada.")
                references.append(result["image_id"])
            if not references:
                raise ValueError("No hay evidencia válida para atribuir.")
            result.update(**{field: parsed[field] for field in fields}, observed_facts=facts,
                          evidence_references=references, validation_status="VALIDATED")
        except (ValueError, TypeError) as error:
            result["validation_error"] = str(error)
        return result
