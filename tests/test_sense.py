from __future__ import annotations

import copy
import json
import tempfile
import threading
import time
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sense.agents import InterpretationAgent, VisionAgent
from sense.acquisition import EnvironmentAgent, PresenceAgent
from sense.config import load_config, validate_config
from sense.context import ContextStore
from sense.contracts import Command, Observation, identifier, utc_now
from sense.orchestrator import SenseOrchestrator
from sense.policy import PolicyEngine, answer_questions, semantic_key
from sense.runtime import TaskManager
from sense.inference import request_completion
from sense.storage import ExperimentLog

ROOT = Path(__file__).resolve().parents[1]


def config():
    return load_config(ROOT / "sense" / "pilot.yaml")


def telemetry(at=None, temperature=26.33, humidity=70.63, aqi=2, eco2=497, presence=2):
    return {"schema": "rustio.iot.telemetry.v1", "device_id": "rpi5-01", "timestamp": at or utc_now(),
            "environment": {"sht40": {"temperature_c": temperature, "humidity_percent": humidity},
                            "ens160": {"aqi": aqi, "tvoc_ppb": 70, "eco2_ppm": eco2}},
            "presence": {"state_code": presence, "state": "Persona estática"}}


def ingest_packet(store, payload, now, wall=None):
    wall = time.time() if wall is None else wall
    return store.ingest(EnvironmentAgent.observe(payload, utc_now(), store.config['regions']['environment_region']),
                        PresenceAgent.observe(payload, utc_now(), store.config['regions']['radar_region']), now, wall)


def stamp(second):
    return (datetime(2026, 10, 24, tzinfo=timezone.utc) + timedelta(seconds=second)).isoformat()


def put_count(store, now, value=2, at=None):
    store.put("count", Observation(identifier(), "VisionAgent", at or utc_now(), utc_now(),
                                   store.config["regions"]["camera_region"], value, "visible_people", "test", "VALID"), now)


def resources():
    return {"available_mb": 4096, "main": {"rss_mb": 100}, "cpu_total_percent": 10,
            "database_mb": 1, "disk_free_mb": 4096}


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.config = config()
        self.config["environment"].update(window_seconds=6, reference_tolerance_seconds=0.1)
        self.store = ContextStore(self.config)

    def ingest(self, second, **kwargs):
        data = telemetry(stamp(second), **kwargs)
        wall = datetime.fromisoformat(data["timestamp"]).timestamp()
        return ingest_packet(self.store, data, second, wall)

    def test_actual_mqtt_shape_and_scope(self):
        self.ingest(0)
        snapshot = self.store.snapshot(0)
        answers = answer_questions(snapshot, "C")
        self.assertEqual(self.store.observations["presence"].value, 1)
        self.assertNotIn("count", self.store.observations)
        self.assertEqual(answers["Q2"]["status"], "PENDING")
        self.assertEqual(answers["Q3"]["answer"]["eco2"]["unit"], "ppm equivalent")

    def test_unknown_is_not_zero_and_invalid_breaks_confirmation(self):
        self.ingest(0, temperature=None, presence=None, humidity="bad")
        observation = self.store.snapshot(0).document()["observations"]
        self.assertIsNone(observation["temperature"]["value"])
        self.assertEqual(observation["temperature"]["status"], "UNAVAILABLE")
        self.assertEqual(observation["humidity"]["status"], "ERROR")
        self.assertIsNone(observation["presence"]["value"])

    def test_snapshot_immutable_and_stale(self):
        self.ingest(0)
        snapshot = self.store.snapshot(0)
        original = snapshot.document()
        self.ingest(2, temperature=28)
        self.assertEqual(snapshot.document(), original)
        self.assertEqual(self.store.snapshot(30).document()["observations"]["temperature"]["status"], "STALE")

    def test_reject_duplicate_old_and_future_timestamps(self):
        self.ingest(0)
        with self.assertRaises(ValueError):
            self.ingest(0)
        with self.assertRaises(ValueError):
            ingest_packet(self.store, telemetry(stamp(100)), 0, datetime.fromisoformat(stamp(0)).timestamp())
        self.assertEqual(self.store.observations["temperature"].value, 26.33)

    def test_three_valid_readings_confirm_exactly_one_episode(self):
        events = []
        for second in range(0, 22, 2):
            events += self.ingest(second, temperature=26 if second < 6 else 27)
        temp = [event for event in events if event["event_type"] == "TEMP_RISE"]
        self.assertEqual(len(temp), 1)
        self.assertEqual(len(temp[0]["evidence_ids"]), 3)
        self.assertEqual(temp[0]["reference"]["value"], 26)
        self.assertEqual(self.store.environment.baseline["temperature"]["value"], 26)

    def test_invalid_reading_cannot_confirm(self):
        events = []
        for second, value in ((0, 26), (2, 26), (4, 26), (6, 27), (8, None), (10, 27)):
            events += self.ingest(second, temperature=value)
        self.assertFalse(any(event["event_type"] == "TEMP_RISE" for event in events))

    def test_humidity_percentage_points(self):
        events = []
        for second in range(0, 12, 2):
            events += self.ingest(second, humidity=70 if second < 6 else 73.5)
        self.assertFalse(any(event["event_type"] == "HUMIDITY_RISE" for event in events))

    def test_eco2_crossing_rearm_and_no_startup_crossing(self):
        events = []
        for second in range(5):
            events += self.ingest(second, eco2=800)
        self.assertFalse(events)
        for second, value in enumerate([600, 720, 720, 720, 720, 640, 640, 640, 710, 710, 710], start=5):
            events += self.ingest(second, eco2=value)
        self.assertEqual(sum(e["event_type"] == "ECO2_THRESHOLD_CROSSED" for e in events), 2)

    def test_radar_debounce(self):
        events = []
        for second, presence in enumerate([0, 0, 0, 2, 0, 2, 2, 2, 2]):
            events += self.ingest(second, presence=presence)
        self.assertEqual(sum(e["event_type"] == "PRESENCE_CHANGED" for e in events), 1)

    def test_gaps_break_environment_and_radar_confirmation(self):
        events = []
        for second, value in ((0, 500), (1, 710), (2, 710), (100, 710)):
            events += self.ingest(second, eco2=value)
        self.assertFalse(any(event["event_type"] == "ECO2_THRESHOLD_CROSSED" for event in events))
        other = ContextStore(self.config)
        for second, code in ((0, 0), (1, 0), (2, 0), (3, 2), (4, 2), (100, 2)):
            packet = telemetry(stamp(second), presence=code)
            events += ingest_packet(other, packet, second, datetime.fromisoformat(packet["timestamp"]).timestamp())
        self.assertFalse(any(event["event_type"] == "PRESENCE_CHANGED" for event in events))

    def test_eco2_crossing_can_start_just_below_threshold(self):
        events = []
        for second, value in enumerate((690, 710, 710, 710)):
            events += self.ingest(second, eco2=value)
        self.assertEqual(sum(e["event_type"] == "ECO2_THRESHOLD_CROSSED" for e in events), 1)

    def test_aqi_plateau_and_humidity_full_rise_confirm_once(self):
        events = []
        for second in range(0, 22, 2):
            events += self.ingest(second, humidity=70 if second < 6 else 75, aqi=2 if second < 6 else 3)
        self.assertEqual(sum(e["event_type"] == "HUMIDITY_RISE" for e in events), 1)
        self.assertEqual(sum(e["event_type"] == "AQI_WORSENED" for e in events), 1)

    def test_q4_distinguishes_warmup_from_no_confirmed_change(self):
        self.ingest(0)
        self.assertEqual(answer_questions(self.store.snapshot(0), "C")["Q4"]["status"], "PARTIAL")
        for second in (2, 4, 6):
            self.ingest(second)
        self.assertEqual(answer_questions(self.store.snapshot(6), "C")["Q4"]["status"], "RESOLVED")

    def test_comparable_regions_still_require_temporal_alignment(self):
        self.config["regions"]["radar_camera_comparable"] = True
        self.ingest(10, presence=0)
        put_count(self.store, 10, 3, stamp(0))
        self.assertFalse(self.store.snapshot(10).document()["conflict"])

    def test_coverage_not_comparable_unless_declared(self):
        self.ingest(0, presence=0)
        put_count(self.store, 0, 3, stamp(0))
        self.assertFalse(self.store.snapshot(0).document()["conflict"])
        self.config["regions"]["radar_camera_comparable"] = True
        self.assertTrue(self.store.snapshot(0).document()["conflict"])

    def test_histories_bounded(self):
        for second in range(550):
            self.ingest(second)
        self.assertEqual(len(self.store.environment.history["temperature"]), self.config["environment"]["history_capacity"])


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = config()
        self.store = ContextStore(self.config)
        ingest_packet(self.store, telemetry(), 0)

    def decision(self, policy, now, events=None, busy=False):
        return policy.vision(self.store.snapshot(now).document(), now, events or [], True, busy, None)

    def test_a_schedule_and_missed_period(self):
        policy = PolicyEngine(self.config, "A", 0)
        self.assertEqual(self.decision(policy, 0).reason, "PERIODIC_SCHEDULE")
        policy.accepted_vision(0)
        self.assertIsNone(self.decision(policy, 10).action)
        self.assertEqual(self.decision(policy, 30, busy=True).reason, "MISSED_PERIOD_BUSY")
        self.assertIsNone(self.decision(policy, 31).action)
        self.assertEqual(self.decision(policy, 60).action, "vision")

    def test_b_never_uses_unknown_count_as_trigger(self):
        policy = PolicyEngine(self.config, "B", 0)
        self.assertEqual(self.decision(policy, 0).reason, "RADAR_DISTANCE_UNKNOWN")
        self.assertIsNone(self.decision(policy, 1, [{"event_type": "PRESENCE_CHANGED"}]).action)
        self.assertIsNone(self.decision(policy, 40).action)

    def test_cde_exact_visual_equivalence(self):
        policies = [PolicyEngine(self.config, mode, 0) for mode in "CDE"]
        for now in (0, 1, 29, 30, 60, 61):
            decisions = [asdict(self.decision(policy, now)) for policy in policies]
            self.assertEqual(decisions[0], decisions[1])
            self.assertEqual(decisions[1], decisions[2])
            if decisions[0]["action"]:
                for policy in policies:
                    policy.accepted_vision(now)
                put_count(self.store, now)

    def test_environment_event_reuses_fresh_count(self):
        policy = PolicyEngine(self.config, "C", 0)
        put_count(self.store, 0)
        decision = self.decision(policy, 2, [{"event_type": "TEMP_RISE"}])
        self.assertEqual(decision.reason, "ALREADY_FRESH")
        self.assertIsNone(decision.action)
        self.assertEqual(self.decision(policy, 61).reason, "COUNT_STALE")

    def test_budget_and_duplicates_skip(self):
        policy = PolicyEngine(self.config, "C", 0)
        snapshot = self.store.snapshot(0).document()
        self.assertEqual(policy.vision(snapshot, 0, [], True, False, "INSUFFICIENT_MEMORY").reason, "INSUFFICIENT_MEMORY")
        self.assertEqual(self.decision(policy, 0, busy=True).reason, "DUPLICATE_REQUEST")

    def test_no_text_slm_for_rule_resolved_question(self):
        policy = PolicyEngine(self.config, "D", 0)
        answer = answer_questions(self.store.snapshot(0), "D")["Q6"]
        self.assertIsNone(policy.interpretation("text", answer, 0, "key", set(), True, None).action)

    def test_dedup_ignores_timestamps_and_observation_ids(self):
        first = semantic_key("Q6", self.store.snapshot(0).document(), "gemma")
        ingest_packet(self.store, telemetry((datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()), 1)
        second = semantic_key("Q6", self.store.snapshot(1).document(), "gemma")
        self.assertEqual(first, second)

    def test_required_limits_not_null(self):
        for section, field in (("vision", "timeout_seconds"), ("environment", "eco2_rearm_threshold"), ("runtime", "max_run_seconds")):
            candidate = copy.deepcopy(self.config)
            candidate[section][field] = None
            with self.assertRaises(ValueError):
                validate_config(candidate)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tasks = TaskManager(1)
        self.gate = threading.Event()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.gate.set()
        for executor in self.tasks.executors.values():
            executor.shutdown(wait=True)

    def command(self, action="multimodal"):
        return Command(identifier(), "cycle", "run", "InterpretationAgent", action, utc_now(), utc_now(), {"question_id": "Q7"}, "TEST")

    def test_timeout_retains_physical_slot_and_bounds_queue(self):
        self.tasks.submit("gemma", self.command(), lambda: self.gate.wait(2), "one", 0, 1)
        self.tasks.submit("gemma", self.command(), lambda: "two", "two", 0, 5)
        self.assertEqual(self.tasks.submit("gemma", self.command(), lambda: 3, "three", 0, 5), "QUEUE_SATURATED")
        events = self.tasks.poll(2)
        self.assertEqual(events[0].event_type, "TASK_TIMEOUT")
        self.assertIsNotNone(self.tasks.active["gemma"])
        self.assertEqual(len(self.tasks.pending), 1)
        self.gate.set()
        self.tasks.active["gemma"].future.result(timeout=2)
        events = self.tasks.poll(3)
        self.assertTrue(events[0].payload["late"])

    def test_cancellation_keeps_worker_occupied_until_done(self):
        self.tasks.submit("gemma", self.command(), lambda: self.gate.wait(2), "one", 0, 10)
        self.assertEqual(len(self.tasks.cancel("run")), 1)
        self.assertTrue(self.tasks.busy)
        self.assertEqual(self.tasks.view(1)["active"][0]["status"], "DRAINING")

    def test_pending_task_expires_without_running(self):
        self.tasks.submit("gemma", self.command(), lambda: self.gate.wait(2), "one", 0, 10)
        invoked = []
        self.tasks.submit("gemma", self.command(), lambda: invoked.append(1), "two", 0, 1)
        self.tasks.poll(2)
        self.assertEqual(invoked, [])
        self.assertEqual(len(self.tasks.pending), 0)

    def test_remote_timeout_does_not_prove_runtime_stopped(self):
        from requests.exceptions import ReadTimeout

        def fail():
            raise ReadTimeout("El servidor puede seguir trabajando")
        self.tasks.submit("gemma", self.command(), fail, "one", 0, 10)
        with self.assertRaises(ReadTimeout):
            self.tasks.active["gemma"].future.result(timeout=2)
        events = self.tasks.poll(1)
        self.assertTrue(events[0].payload["remote_execution_uncertain"])
        self.assertTrue(self.tasks.busy)
        self.assertEqual(self.tasks.submit("gemma", self.command(), lambda: 1, "two", 2, 10), "REMOTE_EXECUTION_UNCERTAIN")

    def test_expired_queued_image_is_not_retained_or_executed(self):
        from dataclasses import replace

        self.tasks.submit("gemma", self.command(), lambda: self.gate.wait(2), "one", 0, 10)
        command = replace(self.command(), parameters={"question_id": "Q7", "image_expires_monotonic": 1})
        self.tasks.submit("gemma", command, lambda: self.fail("Imagen expirada ejecutada"), "two", 0, 10)
        events = self.tasks.poll(2)
        self.assertEqual(events[0].payload["reason"], "IMAGE_EXPIRED_IN_QUEUE")
        self.assertEqual(len(self.tasks.pending), 0)

    def test_timeout_and_completion_events_do_not_share_mutable_payload(self):
        self.tasks.submit("vision", self.command("vision"), lambda: {"count": 2}, "one", 0, 1)
        self.tasks.active["vision"].future.result(timeout=2)
        events = self.tasks.poll(2)
        self.assertEqual(events[0].event_type, "TASK_TIMEOUT")
        self.assertNotIn("result", events[0].payload)
        self.assertEqual(events[1].payload["result"], {"count": 2})


class InterpretationTests(unittest.TestCase):
    def setUp(self):
        self.store = ContextStore(config())
        ingest_packet(self.store, telemetry(), time.monotonic())
        self.snapshot = self.store.snapshot(time.monotonic())
        self.evidence = self.snapshot.document()["observations"]["temperature"]

    def response(self):
        return {"observed_facts": [{"evidence_id": self.evidence["observation_id"], "value": self.evidence["value"]}],
                "inferences": ["Coincidencia temporal, sin causalidad demostrada."], "unknowns": [], "recommendations": [],
                "evidence_references": [self.evidence["observation_id"]]}

    def text_response(self):
        return {"inferences": ["Coincidencia contextual, sin causalidad demostrada."], "unknowns": [], "recommendations": []}

    def test_validates_facts_and_does_not_send_images_in_d(self):
        calls = []
        def complete(prompt, image, **options):
            calls.append((image, options["system_prompt"]))
            return {"content": json.dumps(self.text_response()), "usage": {"completion_tokens": 20}}
        agent = InterpretationAgent(complete, "gemma")
        command = Command(identifier(), "cycle", "run", "InterpretationAgent", "text", utc_now(), utc_now(), {"question_id": "Q6"}, "TEST")
        result = agent.execute(command, self.snapshot, None, config()["interpretation"]["textual"], agent.prompt("Q6", self.snapshot, None))
        self.assertEqual(calls, [(None, agent.system_prompt("Q6"))])
        self.assertEqual(result["validation_status"], "VALIDATED")
        self.assertEqual(result["snapshot_id"], self.snapshot.snapshot_id)
        self.assertIn(self.evidence["observation_id"], result["evidence_references"])
        self.assertIn({"evidence_id": self.evidence["observation_id"], "value": self.evidence["value"]}, result["observed_facts"])
        prompt = agent.prompt("Q6", self.snapshot, None)
        self.assertNotIn(self.evidence["observation_id"], prompt)
        self.assertIn("<presence>", prompt)

    def test_text_uses_snapshot_facts_not_model_measurements(self):
        response = self.response()
        response["observed_facts"][0]["value"] = 99
        agent = InterpretationAgent(lambda *a, **kw: {"content": json.dumps(response)}, "gemma")
        command = Command(identifier(), "c", "r", "InterpretationAgent", "text", utc_now(), utc_now(), {"question_id": "Q6"}, "TEST")
        result = agent.execute(command, self.snapshot, None, config()["interpretation"]["textual"], "prompt")
        self.assertEqual(result["validation_status"], "VALIDATED")
        self.assertNotIn(99, [fact["value"] for fact in result["observed_facts"]])

    def test_rejects_duplicate_json_keys(self):
        content = '{"inferences":[],"unknowns":[],"recommendations":[],"unknowns":[]}'
        agent = InterpretationAgent(lambda *a, **kw: {"content": content}, "gemma")
        command = Command(identifier(), "c", "r", "InterpretationAgent", "text", utc_now(), utc_now(), {"question_id": "Q6"}, "TEST")
        result = agent.execute(command, self.snapshot, None, config()["interpretation"]["textual"], "prompt")
        self.assertEqual(result["validation_status"], "REJECTED")
        self.assertIn("Clave JSON duplicada", result["validation_error"])

    def test_multimodal_uses_authorized_image_without_sending_snapshot_ids(self):
        calls = []
        def complete(prompt, image, **options):
            calls.append((prompt, image, options["system_prompt"]))
            return {"content": json.dumps(self.text_response())}
        agent = InterpretationAgent(complete, "gemma")
        image_id = "image-1"
        command = Command(identifier(), "cycle", "run", "InterpretationAgent", "multimodal", utc_now(), utc_now(),
                          {"question_id": "Q7", "image_id": image_id}, "TEST")
        prompt = agent.prompt("Q7", self.snapshot, image_id)
        result = agent.execute(command, self.snapshot, b"image", config()["interpretation"]["multimodal"], prompt)
        self.assertEqual(calls, [(prompt, b"image", agent.system_prompt("Q7"))])
        self.assertIn(image_id, result["evidence_references"])
        self.assertNotIn(image_id, prompt)
        self.assertNotIn(self.evidence["observation_id"], prompt)
        self.assertIn("conteo YOLO", agent.system_prompt("Q7"))


class InferenceTests(unittest.TestCase):
    @patch("sense.inference.requests.post")
    def test_uses_completion_token_limit(self, post):
        post.return_value.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        request_completion("http://model", "gemma", "prompt", max_tokens=256, response_format={"type": "json_object"}, system_prompt="system")
        self.assertEqual(post.call_args.kwargs["json"]["max_completion_tokens"], 256)
        self.assertNotIn("max_tokens", post.call_args.kwargs["json"])
        self.assertEqual(post.call_args.kwargs["json"]["response_format"], {"type": "json_object"})
        self.assertEqual(post.call_args.kwargs["json"]["messages"][0], {"role": "system", "content": "system"})
        self.assertEqual(post.call_args.kwargs["json"]["messages"][1]["content"], "prompt")

    @patch("sense.inference.requests.post")
    def test_keeps_multimodal_content_for_images(self, post):
        post.return_value.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        request_completion("http://model", "gemma", "prompt", image=b"image")
        content = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "prompt"})
        self.assertEqual(content[1]["type"], "image_url")


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = config()
        self.log = ExperimentLog(Path(self.temp.name) / "runs.sqlite3")
        self.addCleanup(self.log.db.close)
        self.tasks = TaskManager(1)
        self.gate = threading.Event()
        self.addCleanup(self.cleanup_workers)
        self.captures = []
        self.slm_calls = []
        def capture():
            self.captures.append(1)
            return b"jpeg-fixture", utc_now()
        def complete(prompt, image, **kwargs):
            self.slm_calls.append(image)
            self.gate.wait(2)
            return {"content": "invalid model output"}
        self.controller = SenseOrchestrator(self.config, self.log, self.tasks, VisionAgent(capture, lambda image: 2),
                                            InterpretationAgent(complete, "gemma-test"),
                                            lambda: {"yolo": "ready", "text": "ready", "vision": "ready"},
                                            {"model_version": {"yolo": "fixed", "gemma": "gemma-test"}})
        self.now = time.monotonic()
        self.controller.resources = resources()

    def cleanup_workers(self):
        self.gate.set()
        for executor in self.tasks.executors.values():
            executor.shutdown(wait=True)

    def start(self, mode="E"):
        return self.controller.start(mode, self.now, "session", "scenario")

    def finish_vision(self):
        self.controller.tick(self.now, resources())
        self.tasks.active["vision"].future.result(timeout=2)
        self.controller.tick(self.now + 0.1, resources())

    def test_e_keeps_monitoring_during_multimodal_and_late_result_is_historical(self):
        run = self.start()
        self.controller.ingest(telemetry(), self.now, time.time())
        self.finish_vision()
        self.assertIsNotNone(self.tasks.active["gemma"])
        self.assertEqual(self.controller.fsm, "WAIT")
        original_count = self.controller.context.observations["count"]
        future = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()
        self.controller.ingest(telemetry(future, temperature=29), self.now + 2, time.time() + 2)
        self.controller.tick(self.now + 2, resources())
        self.assertEqual(self.controller.context.observations["temperature"].value, 29)
        self.assertEqual(self.controller.context.observations["count"], original_count)
        self.controller.stop("USER_STOP", self.now + 3)
        self.assertTrue(self.tasks.busy)
        self.gate.set()
        self.tasks.active["gemma"].future.result(timeout=2)
        self.controller.tick(self.now + 4, resources())
        self.assertTrue(self.controller.interpretations[-1]["historical"])
        self.assertEqual(self.controller.context.observations["temperature"].value, 29)
        self.assertIn('"type": "HISTORICAL_INTERPRETATION"', ''.join(self.log.export(run["run_id"])))

    def test_unchanged_count_does_not_interpret_every_image(self):
        self.gate.set()
        self.start()
        self.finish_vision()
        self.tasks.active["gemma"].future.result(timeout=2)
        self.controller.tick(self.now + 1, resources())
        self.controller.tick(self.now + 61, resources())
        self.tasks.active["vision"].future.result(timeout=2)
        self.controller.tick(self.now + 61.1, resources())
        self.assertEqual(len(self.captures), 2)
        self.assertEqual(len(self.slm_calls), 1)

    def test_new_run_resets_context_and_policy(self):
        self.start("B")
        self.controller.ingest(telemetry(), self.now, time.time())
        self.controller.tick(self.now, resources())
        self.assertFalse(self.captures)
        self.controller.stop("USER_STOP", self.now + 1)
        self.start("C")
        self.assertEqual(self.controller.context.observations, {})
        self.assertEqual(self.controller.policy.mode, "C")

    def test_vision_failure_degrades_without_stopping_sensors(self):
        def fail(_):
            raise RuntimeError("Cámara desconectada")
        self.controller.vision_agent.detector = fail
        self.start("C")
        self.controller.tick(self.now, resources())
        with self.assertRaises(RuntimeError):
            self.tasks.active["vision"].future.result(timeout=2)
        self.controller.tick(self.now + 0.1, resources())
        self.assertTrue(self.controller.running)
        self.assertTrue(any(t["to"] == "DEGRADED" for t in self.controller.transitions))
        self.controller.ingest(telemetry(), self.now + 1, time.time())
        self.assertEqual(self.controller.context.observations["temperature"].value, 26.33)

    def test_textual_mode_d_gets_structured_snapshot_without_image(self):
        self.start("D")
        self.controller.ingest(telemetry(), self.now, time.time())
        for kind in ("TEMP_RISE", "AQI_WORSENED"):
            self.controller.context.environment.events.append({"event_id": identifier(), "event_type": kind,
                "magnitude": 1, "captured_at": utc_now()})
        self.finish_vision()
        task = self.tasks.active["gemma"]
        self.assertIsNotNone(task)
        self.assertEqual(task.command.action, "text")
        self.assertIsNone(task.command.parameters["image_id"])
        self.gate.set()
        task.future.result(timeout=2)
        self.assertEqual(self.slm_calls, [None])

    def test_single_vision_per_cycle_even_with_conflict(self):
        self.config["regions"]["radar_camera_comparable"] = True
        self.start("C")
        self.controller.ingest(telemetry(presence=0), self.now, time.time())
        self.finish_vision()
        self.assertEqual(len(self.captures), 1)
        self.assertEqual(self.controller.cycle["requests"], 1)
        self.assertEqual(self.controller.fsm, "WAIT")

    def test_b_near_zone_command_is_linked_to_confirmed_evidence(self):
        run = self.start("B")
        wall = time.time()
        for second in range(3):
            at = datetime.fromtimestamp(wall + second, timezone.utc).isoformat()
            packet = telemetry(at)
            packet["presence"].update(static_distance_cm=20, motion_distance_cm=300, total_distance_cm=5)
            self.controller.ingest(packet, self.now + second, wall + second)
            self.controller.tick(self.now + second, resources())
            if second < 2:
                self.assertIsNone(self.tasks.active["vision"])
        command = self.tasks.active["vision"].command
        self.assertEqual(command.reason, "RADAR_NEAR_CONFIRMED")
        events = self.log.events(run["run_id"])
        event = next(row["payload"] for row in events if row["type"] == "RADAR_NEAR_CONFIRMED")
        self.assertEqual(command.parameters["trigger_event_id"], event["event_id"])
        self.assertEqual(len(event["evidence_ids"]), 3)
        self.assertEqual(self.controller.context.observations["presence"].value, 1)
        self.assertEqual(self.controller.view(self.now + 2)["reactive_trigger"]["state"], "NEAR")

    def test_trace_contains_config_snapshot_reason_and_transitions(self):
        run = self.start("C")
        self.finish_vision()
        self.controller.stop("USER_STOP", self.now + 1)
        events = list(self.log.export(run["run_id"]))
        serialized = ''.join(events)
        for required in ("config_hash", "FSM_TRANSITION", "COUNT_UNKNOWN", "snapshot_id", "RESULT_PUBLISHED", "RUN_FINISHED"):
            self.assertIn(required, serialized)

    def test_human_truth_is_separate_and_restart_marks_interrupted(self):
        run = self.start("B")
        self.log.human_record(run["run_id"], "GROUND_TRUTH", {"count": 5, "observed_at": utc_now()})
        self.assertEqual(self.controller.context.observations, {})
        second = ExperimentLog(self.log.path)
        self.addCleanup(second.db.close)
        self.assertEqual(second.run(run["run_id"])["status"], "INTERRUPTED")


if __name__ == "__main__":
    unittest.main()
