from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .context import ContextStore, timestamp
from .acquisition import EnvironmentAgent, PresenceAgent
from .contracts import Command, Observation, identifier, utc_now
from .policy import PolicyEngine, answer_questions, semantic_key
from .telemetry import budget_reason
from .protocol import CHECKPOINTS, PROTOCOL_VERSION, validate_guided_start
from .trace import sample_document
from .faults import FaultInjector, SENSOR_FIELDS
from .health import HealthMonitor

TRANSITIONS = {"WAIT": {"ACQUIRE"}, "ACQUIRE": {"ASSESS", "DEGRADED"},
               "ASSESS": {"VISION", "INTERPRET", "REPORT", "DEGRADED"}, "VISION": {"ASSESS", "DEGRADED"},
               "INTERPRET": {"REPORT", "DEGRADED"}, "REPORT": {"WAIT", "DEGRADED"}, "DEGRADED": {"REPORT"}}


class SenseOrchestrator:
    def __init__(self, config, log, tasks, vision, interpreter, readiness, metadata):
        self.config, self.log, self.tasks = config, log, tasks
        self.vision_agent, self.interpreter, self.readiness = vision, interpreter, readiness
        self.metadata = metadata
        self.run = None
        self.fsm = "WAIT"
        self.cycle = None
        self.transitions = deque(maxlen=96)
        self.errors = deque(maxlen=20)
        self.interpretations = deque(maxlen=20)
        self.decisions = deque(maxlen=20)
        self.resources = {}
        self.latest_snapshot = None
        self.answers = {}
        self.dirty = False
        self.next_evaluation = 0
        self.image = None
        self.attempted = set()
        self.result_keys = {}
        self.events = []
        self.last_decisions = {}
        self.last_multimodal_context = None
        self.explicit = set()
        self.manual_presence = None
        self.last_sensor_presence = None

    @property
    def running(self):
        return self.run is not None and self.run["status"] == "RUNNING"

    def start(self, mode: str, now: float, session_id: str, scenario_id: str, experiment: dict | None = None) -> dict:
        experiment = experiment or {}
        validate_guided_start(experiment)
        if experiment.get("guided") and self.config["runtime"]["max_run_seconds"] != 1800:
            raise ValueError("La ejecución guiada requiere runtime.max_run_seconds=1800 para registrar 30 minutos.")
        if self.running or self.tasks.busy:
            raise ValueError("Hay una ejecución o un worker pendiente de finalizar.")
        if mode not in self.config["enabled_modes"]:
            raise ValueError("Modo experimental no habilitado.")
        if any(value == "loading" or value == "waiting" for value in self.readiness().values()):
            raise ValueError("Espere a que termine la preparación.")
        reason = budget_reason(self.resources, self.config["runtime"]) if self.resources else "RESOURCE_MONITOR_UNAVAILABLE"
        if reason:
            raise ValueError("No se puede iniciar: " + reason)
        self.context = ContextStore(self.config)
        self.policy = PolicyEngine(self.config, mode, now)
        self.run = dict(self.metadata, run_id=identifier(), session_id=session_id, scenario_id=scenario_id,
                        mode=mode, start_time=utc_now(), end_time=None, status="RUNNING",
                        config_version=self.config["config_version"], config_hash=self.config["config_hash"],
                        config=self.config, hardware_profile=self.config["hardware_profile"])
        self.run.update(guided=experiment.get("guided", False), repetition=experiment.get("repetition"),
                        duration_seconds=min(1800, self.config["runtime"]["max_run_seconds"]),
                        protocol_version=PROTOCOL_VERSION, power_interval_seconds=60,
                        observer=experiment.get("initial_observation", {}).get("observer"),
                        instrument=experiment.get("initial_observation", {}).get("instrument"),
                        equipment=experiment.get("initial_observation", {}).get("equipment"))
        self.run["observation_region"] = self.config["regions"]["camera_region"]
        self.run["policy_mode"] = self.policy.mode
        self.started = now
        self.health = HealthMonitor(self.record, now, self.config)
        self.faults = FaultInjector(self.record, now)
        self.sensor_observations = {}
        self.last_raw_presence = None
        self.raw_presence_received = None
        self.raw_presence_age = 0
        self.manual_near = None
        self.last_sample_second = -1
        self.next_manual_second = 60
        self.checkpoints = set()
        self.fsm, self.cycle, self.image = "WAIT", None, None
        self.transitions.clear()
        self.errors.clear()
        self.interpretations.clear()
        self.decisions.clear()
        self.attempted.clear()
        self.result_keys.clear()
        self.last_decisions.clear()
        self.events.clear()
        self.explicit.clear()
        self.last_multimodal_context = None
        self.manual_presence = None
        self.last_sensor_presence = None
        self.answers = {}
        self.tasks.counters = dict.fromkeys(self.tasks.counters, 0)
        self.log.begin(self.run)
        self.record("RUN_STARTED", self.run)
        if self.run["guided"]:
            initial = self.log.request_observer(self.run["run_id"], "RUN_INITIAL", ["power_w", "visible_people"])
            self.log.resolve_observer(self.run["run_id"], initial, experiment["initial_observation"])
        self.sample(now)
        self.dirty = True
        return self.run

    def record(self, kind: str, payload: dict):
        self.log.event(self.run["run_id"], kind, payload)
        if self.run.get("guided") and kind in ("FAULT_INJECTED", "FAULT_RESTORED", "FAULT_RECOVERED"):
            self.log.request_observer(self.run["run_id"], kind, ["power_w", "action"], task_id=payload.get("task_id"), event_id=payload["event_id"])
        if self.run.get("guided") and kind == "MANUAL_PRESENCE_CHANGED":
            self.log.request_observer(self.run["run_id"], kind, ["power_w", "visible_people", "action"], event_id=payload["event_id"])

    def transition(self, target: str, reason: str):
        if target not in TRANSITIONS[self.fsm]:
            raise RuntimeError(f"Transición inválida {self.fsm} → {target}")
        transition = {"from": self.fsm, "to": target, "reason": reason, "cycle_id": self.cycle["cycle_id"],
                      "timestamp": utc_now(), "elapsed_seconds": round(time.monotonic() - self.cycle["started_monotonic"], 3)}
        self.transitions.append(transition)
        self.cycle["actions"].append(target)
        self.record("FSM_TRANSITION", transition)
        self.fsm = target

    def ingest(self, payload: dict, now: float, wall: float):
        if not self.running:
            return
        try:
            if not isinstance(payload, dict) or payload.get("schema") != "rustio.iot.telemetry.v1":
                raise ValueError("Contrato MQTT no reconocido.")
            timestamp(payload.get("timestamp"))
            received_at = datetime.fromtimestamp(wall, timezone.utc).isoformat()
            environment = EnvironmentAgent.observe(payload, received_at, self.config["regions"]["environment_region"])
            presence = PresenceAgent.observe(payload, received_at, self.config["regions"]["radar_region"])
            raw_presence = presence
            for component, fields in SENSOR_FIELDS.items():
                if component in self.faults.disabled:
                    for key in fields:
                        environment.pop(key, None)
                    if component == "radar":
                        presence = None
            events = self.context.ingest(environment, presence if self.manual_presence is None else None,
                                         now, wall, payload.get("timestamp"))
            self.last_raw_presence = raw_presence
            self.raw_presence_received, self.raw_presence_age = now, max(0, wall - timestamp(raw_presence.captured_at))
            if presence is not None:
                self.last_sensor_presence = presence
                self.sensor_observations["presence"] = (presence, now, max(0, wall - timestamp(presence.captured_at)))
            for key, observation in environment.items():
                self.sensor_observations[key] = (observation, now, max(0, wall - timestamp(observation.captured_at)))
            if presence is not None and self.manual_presence is None:
                events.extend(self.policy.observe_presence(presence, wall))
        except (ValueError, TypeError, OverflowError, KeyError) as error:
            self.record("OBSERVATION_REJECTED", {"reason": str(error)})
            return
        self.record("OBSERVATIONS_RECEIVED", {"raw": payload, "dispatcher_wait_seconds": max(0, time.monotonic() - now),
                                              "raw_presence": raw_presence.document(),
                                              "observations": {k: v.document() for k, v in self.context.observations.items() if k != "count"}})
        for event in events:
            self.record(event["event_type"], event)
            if self.run["guided"]:
                self.log.request_observer(self.run["run_id"], event["event_type"], ["power_w", "visible_people", "action"], event_id=event["event_id"])
        self.events.extend(events)
        self.events = self.events[-self.config["runtime"]["inbox_capacity"]:]
        self.dirty = True

    def set_presence(self, detected: bool | None, now: float, near: bool | None = None):
        if not self.running or self.run["mode"] not in "BCDEF":
            raise ValueError("El control manual de presencia requiere B–F activos.")
        if (detected is not None and type(detected) is not bool) or (near is not None and type(near) is not bool):
            raise ValueError("Presencia y zona manual requieren booleanos.")
        if near is not None and (self.run["mode"] != "B" or detected is None or near and not detected):
            raise ValueError("La zona manual solo se admite en B; zona próxima requiere presencia.")
        previous = self.context.observations.get("presence")
        was_manual = self.manual_presence is not None
        self.manual_presence = detected
        self.manual_near = (detected if near is None else near) if detected is not None and self.run["mode"] == "B" else None
        self.record("MANUAL_PRESENCE_CHANGED", {"event_id": identifier(), "mode": "AUTO" if detected is None else "MANUAL", "detected": detected,
                    "near": self.manual_near, "raw_observation_id": self.last_raw_presence.observation_id if self.last_raw_presence else None,
                    "elapsed_s": now - self.started})
        self.dirty = True
        if detected is None:
            self.context.presence_samples = 0
            self.context.confirmed_presence = None
            self.policy.reset_reactive()
            original = self.sensor_observations.get("presence")
            if original:
                observation, received, age = original
                self.context.put("presence", observation, received, age)
            else:
                self.context.observations.pop("presence", None)
            return
        captured_at = utc_now()
        metadata = {"source_kind": "MANUAL_CONTROL"}
        if self.run["mode"] == "B":
            metadata["manual_near"] = self.manual_near
        presence = Observation(identifier(), "OperatorControl", captured_at, captured_at,
                               self.config["regions"]["radar_region"], int(detected), "presence", "operator_control", "VALID", tuple(metadata.items()))
        self.context.put("presence", presence, now)
        if self.run["mode"] == "B":
            if not was_manual:
                self.policy.reactive_last_timestamp = None
            for event in self.policy.observe_presence(presence, timestamp(captured_at)):
                self.record(event["event_type"], event)
        if previous is None or previous.value != presence.value:
            event = {"event_id": identifier(), "event_type": "PRESENCE_CHANGED", "source": "MANUAL_CONTROL",
                     "previous": previous.value if previous else None, "value": presence.value,
                     "evidence_ids": [presence.observation_id], "captured_at": presence.captured_at}
            self.record(event["event_type"], event)
            self.events.append(event)
            self.events = self.events[-self.config["runtime"]["inbox_capacity"]:]

    def set_fault(self, payload: dict, now: float):
        if not self.running or self.run["mode"] != "F":
            raise ValueError("La inyección de fallas solo está disponible en F activo.")
        if payload.get("action") == "availability":
            self.faults.set_enabled(payload.get("component"), payload.get("enabled"), now,
                                    self.health.components.get(payload.get("component"), {}).get("status", "UNKNOWN"))
        elif payload.get("action") == "timeout":
            if payload.get("lane") in self.tasks.quarantined:
                raise ValueError("El runtime remoto sigue sin confirmar; recupéralo antes de armar otra prueba.")
            self.faults.arm_timeout(payload.get("lane"), now,
                                    self.health.components["camera" if payload.get("lane") == "vision" else "gemma"]["status"])
        else:
            raise ValueError("Usa action availability o timeout.")

    def update_health(self, now):
        readings = {}
        for key, (observation, received, age) in self.sensor_observations.items():
            status = observation.status
            ttl = self.config["sensors"]["presence_ttl_seconds" if key == "presence" else "environment_ttl_seconds"]
            if status == "VALID" and now - received + age >= ttl:
                status = "STALE"
            readings[key] = dict(status=status, received_monotonic=received)
        self.health.sensors(readings, now)
        self.context.component_health = self.health.components.copy()
        self.faults.observe(self.health.components, now, self.health.evidence_times)

    def query(self, qid: str, now: float | None = None):
        from .policy import QUESTIONS

        if not self.running or qid not in QUESTIONS or (qid == "Q7" and self.policy.mode != "E"):
            raise ValueError("Pregunta no disponible en la ejecución actual.")
        self.explicit.add(qid)
        if qid in ("Q6", "Q7") and self.health.components["gemma"]["status"] == "FAILED":
            self.attempted.discard(semantic_key(qid, self.context.snapshot(time.monotonic() if now is None else now).document(), self.interpreter.model,
                                               self.image["image_id"] if qid == "Q7" and self.image else None))
        if qid == "Q2":
            self.policy.request_visual_count()
        self.record("QUESTION_REQUESTED", {"question_id": qid})
        self.dirty = True

    def tick(self, now: float, resources: dict):
        self.resources = resources
        if self.running and now - self.started >= self.run["duration_seconds"]:
            self.stop("MAX_RUN_DURATION", now)
        for event in self.tasks.poll(now, allow_start=self.running and budget_reason(resources, self.config["runtime"]) is None):
            self.handle_task(event, now)
        if not self.running:
            return
        self.update_health(now)
        if self.image and now >= self.image["expires"]:
            self.record("IMAGE_EXPIRED", {"image_id": self.image["image_id"]})
            self.image = None
        self.sample(now)
        if self.run["guided"]:
            elapsed = now - self.started
            if elapsed >= self.next_manual_second:
                due = int(elapsed // 60) * 60
                self.log.request_observer(self.run["run_id"], f"PERIODIC_W:{due}", ["power_w"])
                if due > self.next_manual_second:
                    self.record("OBSERVER_SCHEDULE_GAP", {"from_s": self.next_manual_second, "to_s": due})
                self.next_manual_second = due + 60
            for second in CHECKPOINTS[self.run["scenario_id"]]:
                if elapsed >= second and second not in self.checkpoints:
                    self.checkpoints.add(second)
                    self.log.request_observer(self.run["run_id"], f"SCENARIO_CHECKPOINT:{second}", ["power_w", "visible_people", "action"])
        if budget_reason(resources, self.config["runtime"]) == "STORAGE_BUDGET":
            self.stop("STORAGE_BUDGET", now)
            return
        if self.cycle and self.fsm == "VISION":
            if now >= self.cycle["deadline_monotonic"] or self.health.degraded:
                self.transition("DEGRADED", "CYCLE_DEADLINE" if now >= self.cycle["deadline_monotonic"] else "COMPONENT_FAILURE_DURING_VISION")
                self.answers = answer_questions(self.context.snapshot(now), self.run["mode"], self.config["interpretation"]["relationship_alignment_seconds"])
                self.report(now)
            return
        if self.dirty or now >= self.next_evaluation:
            self.dirty = False
            self.next_evaluation = now + self.config["runtime"]["evaluation_interval_seconds"]
            self.cycle = {"cycle_id": identifier(), "started_at": utc_now(), "started_monotonic": now,
                          "deadline_monotonic": now + self.config["runtime"]["cycle_timeout_seconds"], "requests": 0,
                          "pending": None, "actions": [], "vision_attempted": False}
            self.transition("ACQUIRE", "SENSOR_EVENT_OR_TIMER")
            self.transition("ASSESS", "AVAILABLE_OBSERVATIONS")
            self.assess(now)

    def assess(self, now: float):
        snapshot = self.context.snapshot(now)
        document = snapshot.document()
        self.latest_snapshot = document
        self.answers = answer_questions(snapshot, self.run["mode"], self.config["interpretation"]["relationship_alignment_seconds"])
        self.policy.visual_need(document, self.events)
        for qid, saved in self.result_keys.items():
            image_id = self.image["image_id"] if qid == "Q7" and self.image else None
            if saved["result"]["validation_status"] == "VALIDATED" and saved["semantic_key"] == semantic_key(qid, document, self.interpreter.model, image_id):
                result = saved["result"]
                self.answers[qid].update(status="INTERPRETED", answer=result["inferences"], pending_information=[],
                                         evidence_ids=result["evidence_references"], interpretation_id=result["interpretation_id"],
                                         source_snapshot_id=result["snapshot_id"])
        previous_needs = {need["need_id"] for need in self.policy.needs.values()}
        for need in self.policy.information_needs(self.answers, document):
            if need["need_id"] not in previous_needs:
                self.record("INFORMATION_NEED_CREATED", need)
        self.record("CONTEXT_UPDATED", document)
        if document["conflict"]:
            self.record("CONTEXT_CONFLICT", {"snapshot_id": snapshot.snapshot_id, "reason": "COMPARABLE_PRESENCE_DISAGREES"})
        if document["observations"].get("count", {}).get("status") == "STALE" and not self.last_decisions.get("stale"):
            self.record("VISUAL_COUNT_STALE", {"snapshot_id": snapshot.snapshot_id})
            self.last_decisions["stale"] = True
        ready = self.readiness()
        reason = budget_reason(self.resources, self.config["runtime"])
        previous_period = self.policy.next_period
        decision = self.policy.vision(document, now, self.events, ready.get("yolo") == "ready" and self.health.available("camera", now),
                                      self.tasks.active["vision"] is not None, reason)
        if self.run["mode"] == "A" and previous_period != self.policy.next_period:
            due = round((self.policy.next_period - previous_period) / self.config["modes"]["periodic_interval_seconds"])
            self.record("PERIOD_SCHEDULE", {"first_due_monotonic": previous_period, "evaluated_monotonic": now,
                                           "intervals_due": due, "missed_intervals": due - 1 if decision.action else due,
                                           "reason": decision.reason})
        self.events.clear()
        if self.cycle["vision_attempted"] or self.cycle["requests"] >= self.config["runtime"]["max_cycle_requests"]:
            from .policy import Decision

            decision = Decision(None, "Q2", "CYCLE_REQUEST_LIMIT")
        self.record_decision("VISION", decision)
        if decision.action:
            command = self.command("VisionAgent", "vision", "Q2", decision.reason, self.config["vision"]["timeout_seconds"],
                                   {"region": self.config["regions"]["camera_region"], "snapshot_id": snapshot.snapshot_id,
                                    "trigger_event_id": self.policy.reactive_pending["event_id"] if self.run["mode"] == "B" else None})
            fault = self.faults.task_fault("vision")
            if fault:
                command.parameters.update(fault_id=fault["fault_id"], simulated=True, model_executed=False)
            error = self.tasks.submit("vision", command,
                                      lambda: self.vision_agent.execute(command, self.config["vision"]["max_image_bytes"]),
                                      "vision:" + self.run["run_id"], now, self.config["vision"]["timeout_seconds"], simulation=fault)
            if error is None:
                self.faults.accepted(fault, command, now)
                self.record("COMMAND_ISSUED", asdict(command))
                self.record("VISION_REQUESTED", {"command_id": command.command_id, "question_id": "Q2", "reason": decision.reason})
                self.policy.accepted_vision(now)
                self.cycle["requests"] += 1
                self.cycle["vision_attempted"] = True
                self.cycle["pending"] = command.command_id
                self.transition("VISION", decision.reason)
                return
            self.record("VISION_SKIPPED", {"reason": error, "question_id": "Q2"})
        submitted = self.interpret(snapshot, now, ready, reason)
        if submitted:
            self.transition("INTERPRET", "ASYNC_TASK_ACCEPTED")
        if self.health.degraded or not any(value.get("status") == "VALID" for value in document["observations"].values()):
            self.transition("DEGRADED", "COMPONENT_FAILURE_OR_INSUFFICIENT_EVIDENCE")
        self.report(now)

    def record_decision(self, kind: str, decision):
        payload = dict(asdict(decision), cycle_id=self.cycle["cycle_id"], snapshot_id=self.latest_snapshot["snapshot_id"])
        self.record("POLICY_EVALUATED", {"kind": kind, **payload})
        key = (decision.action, decision.reason)
        if self.last_decisions.get(kind) != key or decision.action:
            if decision.action is None:
                self.record(kind + "_SKIPPED", payload)
            self.decisions.append({"kind": kind, **payload})
        self.last_decisions[kind] = key

    def command(self, agent: str, action: str, qid: str, reason: str, timeout: float, parameters: dict) -> Command:
        return Command(identifier(), self.cycle["cycle_id"], self.run["run_id"], agent, action, utc_now(),
                       (datetime.now(timezone.utc) + timedelta(seconds=timeout)).isoformat(),
                       dict(parameters, question_id=qid), reason)

    def interpret(self, snapshot, now, ready, resource_reason):
        document = snapshot.document()
        accepted = False
        for kind, qid in (("text", "Q6"), ("multimodal", "Q7")):
            budget = self.config["interpretation"]["textual" if kind == "text" else "multimodal"]
            image = None
            image_id = None
            if kind == "multimodal":
                image_id = self.image["image_id"] if self.image else None
                image = self.image["bytes"] if self.image else None
            key = semantic_key(qid, document, self.interpreter.model, image_id)
            decision = self.policy.interpretation(kind, self.answers[qid], now, key, self.attempted,
                                                  ready.get("text" if kind == "text" else "vision") == "ready" and self.health.available("gemma", now), resource_reason)
            from .policy import Decision

            if self.cycle["requests"] >= self.config["runtime"]["max_cycle_requests"]:
                decision = Decision(None, qid, "CYCLE_REQUEST_LIMIT")

            if kind == "multimodal" and decision.action:
                count = document["observations"].get("count", {})
                episode = document["environment_events"][-1]["event_id"] if document["environment_events"] else None
                context_key = (count.get("value"), episode)
                if image is None:
                    decision = Decision(None, qid, "NO_FRESH_AUTHORIZED_IMAGE")
                elif count.get("status") != "VALID":
                    decision = Decision(None, qid, "INSUFFICIENT_EVIDENCE")
                elif context_key == self.last_multimodal_context and qid not in self.explicit:
                    decision = Decision(None, qid, "NO_ADDITIONAL_INFORMATION_EXPECTED")
            self.record_decision("TEXT_SLM" if kind == "text" else "MULTIMODAL", decision)
            if not decision.action:
                continue
            prompt = self.interpreter.prompt(qid, snapshot, image_id)
            command = self.command("InterpretationAgent", kind, qid, decision.reason, budget["timeout_seconds"],
                                   {"snapshot_id": snapshot.snapshot_id, "image_id": image_id, "semantic_key": key,
                                    "image_expires_monotonic": self.image["expires"] if kind == "multimodal" else None})
            def action(command=command, snapshot=snapshot, image=image, prompt=prompt, budget=budget):
                if image is not None and time.monotonic() >= command.parameters["image_expires_monotonic"]:
                    raise ValueError("IMAGE_EXPIRED_IN_QUEUE")
                return self.interpreter.execute(command, snapshot, image, budget, prompt)

            timeout = budget["timeout_seconds"]
            fault = self.faults.task_fault("gemma")
            if fault:
                command.parameters.update(fault_id=fault["fault_id"], simulated=True, model_executed=False)
            error = self.tasks.submit("gemma", command, action, key, now, timeout, simulation=fault)
            if error:
                self.record(("TEXT_SLM" if kind == "text" else "MULTIMODAL") + "_SKIPPED", {"reason": error, "question_id": qid})
            else:
                self.faults.accepted(fault, command, now)
                self.attempted.add(key)
                self.cycle["requests"] += 1
                self.policy.accepted_interpretation(kind, now)
                self.record("COMMAND_ISSUED", asdict(command))
                self.record(("TEXT_SLM" if kind == "text" else "MULTIMODAL") + "_REQUESTED",
                            {"command_id": command.command_id, "question_id": qid, "reason": decision.reason})
                self.record("SLM_INPUT", {"request_id": command.command_id, "prompt": prompt, "image_id": image_id,
                                          "system_prompt": self.interpreter.system_prompt(qid), "generation_config": budget,
                                          "model_id": self.interpreter.model, "snapshot_id": snapshot.snapshot_id})
                if kind == "multimodal":
                    self.last_multimodal_context = context_key
                accepted = True
        self.explicit.clear()
        return accepted

    def report(self, now):
        if self.fsm != "REPORT":
            self.transition("REPORT", "RESULT_OR_JUSTIFIED_ABSTENTION")
        self.record("RESULT_PUBLISHED", {"cycle_id": self.cycle["cycle_id"], "answers": self.answers})
        self.transition("WAIT", "REPORT_RECORDED")

    def handle_task(self, event, now):
        command = event.payload["command"]
        run_id = command["experiment_run_id"]
        payload = dict(event.payload)
        result = payload.get("result")
        image = result.pop("image", None) if result else None
        self.log.event(run_id, event.event_type, {**payload, "error": event.error, "event_id": event.event_id,
                                                "timestamp": event.timestamp, "schema": event.schema,
                                                "source_agent": event.source_agent, "correlation_id": event.correlation_id})
        if self.run and self.run["run_id"] == run_id and self.run.get("guided") and event.event_type in ("TASK_STARTED", "TASK_COMPLETED", "TASK_FAILED", "TASK_TIMEOUT"):
            fields = ["power_w", "visible_people"] if command["action"] == "vision" and event.event_type == "TASK_STARTED" else ["power_w"]
            self.log.request_observer(run_id, command["action"].upper() + "_" + event.event_type,
                                      fields, task_id=command["command_id"], event_id=event.event_id)
        same_run = self.running and self.run["run_id"] == run_id
        if same_run:
            self.health.task_event(event, now)
            self.faults.task_event(event, now)
            self.context.component_health = self.health.components.copy()
        if not same_run or payload.get("late"):
            if result and command["action"] != "vision":
                self.log.event(run_id, "HISTORICAL_INTERPRETATION", result)
                if self.run and self.run["run_id"] == run_id:
                    self.interpretations.append(dict(result, historical=True))
            return
        if event.error or event.event_type == "TASK_TIMEOUT":
            self.errors.append({"timestamp": utc_now(), "detail": event.error or "TASK_TIMEOUT", "request_id": command["command_id"]})
        if event.event_type == "TASK_STARTED":
            return
        if command["action"] == "vision":
            if event.event_type in ("TASK_FAILED", "TASK_TIMEOUT") and self.policy.mode in "CDE":
                self.policy.pending_visual_reason = "RETRY_VISUAL_EVIDENCE"
            if event.event_type == "TASK_COMPLETED" and result:
                age = max(0, time.time() - timestamp(result["captured_at"]))
                observation = Observation(identifier(), "VisionAgent", result["captured_at"], utc_now(), result["region"],
                                          result["count"], "visible_people", result["quality"], "VALID",
                                          (("image_id", result["image_id"]), ("model_id", self.metadata["model_version"]["yolo"])))
                self.context.put("count", observation, now, age)
                self.record("VISION_OBSERVATION", {"task_id": command["command_id"], "observation": observation.document()})
                self.last_decisions["stale"] = False
                if self.policy.mode == "E" and image is not None and age < self.config["vision"]["image_ttl_seconds"]:
                    self.image = {"image_id": result["image_id"], "bytes": image, "captured_at": result["captured_at"],
                                  "expires": now + self.config["vision"]["image_ttl_seconds"] - age}
            if self.fsm == "VISION" and self.cycle["pending"] == command["command_id"]:
                if event.event_type == "TASK_COMPLETED":
                    self.transition("ASSESS", "VISION_RESULT_RECEIVED")
                    self.assess(now)
                elif event.event_type in ("TASK_FAILED", "TASK_TIMEOUT"):
                    self.transition("DEGRADED", event.error or "TASK_TIMEOUT")
                    snapshot = self.context.snapshot(now)
                    self.latest_snapshot = snapshot.document()
                    self.answers = answer_questions(snapshot, self.run["mode"], self.config["interpretation"]["relationship_alignment_seconds"])
                    self.report(now)
        elif result:
            self.interpretations.append(dict(result, historical=True))
            self.result_keys[command["parameters"]["question_id"]] = {"semantic_key": payload["semantic_key"], "result": result}
            self.dirty = True

    def stop(self, reason: str, now: float):
        if not self.running:
            return
        if self.fsm != "WAIT":
            if self.fsm != "DEGRADED":
                self.transition("DEGRADED", reason)
            self.report(now)
        for command in self.tasks.cancel(self.run["run_id"]):
            self.record("TASK_CANCELLED", {"command_id": command.command_id, "reason": reason,
                                            "physical_cancellation_supported": False})
        self.image = None
        elapsed = min(self.run["duration_seconds"], max(0, now - self.started))
        expected = min(math.ceil(self.run["duration_seconds"]), max(1, math.ceil(elapsed)))
        if self.last_sample_second + 1 < expected:
            self.record("SAMPLE_GAP", {"from_second": self.last_sample_second + 1, "to_second": expected - 1, "reason": "RUN_ENDED_WITHOUT_SAMPLE"})
        self.run.update(elapsed_s=elapsed, expected_samples=expected, finish_reason=reason)
        self.run.update(status="COMPLETED" if reason in ("USER_STOP", "MAX_RUN_DURATION") else "FAILED", end_time=utc_now())
        self.record("RUN_FINISHED", {"reason": reason, "end_time": self.run["end_time"], "counters": self.tasks.counters})
        if self.run["guided"]:
            self.log.request_observer(self.run["run_id"], "RUN_FINAL", ["power_w", "visible_people", "action"])
        self.faults.finish(now)
        self.log.finish(self.run["run_id"], self.run["status"], self.run)

    def sample(self, now):
        second = int(max(0, now - self.started))
        if second <= self.last_sample_second or second >= self.run["duration_seconds"]:
            return
        if second > self.last_sample_second + 1:
            self.record("SAMPLE_GAP", {"from_second": self.last_sample_second + 1, "to_second": second - 1, "reason": "SAMPLER_DELAY"})
        document = dict(sample_document(self, now), second=second)
        self.log.sample(self.run["run_id"], second, document)
        self.last_sample_second = second

    def view(self, now):
        context = self.context.snapshot(now).document() if self.run else None
        run = {key: value for key, value in self.run.items() if key != "config"} if self.run else None
        raw_presence = self.last_raw_presence.document() if self.run and self.last_raw_presence else None
        if raw_presence:
            age = max(0, now - self.raw_presence_received + self.raw_presence_age)
            raw_presence["age_seconds"] = round(age, 2)
            if raw_presence["status"] == "VALID" and age >= self.config["sensors"]["presence_ttl_seconds"]:
                raw_presence["status"] = "STALE"
        return {"running": self.running, "run": run, "fsm": self.fsm, "cycle": self.cycle,
                "observation_region": self.config["regions"]["camera_region"],
                "component_health": self.health.components if self.run else {},
                "fault_control": self.faults.view() if self.run and self.run["mode"] == "F" else None,
                "raw_presence": raw_presence,
                "elapsed_s": min(now - self.started, self.run["duration_seconds"]) if self.running else self.run.get("elapsed_s", 0) if self.run else 0,
                "observer_requests": self.log.observer_requests(self.run["run_id"], True) if self.run else [],
                "quality": self.log.quality(self.run["run_id"]) if self.run else None,
                "transitions": list(self.transitions), "context": context, "answers": self.answers,
                "needs": list(self.policy.needs.values()) if self.run else [], "tasks": self.tasks.view(now),
                "interpretations": list(self.interpretations), "decisions": list(self.decisions),
                "errors": list(self.errors), "resources": self.resources, "enabled_modes": self.config["enabled_modes"],
                "config_version": self.config["config_version"], "questions": {key: value["question"] for key, value in self.answers.items()},
                "reactive_trigger": self.policy.reactive_view(context) if self.run and self.run["mode"] == "B" else None,
                "presence_control": {"mode": "MANUAL" if self.manual_presence is not None else "AUTO",
                                     "detected": self.manual_presence, "near": self.manual_near} if self.run and self.run["mode"] in "BCDEF" else None}
