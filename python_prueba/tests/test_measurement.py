"""Regresiones preparadas, no ejecutadas: W obligatorios sin hardware ni modelos."""

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import RunCommand, create_app
from context import PROFILE
from experiment import POWER_PROTOCOL
from runtime import Runtime, Settings
from store import Store
from helpers import mark_ready


class MeasurementStoreTests(unittest.TestCase):
    def test_queue_survives_restart_and_recovery_adds_final_task(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"measurement.sqlite3"
            store = Store(path)
            store.create("run", None, "hash", {"source_mode": "live", "profile": PROFILE,
                         "power_protocol": dict(POWER_PROTOCOL), "request": {"duration_s": 600}}, "boot")
            state = store.measurement("run", 65)
            self.assertEqual([task["task_id"] for task in state["tasks"]], ["power-0", "power-30", "power-60"])
            store.append("run", "power.task_omitted", {
                "task_id": "power-30", "reason": "No se observó el instrumento", "observer_id": "operator-01"}, 65, "boot")
            store.close()
            store = Store(path)
            try:
                state = store.measurement("run")
                self.assertEqual(state["elapsed_s"], 65)
                self.assertEqual(state["status"], "pending_review")
                self.assertEqual(state["pending_count"], 3)  # inicio, 60 s y cierre
                self.assertEqual(state["omitted_count"], 1)
                self.assertEqual(state["tasks"][-1]["task_id"], "final")
            finally:
                store.close()

    def test_old_and_replay_runs_do_not_gain_retroactive_obligations(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/"old.sqlite3")
            try:
                for run_id, mode, expected in [("old", "live", "legacy"), ("replay", "replay", "not_required")]:
                    store.create(run_id, None, "hash", {"source_mode": mode, "profile": PROFILE}, "boot")
                    store.finish(run_id, "completed", {}, 60, "boot")
                    self.assertEqual(store.measurement(run_id)["status"], expected)
                    self.assertFalse(json.loads(store.export(run_id)["manifest.json"])["partial"])
            finally:
                store.close()


class MeasurementAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()

        async def no_hardware_open(runtime):
            pass

        self.open_patch = patch.object(Runtime, "open", no_hardware_open)
        self.open_patch.start()
        self.client = TestClient(create_app(Settings(data_dir=Path(self.directory.name))))
        self.client.__enter__()
        self.runtime = self.client.app.state.runtime
        mark_ready(self.runtime)
        run_id = self.runtime.start(RunCommand(duration_s=600).model_dump())
        self.prefix = "/v1/runs/"+run_id
        self.run_id = run_id

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.open_patch.stop()
        self.directory.cleanup()

    def power(self, task, observed, value=6, **extra):
        return self.client.post(self.prefix+"/power-readings", json={
            "value": value, "task_id": task, "observed_elapsed_s": observed, **extra})

    def omit(self, task, reason="No observé el vatímetro"):
        return self.client.post(self.prefix+"/power-tasks/"+task+"/omit", json={"reason": reason})

    def test_stop_keeps_pending_and_api_rejects_premature_closure(self):
        self.runtime.engine.tick(65)
        self.assertEqual(self.client.post(self.prefix+"/measurement-close", json={}).status_code, 409)
        stopped = self.client.post(self.prefix+"/finish", json={})
        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertEqual(stopped.json()["status"], "completed")
        self.assertEqual(stopped.json()["measurement"]["pending_count"], 4)
        self.assertEqual(self.client.post(self.prefix+"/measurement-close", json={}).status_code, 409)
        manifest = json.loads(self.runtime.store.export(self.run_id)["manifest.json"])
        self.assertTrue(manifest["partial"])
        self.assertEqual(manifest["measurement"]["status"], "pending_review")

    def test_late_current_W_cannot_fill_a_past_slot(self):
        self.runtime.engine.tick(65)
        self.assertEqual(self.power("power-0", 65).status_code, 422)
        self.assertEqual(self.power("power-999", 65).status_code, 422)
        self.assertEqual(self.power("power-0", 5).status_code, 200)
        self.assertEqual(self.power("power-0", 6).status_code, 409)
        self.assertEqual(self.omit("power-30", "     ").status_code, 422)
        self.assertEqual(self.omit("power-30").status_code, 200)
        self.assertEqual(self.omit("power-30").status_code, 200)
        rows = self.runtime.store.events(self.run_id, limit=1000)
        self.assertEqual(sum(e["type"] == "power.task_omitted" for e in rows), 1)
        self.assertEqual(sum(e["type"] == "power.reading_recorded" for e in rows), 1)

    def test_closed_measurement_preserves_omissions_and_prohibits_power_edits(self):
        self.runtime.engine.tick(65)
        self.assertEqual(self.power("power-0", 5).status_code, 200)
        self.assertEqual(self.omit("power-30").status_code, 200)
        self.assertEqual(self.power("power-60", 61).status_code, 200)
        self.assertEqual(self.power("final", 64).status_code, 200)
        self.client.post(self.prefix+"/finish", json={})
        closed = self.client.post(self.prefix+"/measurement-close", json={})
        self.assertEqual(closed.status_code, 200, closed.text)
        state = closed.json()["measurement"]
        self.assertEqual(state["status"], "closed_with_omissions")
        self.assertEqual(state["omitted_count"], 1)
        repeated = self.client.post(self.prefix+"/measurement-close", json={})
        self.assertEqual(repeated.json()["last_sequence"], closed.json()["last_sequence"])
        self.assertEqual(self.omit("power-30").json()["last_sequence"], closed.json()["last_sequence"])
        self.assertEqual(self.power("final", 65).status_code, 409)
        self.assertEqual(self.omit("final").status_code, 409)
        exported = self.runtime.store.export(self.run_id)
        manifest = json.loads(exported["manifest.json"])
        self.assertFalse(manifest["partial"])
        self.assertEqual(manifest["measurement"]["tasks"][1]["reason"], "No observé el vatímetro")
        run_row = next(csv.DictReader(io.StringIO(exported["runs.csv"].decode())))
        self.assertEqual(run_row["measurement_status"], "closed_with_omissions")
        self.assertEqual(run_row["power_omitted_count"], "1")
        self.assertEqual(len(list(csv.DictReader(io.StringIO(exported["power_readings.csv"].decode())))), 3)

    def test_terminal_deadline_replaces_duplicate_periodic_slot(self):
        self.runtime.engine.tick(60)
        self.runtime.engine.finish()
        state = self.client.get(self.prefix).json()["measurement"]
        self.assertEqual([task["task_id"] for task in state["tasks"]], ["power-0", "power-30", "final"])
        self.assertEqual(self.power("final", 20).status_code, 422)
        self.assertEqual(self.power("final", 60).status_code, 200)

    def test_correction_keeps_task_and_counter_does_not_resolve_W(self):
        self.runtime.engine.tick(65)
        first = self.power("power-0", 5).json()["event"]["payload"]["reading_id"]
        correction = self.power("power-0", 6, value=7, supersedes_reading_id=first, note="Error de transcripción")
        self.assertEqual(correction.status_code, 200, correction.text)
        self.assertEqual(self.client.post(self.prefix+"/power-readings", json={
            "quantity": "energy_counter", "unit": "Wh", "value": 10, "observed_elapsed_s": 30}).status_code, 200)
        self.assertEqual(self.client.get(self.prefix).json()["measurement"]["pending_count"], 2)


if __name__ == "__main__":
    unittest.main()
