"""Fixtures de admisión; no representan una prueba de hardware."""

import time

from runtime import FIXTURE
from store import utc_now


TELEMETRY = FIXTURE.read_bytes().splitlines()[0]


def mark_ready(runtime):
    runtime.input.connected = True
    runtime.sensor_timestamps.clear()
    runtime.sensor_readings.clear()
    runtime.record_sensor_receipt(TELEMETRY, time.monotonic(), utc_now(), False)
    runtime.preflight = {"status": "ready", "yolo": {"status": "ready"}, "gemma": {"status": "ready"},
                         "gemma_warmup": {"status": "ready"}, "sensors": runtime.sensor_report(),
                         "camera": {"status": "ready", "visible_person_count": 0, "duration_s": 0}}
