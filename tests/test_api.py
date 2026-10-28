import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from sense.service import ExperimentService


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = main.app.test_client()
        self.calls = []
        self.reserved = threading.Event()
        self.service = SimpleNamespace(reserved=self.reserved, reserve=self.reserve, call=self.call)
        self.patches = [patch.object(main, "get_experiments", return_value=self.service),
                        patch.object(main, "experiments", self.service)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.before = main.state["sandbox_busy"]
        main.state["sandbox_busy"] = False
        self.addCleanup(lambda: main.state.update(sandbox_busy=self.before))

    def reserve(self):
        if self.reserved.is_set():
            raise ValueError("Worker ocupado")
        self.reserved.set()

    def call(self, action, payload=None):
        self.calls.append((action, payload))
        return {"run_id": "test-run"} if action == "start" else {"ok": True}

    def test_start_contract_and_exclusive_sandbox(self):
        response = self.client.post('/api/experiments/start', json={"mode": "E"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json, {"run_id": "test-run"})
        self.assertIn("Finaliza la medición", main.enqueue_sandbox_task("test", lambda: None))
        self.assertEqual(self.client.post('/api/experiments/start', json={"mode": "C"}).status_code, 409)

    def test_invalid_inputs_do_not_start(self):
        for body in (None, [], {"mode": "G"}, {"mode": "C", "scenario_id": []}):
            self.assertEqual(self.client.post('/api/experiments/start', json=body).status_code, 400)
        self.assertFalse(self.calls)

    def test_presence_control_requires_a_valid_mode(self):
        manual = self.client.post('/api/experiments/presence', json={"mode": "manual", "detected": True})
        self.assertEqual(manual.status_code, 202)
        self.assertEqual(self.calls[-1], ("presence", {"detected": True}))
        automatic = self.client.post('/api/experiments/presence', json={"mode": "auto"})
        self.assertEqual(automatic.status_code, 202)
        self.assertEqual(self.calls[-1], ("presence", {"detected": None}))
        for body in (None, {"mode": "manual"}, {"mode": "manual", "detected": 1}, {"mode": "other"}):
            self.assertEqual(self.client.post('/api/experiments/presence', json=body).status_code, 400)

    def test_busy_manual_task_blocks_experiment(self):
        main.state["sandbox_busy"] = True
        self.assertEqual(self.client.post('/api/experiments/start', json={"mode": "A"}).status_code, 409)
        self.assertFalse(self.reserved.is_set())

    def test_mqtt_malformed_data_does_not_crash_callback(self):
        for payload in (b'[]', b'{"temperature":NaN}', b'\xff', b'{', b'x' * 65537):
            main.mqtt_message(None, None, SimpleNamespace(payload=payload))

    def test_assets_and_preparation_still_exist(self):
        response = self.client.get('/')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        for expected in (b'id="preparation"', b'id="take-photo"', b'id="measurement-mode"', b'id="measurement-pipeline"'):
            self.assertIn(expected, response.data)
        for asset in ('measurement.js', 'measurement.css'):
            with self.client.get('/public/' + asset) as response:
                self.assertEqual(response.status_code, 200)

    def test_human_records_are_validated_and_separate(self):
        from unittest.mock import Mock
        from sense.contracts import utc_now

        self.service.log = SimpleNamespace(run=lambda _: {"run_id": "run"}, human_record=Mock(return_value="record"))
        truth = {"observed_at": utc_now(), "region": "camera", "visible_people": 3}
        response = self.client.post('/api/experiments/run/human-records', json={"kind": "GROUND_TRUTH", "payload": truth})
        self.assertEqual(response.status_code, 201)
        energy = {"observed_at": utc_now(), "scope": "whole_run", "value": 2.4, "unit": "Wh"}
        self.assertEqual(self.client.post('/api/experiments/run/human-records', json={"kind": "EXTERNAL_ENERGY", "payload": energy}).status_code, 201)
        for kind, payload in (("GROUND_TRUTH", dict(truth, visible_people=-1)), ("EXTERNAL_ENERGY", dict(energy, unit="CPU%"))):
            self.assertEqual(self.client.post('/api/experiments/run/human-records', json={"kind": kind, "payload": payload}).status_code, 400)
        self.assertEqual(self.service.log.human_record.call_count, 2)

    def test_invalid_measurement_config_does_not_block_preparation(self):
        with patch.object(main, 'get_experiments', side_effect=ValueError('Falta timeout_seconds')):
            self.assertEqual(self.client.post('/api/experiments/start', json={"mode": "E"}).status_code, 409)
            with self.client.get('/') as response:
                self.assertEqual(response.status_code, 200)


class ServiceTests(unittest.TestCase):
    def test_real_dispatcher_start_ingest_stop_and_export_without_hardware(self):
        from test_sense import ROOT, resources, telemetry

        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            readiness = lambda: {"yolo": "error", "text": "error", "vision": "error"}
            with patch('sense.service.ResourceMonitor') as monitor:
                monitor.return_value.sample.return_value = resources()
                service = ExperimentService(ROOT, data, ROOT / 'sense' / 'pilot.yaml', None, None, None, 'test', readiness)
                try:
                    service.reserve()
                    run = service.call('start', {"mode": "B"})
                    service.ingest(telemetry(), __import__('time').monotonic(), __import__('time').time())
                    service.call('query', {"question_id": "Q3"})
                    service.call('stop')
                    rows = [json.loads(line) for line in service.log.export(run['run_id'])]
                    self.assertTrue(any(row['type'] == 'OBSERVATIONS_RECEIVED' for row in rows))
                    self.assertTrue(any(row['type'] == 'RUN_FINISHED' for row in rows))
                    self.assertFalse(service.controller.running)
                finally:
                    service.close()


if __name__ == '__main__':
    unittest.main()
