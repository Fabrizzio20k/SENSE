from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass

from .contracts import Observation, Snapshot, identifier

QUESTIONS = {
    "Q1": "¿Hay presencia humana en la región monitoreada?",
    "Q2": "¿Cuántas personas son visibles actualmente?",
    "Q3": "¿Cuáles son las condiciones ambientales actuales?",
    "Q4": "¿Ha ocurrido un cambio ambiental relevante?",
    "Q5": "¿La información disponible es suficiente y consistente?",
    "Q6": "¿Qué relación contextual puede describirse entre ocupación y condiciones ambientales?",
    "Q7": "¿Qué información adicional aporta la imagen sobre la situación del aula?",
}


def semantic_key(question: str, snapshot: dict, model: str, image_id: str | None = None) -> str:
    relevant = {key: {"value": value["value"], "status": value["status"], "region": value["region"],
                     "source_agent": value.get("source_agent"), "source_kind": value.get("metadata", {}).get("source_kind")}
                for key, value in snapshot["observations"].items()}
    content = {"question": question, "evidence": relevant, "model": model, "image_id": image_id,
               "episodes": [event["event_id"] for event in snapshot["environment_events"]]}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def answer_questions(snapshot: Snapshot, mode: str, alignment_seconds: float = 60) -> dict:
    mode = "E" if mode == "F" else mode
    document = snapshot.document()
    observations = document["observations"]
    answers = {}

    def result(q: str, status: str, answer, keys=(), limitations=(), pending=()):
        answers[q] = {"question_id": q, "question": QUESTIONS[q], "status": status, "answer": answer,
                      "evidence_ids": [observations[key]["observation_id"] for key in keys if key in observations],
                      "evaluated_at": snapshot.created_at, "snapshot_id": snapshot.snapshot_id,
                      "limitations": list(limitations), "pending_information": list(pending)}

    presence = observations.get("presence", {})
    valid_presence = presence.get("status") == "VALID"
    manual = presence.get("metadata", {}).get("source_kind") == "MANUAL_CONTROL"
    result("Q1", "RESOLVED" if valid_presence else "ABSTAINED",
           ("Presencia detectada" if presence["value"] else "Sin presencia detectada") if valid_presence else "Radar sin evidencia vigente.",
           ("presence",), ("Solo cobertura del radar; no representa toda el aula ni proporciona conteo.",),
           () if valid_presence else ("PRESENCE_REQUIRED",))
    if manual:
        answers["Q1"]["limitations"] = ["Señal manual del operador; no es medición del radar ni ground truth."]
    count = observations.get("count", {})
    valid_count = count.get("status") == "VALID"
    result("Q2", "RESOLVED" if valid_count else "PENDING", count["value"] if valid_count else None,
           ("count",), ("Personas visibles en la región de cámara; estimación YOLO.",),
           () if valid_count else ("VISUAL_COUNT_REQUIRED",))
    env_keys = ("temperature", "humidity", "aqi", "tvoc", "eco2")
    environment = {key: {"value": observations.get(key, {}).get("value"), "unit": observations.get(key, {}).get("unit"),
                         "status": observations.get(key, {}).get("status", "UNKNOWN")} for key in env_keys}
    result("Q3", "RESOLVED" if all(v["status"] == "VALID" for v in environment.values()) else "PARTIAL", environment, env_keys,
           ("eCO₂ es estimado; AQI es el índice del ENS160. No constituye una alerta certificada.",),
           tuple(key for key, value in environment.items() if value["status"] != "VALID"))
    events = document["environment_events"]
    warming = any(not value["evaluable"]
                  for key, value in document["environment_conditions"].items() if key != "eco2")
    result("Q4", "PARTIAL" if warming or answers["Q3"]["status"] != "RESOLVED" else "RESOLVED",
           [{"event_type": e["event_type"], "magnitude": e["magnitude"], "captured_at": e["captured_at"]} for e in events], env_keys,
           ("Cambios confirmados de esta sesión; referencia de ventana y rearme documentados. No implica causalidad.",),
           ("Ventana de comparación incompleta o en rearme.",) if warming else ())
    missing = [key for key in (*env_keys, "presence", "count") if observations.get(key, {}).get("status") != "VALID"]
    result("Q5", "RESOLVED" if not missing else "ABSTAINED",
           "Evidencia vigente dentro de sus regiones." if not missing else "Información incompleta, vencida o no comparable.",
           tuple(observations), ("Radar y cámara solo se comparan si su cobertura fue declarada comparable.",), missing)
    if manual:
        answers["Q5"]["limitations"].append("La presencia utilizada es una intervención manual, separada del ground truth.")
    related = bool(events and valid_count and valid_presence)
    latest_episode = events[-1] if events else None
    # La relación requiere evidencia próxima al episodio; la simultaneidad no prueba causalidad.
    if related:
        from .context import timestamp

        related = all(abs(timestamp(observations[key]["captured_at"]) - timestamp(latest_episode["captured_at"])) <= alignment_seconds
                      for key in ("count", "presence"))
    complex_episode = related and len({event["event_type"] for event in events[-4:]}) >= 2
    result("Q6", "PARTIAL" if complex_episode else "RESOLVED" if related else "ABSTAINED",
           "Coincidencia temporal de cambios ambientales y evidencia de ocupación; no demuestra causalidad." if related
           else "No hay un episodio ambiental y evidencia de ocupación temporalmente comparables.",
           (*env_keys, "presence", "count"), ("No se puede atribuir el cambio ambiental a las personas.",),
           ("TEXT_INTERPRETATION_REQUIRED",) if complex_episode and mode in ("D", "E") else ())
    if manual:
        answers["Q6"]["limitations"].append("La señal manual de presencia no confirma ocupación real.")
    result("Q7", "PENDING" if mode == "E" else "NOT_APPLICABLE",
           "Pendiente de imagen pertinente y necesidad visual adicional." if mode == "E" else "Capacidad disponible en E y F.",
           ("count",), ("Descripción inferida; sin identificación ni reconocimiento facial.",),
           ("MULTIMODAL_INTERPRETATION_REQUIRED",) if mode == "E" else ())
    return answers


@dataclass(frozen=True)
class Decision:
    action: str | None
    question_id: str
    reason: str


class PolicyEngine:
    def __init__(self, config: dict, mode: str, started: float):
        self.config, self.mode = config, "E" if mode == "F" else mode
        self.next_period = started
        self.reactive_pending = None
        self.reactive_confirmed = None
        self.reactive_candidate = None
        self.reactive_evidence = deque(maxlen=config["modes"]["reactive_debounce_samples"])
        self.reactive_last_timestamp = None
        self.last_visual = float("-inf")
        self.visual_requests = deque()
        self.slm_requests = {"text": deque(), "multimodal": deque()}
        self.last_slm = {"text": float("-inf"), "multimodal": float("-inf")}
        self.needs = {}
        self.pending_visual_reason = None

    def observe_presence(self, observation: Observation, wall: float) -> list[dict]:
        if self.mode != "B":
            return []
        from .context import timestamp

        metadata = dict(observation.metadata)
        manual = metadata.get("source_kind") == "MANUAL_CONTROL"
        captured = timestamp(observation.captured_at)
        if not manual and self.reactive_last_timestamp is not None:
            if captured <= self.reactive_last_timestamp:
                return []
            if captured - self.reactive_last_timestamp >= self.config["sensors"]["presence_ttl_seconds"]:
                self.reactive_evidence.clear()
        if not manual:
            self.reactive_last_timestamp = captured
        distance = metadata.get("trigger_distance_cm")
        if observation.status != "VALID" or (not manual and wall - captured >= self.config["sensors"]["presence_ttl_seconds"]) or (not manual and observation.value != 0 and distance is None):
            self.reactive_candidate = None
            self.reactive_evidence.clear()
            return []
        modes = self.config["modes"]
        threshold = modes["reactive_exit_at_or_above_cm"] if self.reactive_confirmed else modes["reactive_enter_below_cm"]
        near = metadata["manual_near"] if manual else observation.value != 0 and distance < threshold
        if manual:
            self.reactive_evidence.clear()
        if near != self.reactive_candidate:
            self.reactive_evidence.clear()
        self.reactive_candidate = near
        self.reactive_evidence.append(observation.observation_id)
        if (not manual and len(self.reactive_evidence) < modes["reactive_debounce_samples"]) or near == self.reactive_confirmed:
            return []
        previous = self.reactive_confirmed
        self.reactive_confirmed = near
        if previous is None and not near:
            return []
        event = {"event_id": identifier(), "event_type": "RADAR_NEAR_CONFIRMED" if previous is None else "RADAR_ZONE_ENTERED" if near else "RADAR_ZONE_EXITED",
                 "previous": previous, "near": near, "distance_cm": distance, "distance_source": metadata.get("trigger_distance_source"),
                 "enter_below_cm": modes["reactive_enter_below_cm"], "exit_at_or_above_cm": modes["reactive_exit_at_or_above_cm"],
                 "confirmation_samples": len(self.reactive_evidence), "region": observation.region,
                 "evidence_ids": list(self.reactive_evidence), "captured_at": observation.captured_at}
        if manual:
            event.update(event_type="MANUAL_ZONE_ENTERED" if near else "MANUAL_ZONE_EXITED", source="MANUAL_CONTROL")
        self.reactive_pending = event
        return [event]

    def reset_reactive(self):
        self.reactive_confirmed = self.reactive_candidate = self.reactive_pending = self.reactive_last_timestamp = None
        self.reactive_evidence.clear()

    def reactive_view(self, snapshot: dict) -> dict:
        observation = snapshot["observations"].get("presence", {})
        metadata = observation.get("metadata", {})
        if metadata.get("source_kind") == "MANUAL_CONTROL":
            return dict(state="NEAR" if metadata["manual_near"] else "FAR", manual=True,
                        candidate="NEAR" if metadata["manual_near"] else "FAR", distance_cm=None, distance_source=None,
                        confirmed_samples=1, required_samples=1, pending_event=self.reactive_pending,
                        enter_below_cm=self.config["modes"]["reactive_enter_below_cm"], exit_at_or_above_cm=self.config["modes"]["reactive_exit_at_or_above_cm"])
        known = observation.get("status") in ("VALID", "CONFLICTING") and (observation.get("value") == 0 or metadata.get("trigger_distance_cm") is not None)
        return {"state": "UNKNOWN" if not known else "CONFIRMING" if len(self.reactive_evidence) < self.config["modes"]["reactive_debounce_samples"] else "NEAR" if self.reactive_confirmed else "FAR",
                "candidate": "NEAR" if self.reactive_candidate else "FAR" if self.reactive_candidate is not None else None,
                "distance_cm": metadata.get("trigger_distance_cm"), "distance_source": metadata.get("trigger_distance_source"),
                "confirmed_samples": len(self.reactive_evidence) if known else 0,
                "required_samples": self.config["modes"]["reactive_debounce_samples"],
                "enter_below_cm": self.config["modes"]["reactive_enter_below_cm"],
                "exit_at_or_above_cm": self.config["modes"]["reactive_exit_at_or_above_cm"],
                "pending_event": self.reactive_pending}

    def information_needs(self, answers: dict, snapshot: dict) -> list[dict]:
        from datetime import datetime, timedelta

        types = {"Q1": "PRESENCE_REQUIRED", "Q2": "VISUAL_COUNT_REQUIRED", "Q3": "ENVIRONMENT_STATUS_REQUIRED",
                 "Q5": "CONFLICT_RESOLUTION_REQUIRED", "Q6": "TEXT_INTERPRETATION_REQUIRED", "Q7": "MULTIMODAL_INTERPRETATION_REQUIRED"}
        for qid, kind in types.items():
            answer = answers[qid]
            needed = bool(answer["pending_information"]) and answer["status"] != "NOT_APPLICABLE"
            if qid == "Q2" and self.mode in ("C", "D", "E"):
                needed = self.pending_visual_reason is not None
            previous = self.needs.get(qid)
            if needed and (previous is None or previous["status"] == "RESOLVED"):
                self.needs[qid] = {"need_id": identifier(), "type": kind, "question_id": qid, "question": QUESTIONS[qid],
                                   "origin": "CONTEXT_EVALUATION", "region": self.config["regions"]["camera_region"] if qid in ("Q2", "Q7") else "source_regions",
                                   "created_at": snapshot["created_at"],
                                   "expires_at": (datetime.fromisoformat(snapshot["created_at"]) + timedelta(seconds=self.config["runtime"]["max_run_seconds"])).isoformat(),
                                   "priority": 1 if qid in ("Q1", "Q3") else 2, "status": "PENDING"}
            if qid in self.needs:
                self.needs[qid].update(status="PENDING" if needed else "RESOLVED", evidence_ids=answer["evidence_ids"],
                                       missing_information=answer["pending_information"])
        return list(self.needs.values())

    def visual_need(self, snapshot: dict, events: list[dict]) -> str | None:
        """C/D/E only refresh visual evidence when a question needs it."""
        if self.mode not in ("C", "D", "E"):
            return None
        count = snapshot["observations"].get("count", {})
        event_types = {event["event_type"] for event in events}
        if count.get("status") == "VALID" and not snapshot["conflict"]:
            self.pending_visual_reason = None
            if self.config["regions"]["radar_camera_comparable"] and "PRESENCE_CHANGED" in event_types:
                return "COMPARABLE_PRESENCE_CHANGED"
            if event_types & {"TEMP_RISE", "HUMIDITY_RISE", "AQI_WORSENED", "ECO2_THRESHOLD_CROSSED"}:
                return "ENVIRONMENT_CONTEXT_REQUIRED"
            return None
        if self.pending_visual_reason:
            return self.pending_visual_reason
        if snapshot["conflict"]:
            self.pending_visual_reason = "RESOLVABLE_CONFLICT"
        elif self.config["regions"]["radar_camera_comparable"] and "PRESENCE_CHANGED" in event_types:
            self.pending_visual_reason = "COMPARABLE_PRESENCE_CHANGED"
        elif event_types & {"TEMP_RISE", "HUMIDITY_RISE", "AQI_WORSENED", "ECO2_THRESHOLD_CROSSED"}:
            self.pending_visual_reason = "ENVIRONMENT_CONTEXT_REQUIRED"
        elif self.mode == "E" and not count:
            self.pending_visual_reason = "MULTIMODAL_REFERENCE_REQUIRED"
        return self.pending_visual_reason

    def request_visual_count(self) -> None:
        self.pending_visual_reason = "EXPLICIT_VISUAL_COUNT_REQUEST"

    def vision(self, snapshot: dict, now: float, events: list[dict], available: bool, busy: bool, resource_reason: str | None) -> Decision:
        count = snapshot["observations"].get("count", {})
        if self.mode == "A":
            if now < self.next_period:
                return Decision(None, "Q2", "PERIOD_NOT_DUE")
            reason = "PERIODIC_SCHEDULE"
        elif self.mode == "B":
            trigger = self.reactive_view(snapshot)
            if trigger["state"] == "UNKNOWN":
                self.reactive_evidence.clear()
                return Decision(None, "Q2", "RADAR_DISTANCE_UNKNOWN")
            if trigger["state"] == "CONFIRMING":
                return Decision(None, "Q2", "RADAR_ZONE_CONFIRMING")
            if not self.reactive_pending:
                return Decision(None, "Q2", "NO_REACTIVE_TRIGGER")
            reason = self.reactive_pending["event_type"]
        else:
            reason = self.visual_need(snapshot, events)
            if reason is None:
                return Decision(None, "Q2", "NO_VISUAL_NEED")
            if count.get("status") == "VALID":
                return Decision(None, "Q2", "ALREADY_FRESH")
        if self.mode == "A":
            due = int((now - self.next_period) // self.config["modes"]["periodic_interval_seconds"]) + 1
            self.next_period += due * self.config["modes"]["periodic_interval_seconds"]
        if busy:
            return Decision(None, "Q2", "DUPLICATE_REQUEST" if self.mode != "A" else "MISSED_PERIOD_BUSY")
        if not available:
            return Decision(None, "Q2", "CAMERA_UNAVAILABLE")
        if resource_reason:
            return Decision(None, "Q2", resource_reason)
        cooldown = self.config["modes"]["reactive_min_interval_seconds"] if self.mode == "B" else self.config["vision"]["cooldown_seconds"]
        if self.mode != "A" and now - self.last_visual < cooldown:
            return Decision(None, "Q2", "COOLDOWN_ACTIVE")
        requests = self.visual_requests
        while requests and now - requests[0] >= self.config["vision"]["request_window_seconds"]:
            requests.popleft()
        if len(requests) >= self.config["vision"]["max_requests_per_window"]:
            return Decision(None, "Q2", "RATE_LIMIT")
        return Decision("vision", "Q2", reason)

    def accepted_vision(self, now: float) -> None:
        self.last_visual = now
        self.visual_requests.append(now)
        self.reactive_pending = None
        self.pending_visual_reason = None

    def interpretation(self, kind: str, answer: dict, now: float, semantic: str, attempted: set,
                       available: bool, resource_reason: str | None) -> Decision:
        question = "Q6" if kind == "text" else "Q7"
        if self.mode not in (("D", "E") if kind == "text" else ("E",)):
            return Decision(None, question, "MODE_CAPABILITY_DISABLED")
        if kind == "text" and "TEXT_INTERPRETATION_REQUIRED" not in answer["pending_information"]:
            return Decision(None, question, "NOT_REQUIRED_FOR_QUESTION")
        if semantic in attempted:
            return Decision(None, question, "DUPLICATE_REQUEST")
        if not available:
            return Decision(None, question, "MODEL_UNAVAILABLE")
        if resource_reason:
            return Decision(None, question, resource_reason)
        budget = self.config["interpretation"]["textual" if kind == "text" else "multimodal"]
        if now - self.last_slm[kind] < budget["cooldown_seconds"]:
            return Decision(None, question, "COOLDOWN_ACTIVE")
        history = self.slm_requests[kind]
        while history and now - history[0] >= budget["request_window_seconds"]:
            history.popleft()
        if len(history) >= budget["max_requests_per_window"]:
            return Decision(None, question, "RATE_LIMIT")
        return Decision(kind, question, "UNRESOLVED_CONTEXTUAL_NEED")

    def accepted_interpretation(self, kind: str, now: float) -> None:
        self.last_slm[kind] = now
        self.slm_requests[kind].append(now)
