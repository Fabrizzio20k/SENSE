"""Comprobación inicial con MQTT y cámara simulados; no iniciar hardware real."""

import asyncio
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from app import RunCommand
from context import ACQUISITION_PROFILE, PROFILE
from helpers import TELEMETRY, mark_ready
from orchestrator import Conflict
from runtime import Runtime, Settings
from store import utc_now
from vision import file_hash


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = Runtime(Settings(data_dir=Path(self.directory.name)))

    async def asyncTearDown(self):
        await self.runtime.close()
        self.directory.cleanup()

    async def test_photo_and_zero_count_are_checked_then_photo_is_deleted(self):
        mark_ready(self.runtime)
        paths = []
        async def capture(job, timeout):
            self.assertIsNone(job["input_path"])
            self.assertEqual(job["kind"], "count")
            self.assertIsNone(self.runtime.engine.run_id)
            self.assertIsNotNone(self.runtime.store.flag("camera_busy"))
            output = Path(job["output_path"])
            paths.append(output)
            Image.new("RGB", (64, 48), "gray").save(output, "JPEG")
            return {"sha256": file_hash(output), "image_size": [64, 48], "visible_person_count": 0,
                    "boxes": [], "model_ref": {"model.ncnn.bin": "fixture"}, "timing": {"captured_at": None}}
        report = self.runtime.preflight
        with patch.object(self.runtime.actions.camera, "run", side_effect=capture):
            await self.runtime._verify_hardware(report)
        self.assertEqual(report["camera"]["status"], "ready")
        self.assertEqual(report["camera"]["visible_person_count"], 0)
        self.assertTrue(report["yolo"]["inference_verified"])
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertIsNone(self.runtime.store.flag("camera_busy"))
        self.assertEqual(self.runtime.store.db.execute("SELECT count(*) FROM runs").fetchone()[0], 0)
        self.assertTrue(all(source.latest is None for source in self.runtime.engine.sources.values()))

    async def test_missing_photo_blocks_all_live_variants_even_rules(self):
        mark_ready(self.runtime)
        with patch.object(self.runtime.actions.camera, "run", new_callable=AsyncMock, return_value={"visible_person_count": 0}):
            await self.runtime._verify_hardware(self.runtime.preflight)
        self.assertEqual(self.runtime.preflight["camera"]["status"], "failed")
        self.assertIsNone(self.runtime.store.flag("camera_busy"))
        with self.assertRaises(Conflict):
            await self.runtime.admit(RunCommand().model_dump())

    async def test_retained_duplicate_and_out_of_order_messages_cannot_refresh_sensors(self):
        now = time.monotonic()
        self.runtime.record_sensor_receipt(TELEMETRY, now, utc_now(), True)
        self.assertTrue(all(v["status"] == "pending" for v in self.runtime.sensor_report().values()))
        old = now-PROFILE["telemetry_silence_s"]-1
        self.runtime.record_sensor_receipt(TELEMETRY, old, utc_now(), False)
        self.runtime.record_sensor_receipt(TELEMETRY, now, utc_now(), False)
        earlier = json.loads(TELEMETRY)
        earlier["timestamp"] = "2026-10-17T00:00:00+00:00"
        self.runtime.record_sensor_receipt(json.dumps(earlier).encode(), now, utc_now(), False)
        self.assertTrue(all(v["status"] == "stale" for v in self.runtime.sensor_report().values()))

    async def test_invalid_sensor_does_not_hide_other_valid_sources_and_timeout_is_finite(self):
        payload = json.loads(TELEMETRY)
        payload["environment"]["ens160"]["aqi"] = 0
        self.runtime.input.connected = True
        self.runtime.record_sensor_receipt(json.dumps(payload).encode(), time.monotonic(), utc_now(), False)
        sensors = self.runtime.sensor_report()
        self.assertEqual(sensors["sht40"]["status"], "ready")
        self.assertEqual(sensors["ld2410c"]["status"], "ready")
        self.assertEqual(sensors["ens160"]["status"], "invalid")
        report = {"yolo": {"status": "unavailable"}}
        with patch.dict(ACQUISITION_PROFILE, {"startup_sensor_timeout_s": 0}):
            await self.runtime._verify_hardware(report)
        self.assertIn("error", report["sensors"]["ens160"])

    async def test_open_serves_diagnostics_while_preparation_is_running(self):
        waiting = asyncio.Event()
        async def prepare():
            await waiting.wait()
        with patch.object(self.runtime.input, "start"), patch.object(self.runtime, "prepare_dependencies", side_effect=prepare):
            await self.runtime.open()
            first_task = self.runtime.preparation_task
            self.assertTrue(self.runtime.preparing)
            self.runtime.request_preparation()
            self.assertIs(first_task, self.runtime.preparation_task)
            with self.assertRaises(Conflict):
                await self.runtime.admit(RunCommand().model_dump())

    async def test_broker_loss_and_stale_sensors_disable_admission(self):
        mark_ready(self.runtime)
        self.assertEqual(self.runtime.readiness_report()["status"], "ready")
        self.runtime.input.connected = False
        with self.assertRaises(Conflict):
            self.runtime.start(RunCommand().model_dump())
        self.runtime.input.connected = True
        for reading in self.runtime.sensor_readings.values():
            reading["received_monotonic"] -= PROFILE["telemetry_silence_s"]+1
        self.assertEqual(self.runtime.readiness_report()["status"], "degraded")

    async def test_rejected_preparation_does_not_mutate_active_session_diagnostic(self):
        mark_ready(self.runtime)
        self.runtime.start(RunCommand().model_dump())
        previous = copy.deepcopy(self.runtime.preflight)
        with self.assertRaises(Conflict):
            await self.runtime.prepare_dependencies()
        self.assertEqual(self.runtime.preflight, previous)


if __name__ == "__main__":
    unittest.main()
