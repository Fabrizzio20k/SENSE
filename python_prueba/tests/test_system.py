import copy
import csv
import io
import json
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from context import LABELS, PROFILE, parse_message
from experiment import Sampler, energy_estimate
from orchestrator import Conflict, Engine
from runtime import FIXTURE, Settings
from store import Store


BASE = json.loads(FIXTURE.read_text().splitlines()[0])
EPOCH = datetime(2026, 10, 17, tzinfo=timezone.utc)


def message(t, temperature=27, state=2):
    value = copy.deepcopy(BASE)
    value["timestamp"] = (EPOCH+timedelta(seconds=t)).isoformat()
    value["environment"]["sht40"]["temperature_c"] = temperature
    value["presence"].update(state_code=state, state=LABELS[state])
    return value


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)/"test.sqlite3"
        self.store = Store(self.path)
        self.engine = Engine(self.store)
        self.request = {"duration_s": 600, "source_mode": "live"}
        self.run_id, _ = self.engine.start(self.request, "first", {"source_mode": "live", "profile": PROFILE})

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def feed(self, t, **kwargs):
        self.engine.ingest(json.dumps(message(t, **kwargs)).encode(), t, receipt_elapsed=t)

    def answers(self, reason):
        return [e for e in self.store.events(self.run_id, limit=10000)
                if e["type"] == "answer.validated" and e["payload"]["content_json"]["reason"] == reason]

    def test_presence_modes_do_not_become_entries(self):
        for t, state in ((0, 2), (2, 3), (4, 1), (6, 0), (8, 0), (10, 2), (12, 3)):
            self.feed(t, state=state)
        self.assertEqual(len(self.answers("presence_initialized")), 1)
        changes = self.answers("presence_changed")
        self.assertEqual([e["payload"]["content_json"]["trigger"]["transition"] for e in changes], ["exit", "entry"])
        self.assertTrue(self.engine.snapshot()["confirmed_radar_presence"])

    def test_persistence_hysteresis_and_single_episode(self):
        for t in range(0, 242, 2):
            self.feed(t, temperature=27 if t <= 180 else 28)
        openings = self.answers("environment_change_persistent")
        self.assertEqual(len(openings), 1)
        self.assertGreaterEqual(openings[0]["elapsed_s"], 206)
        for t in range(242, 302, 2):
            self.feed(t, temperature=27.3)
        self.assertEqual(len(self.answers("environment_recovered")), 0)
        for t in range(302, 362, 2):
            self.feed(t, temperature=27.2)
        recoveries = self.answers("environment_recovered")
        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0]["payload"]["followup_of_episode_id"], openings[0]["episode_id"])
        self.assertEqual(len(self.answers("environment_change_persistent")), 1)

    def test_silence_does_not_confirm_pending_change(self):
        for t in range(0, 198, 2):
            self.feed(t, temperature=27 if t <= 180 else 28)
        self.engine.tick(204)
        for t in range(204, 240, 2):
            self.feed(t, temperature=28)
        self.assertFalse(self.answers("environment_change_persistent"))

    def test_retained_duplicate_and_old_queue_do_not_renew(self):
        self.feed(0)
        self.feed(2)
        self.engine.ingest(json.dumps(message(2)).encode(), 6)
        self.engine.ingest(json.dumps(message(4)).encode(), 6.5, retained=True)
        self.engine.tick(9)
        self.assertEqual(self.engine.sources["sht40"].status, "stale_receipt")
        self.assertEqual(self.engine.sources["sht40"].latest["elapsed_s"], 2)
        self.engine.tick(20)
        self.engine.ingest(json.dumps(message(6)).encode(), 6)
        self.assertEqual(self.engine.sources["sht40"].latest["elapsed_s"], 2)

    def test_partial_validation_and_restore_require_new_data(self):
        bad = message(0)
        bad["environment"]["ens160"]["tvoc_ppb"] = True
        self.engine.ingest(json.dumps(bad).encode(), 0)
        self.assertTrue(self.engine.sources["sht40"].usable)
        self.assertFalse(self.engine.sources["ens160"].usable)
        self.feed(2)
        fault = self.engine.add_fault({"source_id": "ens160", "mode": "disabled", "start_after_s": 0,
                                       "duration_s": 45, "reason": "test"})
        self.feed(4)
        self.assertTrue(self.engine.sources["sht40"].usable)
        self.assertTrue(self.engine.sources["ld2410c"].usable)
        self.assertFalse(self.engine.sources["ens160"].usable)
        self.engine.clear_fault(fault["fault_id"])
        self.assertEqual(self.engine.sources["ens160"].status, "awaiting_fresh_data")
        self.engine.ingest(json.dumps(message(4)).encode(), 5)
        self.assertFalse(self.engine.sources["ens160"].usable)
        self.feed(6)
        self.assertTrue(self.engine.sources["ens160"].usable)

    def test_scheduled_fault_deadline_and_idempotency(self):
        self.feed(0)
        fault = self.engine.add_fault({"source_id": "ld2410c", "mode": "drop", "start_after_s": 2,
                                       "duration_s": 4, "reason": "test"})
        self.engine.tick(2)
        self.assertEqual(self.engine.faults[fault["fault_id"]]["status"], "applied")
        with self.assertRaises(Conflict):
            self.engine.add_fault({"source_id": "ld2410c", "mode": "freeze", "start_after_s": 1, "duration_s": 2})
        self.engine.tick(6)
        self.assertEqual(self.engine.sources["ld2410c"].status, "awaiting_fresh_data")
        self.assertEqual(self.engine.start(self.request, "first", {})[0], self.run_id)
        with self.assertRaises(Conflict):
            self.engine.start({**self.request, "duration_s": 300}, "first", {})

    def test_recovery_after_restart_never_replays_work(self):
        self.feed(12)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.run(self.run_id)["status"], "interrupted")
        events = self.store.events(self.run_id, limit=1000)
        self.assertEqual(events[-1]["elapsed_s"], 12)
        self.assertEqual(events[-1]["type"], "run.interrupted")


class ContractTests(unittest.TestCase):
    def test_json_trust_boundary(self):
        for raw in (b'{"schema":1,"schema":2}', b'{"timestamp":NaN}', b'{"value":1e999}', b"[]", b"x"*16385):
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                parse_message(raw)

    def test_energy_coverage_and_corrections(self):
        def reading(identifier, t, watts=6, supersedes=None):
            return {"reading_id": identifier, "observed_elapsed_s": t, "value": watts,
                    "quantity": "power", "supersedes_reading_id": supersedes}
        rows = [reading("a", 0), reading("b", 30), reading("c", 60)]
        self.assertAlmostEqual(energy_estimate(rows, 60)["estimated_Wh"], .1)
        self.assertEqual(energy_estimate(rows, 60)["coverage_ratio"], 1)
        self.assertIsNone(energy_estimate(rows[:1], 60)["estimated_Wh"])
        self.assertIsNone(energy_estimate([rows[0], reading("d", 90)], 90)["estimated_Wh"])
        corrected = rows+[reading("fixed", 30, 12, "b")]
        self.assertAlmostEqual(energy_estimate(corrected, 60)["estimated_Wh"], .15)
        counters = [{"reading_id": "c1", "quantity": "energy_counter", "normalized_value": 100, "observed_elapsed_s": 0},
                    {"reading_id": "c2", "quantity": "energy_counter", "normalized_value": 101, "observed_elapsed_s": 60}]
        self.assertEqual(energy_estimate(counters, 60)["counter_estimates"]["unspecified"]["delta_Wh"], 1)
        counters[1]["normalized_value"] = 1
        self.assertIsNone(energy_estimate(counters, 60)["counter_estimates"]["unspecified"]["delta_Wh"])

    def test_unsupported_resource_is_null_and_does_not_stop_policy(self):
        sampler = Sampler()
        with patch("experiment.psutil.swap_memory", side_effect=OSError):
            sample = sampler.sample("replay")
        self.assertIsNone(sample["swap_used_bytes"])
        self.assertIn("swap:OSError", sample["collection_errors"])
        self.assertIn("host_replay", sample["scope"])


class APITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Settings(mode="replay", data_dir=Path(self.directory.name), replay_speed=1)))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def start(self):
        response = self.client.post("/v1/runs", json={"source_mode": "replay", "duration_s": 30},
                                    headers={"Idempotency-Key": "api-test"})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["run_id"]

    def test_admission_cancel_reconnect_and_exports(self):
        run_id = self.start()
        prefix = "/v1/runs/"+run_id
        again = self.client.post("/v1/runs", json={"source_mode": "replay", "duration_s": 30}, headers={"Idempotency-Key": "api-test"})
        self.assertEqual(again.json()["run_id"], run_id)
        self.assertEqual(self.client.post("/v1/runs", json={"source_mode": "replay"}).status_code, 409)
        fault = self.client.post(prefix+"/faults", json={"source_id": "ens160", "mode": "disabled"})
        self.assertEqual(fault.status_code, 200, fault.text)
        self.assertEqual(self.client.post(prefix+"/power-readings", json={"value": 6}).status_code, 409)
        self.assertEqual(self.client.post(prefix+"/annotations", json={"label": '=HYPERLINK("x")'}).status_code, 200)
        question = self.client.post(prefix+"/questions", json={"type": "environment"})
        self.assertEqual(question.status_code, 200, question.text)
        self.assertEqual(question.json()["content_json"]["slm_calls"], 0)
        result = self.client.post(prefix+"/cancel", json={}).json()
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.client.post(prefix+"/cancel", json={}).json()["last_sequence"], result["last_sequence"])
        stream = self.client.get(prefix+"/events").text
        self.assertIn("event: run.cancelled", stream)
        cursor = result["last_sequence"]-2
        recovered = self.client.get(prefix+"/events", headers={"Last-Event-ID": f"{run_id}:{cursor}"}).text
        ids = [line[4:] for line in recovered.splitlines() if line.startswith("id: ")]
        self.assertEqual(ids, [f"{run_id}:{cursor+1}", f"{run_id}:{cursor+2}"])
        self.assertEqual(self.client.get(prefix+"/events?after=999999").status_code, 400)
        archive = zipfile.ZipFile(io.BytesIO(self.client.get(prefix+"/export.zip").content))
        manifest = json.loads(archive.read("manifest.json"))
        self.assertFalse(manifest["partial"])
        self.assertEqual(manifest["cutoff_sequence"], result["last_sequence"])
        self.assertIn('=HYPERLINK(\\"x\\")', archive.read("events.jsonl").decode())
        annotations = list(csv.DictReader(io.StringIO(archive.read("annotations.csv").decode())))
        self.assertTrue(annotations[0]["label"].startswith("'="))
        for filename in archive.namelist():
            if filename.endswith(".csv"):
                rows = list(csv.DictReader(io.StringIO(archive.read(filename).decode())))
                self.assertTrue(all(row["export_id"] == manifest["export_id"] for row in rows))
        self.assertEqual(self.client.get(prefix+"/exports/unknown.csv").status_code, 404)

    def test_http_validation_and_page(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.post("/v1/runs", json={"variant": "unknown"}).status_code, 422)
        self.assertEqual(self.client.post("/v1/runs", json={"source_mode": "replay"}, headers={"Origin": "https://other.example"}).status_code, 403)
        self.assertEqual(self.client.post("/v1/runs", content="x"*33000).status_code, 413)
        self.assertEqual(self.client.post("/v1/runs", content='{"duration_s":NaN}').status_code, 400)
        self.assertEqual(self.client.post("/v1/runs", content='{"duration_s":1,"duration_s":2}').status_code, 400)

    def test_full_replay_finishes_with_manifest_and_no_models(self):
        self.client.app.state.runtime.settings.replay_speed = 1000
        response = self.client.post("/v1/runs", json={"source_mode": "replay", "duration_s": 1200})
        run_id = response.json()["run_id"]
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            run = self.client.get("/v1/runs/"+run_id).json()
            if run["status"] != "running":
                break
            time.sleep(.05)
        self.assertEqual(run["status"], "completed", run)
        self.assertEqual(run["manifest"]["measurement_class"], "simulation")
        data = self.client.get("/v1/runs/"+run_id+"/exports/observations.csv").text
        observations = list(csv.DictReader(io.StringIO(data)))
        self.assertEqual(sum(row["metric"] == "temperature_c" and row["accepted"] == "True" for row in observations), 490)


if __name__ == "__main__":
    unittest.main()
