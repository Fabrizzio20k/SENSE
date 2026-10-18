"""Pruebas preparadas para ejecutar en la Pi; no requieren activar cámara/modelo."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from app import RunCommand
from context import ACQUISITION_PROFILE
from orchestrator import Conflict
from runtime import Runtime, Settings
from slm import validate_interpretation
from vision import fuse_boxes, tile_origins
from helpers import mark_ready


class ToolContractTests(unittest.TestCase):
    def test_fusion_uses_its_argument(self):
        boxes = [[0, 0, 10, 10, .9], [2, 2, 12, 12, .8]]
        self.assertEqual(len(fuse_boxes(boxes, .4)), 1)
        self.assertEqual(len(fuse_boxes(boxes, .8)), 2)
        self.assertEqual(tile_origins(1600, 640, 160), [0, 480, 960])
        self.assertEqual(tile_origins(1200, 640, 160), [0, 480, 560])

    def test_interpretation_rejects_unknown_ids_and_thinking(self):
        response = {"status": "supported", "observed": [{"claim": "Presencia declarada por el radar.", "evidence_ids": ["radar-1"]}],
                    "inferred": [], "unknown": [], "requested_information": [], "recommendations": [], "answer": "Hay detección radar."}
        self.assertEqual(validate_interpretation(json.dumps(response), ["radar-1"])["status"], "supported")
        with self.assertRaises(ValueError):
            validate_interpretation(json.dumps(response), ["different"])
        with self.assertRaises(ValueError):
            validate_interpretation("<think>interno</think>"+json.dumps(response), ["radar-1"])

    def test_fault_plan_rejects_overlap(self):
        steps = [{"source_id": "camera", "mode": "disabled", "start_elapsed_s": 10, "duration_s": 20},
                 {"source_id": "camera", "mode": "drop", "start_elapsed_s": 25, "duration_s": 10}]
        with self.assertRaises(ValueError):
            RunCommand.model_validate({"variant": "C", "duration_s": 100, "fault_plan": steps})
        steps[1]["start_elapsed_s"] = 30
        self.assertEqual(len(RunCommand.model_validate({"variant": "C", "duration_s": 100, "fault_plan": steps}).fault_plan), 2)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = Runtime(Settings(data_dir=Path(self.directory.name)))
        mark_ready(self.runtime)
        self.request = RunCommand(variant="C", monitor_count=True).model_dump()
        self.runtime.start(self.request)

    def tearDown(self):
        self.runtime.engine.finish("cancelled", "test_end")
        self.runtime.store.close()
        self.runtime.instance_lock.close()
        self.directory.cleanup()

    def test_c_d_acquisition_profiles_match(self):
        first = self.runtime.store.run(self.runtime.engine.run_id)["manifest"]["acquisition_hash"]
        self.runtime.engine.finish()
        self.runtime.start({**self.request, "variant": "D"})
        second = self.runtime.store.run(self.runtime.engine.run_id)["manifest"]["acquisition_hash"]
        self.assertEqual(first, second)

    def test_queue_is_bounded_and_uncertain_model_blocks_new_work(self):
        for _ in range(ACQUISITION_PROFILE["heavy_queue_capacity"]):
            self.runtime.actions.submit("count_people", "test")
        with self.assertRaises(Conflict):
            self.runtime.actions.submit("count_people", "test")
        self.runtime.actions.queue.clear()
        self.runtime.store.flag("slm_busy", {"state": "unknown"}, write=True)
        with self.assertRaises(Conflict):
            self.runtime.actions.submit("count_people", "test")

    def test_snapshot_reuse_is_exact(self):
        snapshot = self.runtime.engine.snapshot()
        self.runtime.engine.emit("snapshot.created", snapshot)
        stored = self.runtime.store.snapshot(self.runtime.engine.run_id, snapshot["snapshot_id"])
        self.assertEqual(snapshot, stored)

    def test_uploaded_count_is_never_current_camera_count(self):
        source = self.runtime.engine.sources["camera"]
        source.status = "recent_receipt"
        source.latest = {"values": {"visible_person_count": 2}, "elapsed_s": 0,
                         "time_basis": "uploaded_image_unknown_capture_time"}
        self.assertFalse(self.runtime.actions.count_is_fresh())

    def test_scheduled_camera_restore_reopens_bounded_acquisition(self):
        self.runtime.engine.request["monitor_count"] = False
        self.runtime.actions.vision_suspended = True
        self.runtime.actions.vision_failures = 3
        source = self.runtime.engine.sources["camera"]
        source.status, source.availability_version = "awaiting_fresh_data", 4
        self.runtime.actions.tick()
        self.assertFalse(self.runtime.actions.vision_suspended)
        self.assertEqual(self.runtime.actions.vision_failures, 0)
        self.assertIsNone(self.runtime.actions.count_need_started)


if __name__ == "__main__":
    unittest.main()
