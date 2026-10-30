import csv
import io
import json
import tempfile
import time
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from sense.agents import InterpretationAgent, VisionAgent
from sense.contracts import utc_now
from sense.contracts import Command, identifier
from sense.orchestrator import SenseOrchestrator
from sense.protocol import validate_guided_start, validate_observation
from sense.runtime import TaskManager
from sense.storage import ExperimentLog
from sense.trace import export_csv_zip
from test_sense import config, resources, telemetry


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = ExperimentLog(Path(self.temp.name) / 'test.sqlite3')
        self.addCleanup(self.log.db.close)
        self.tasks = TaskManager(1)
        self.addCleanup(lambda: [executor.shutdown(wait=True) for executor in self.tasks.executors.values()])
        self.config = config()
        self.controller = SenseOrchestrator(self.config, self.log, self.tasks,
            VisionAgent(lambda: (b'image', utc_now()), lambda _: 2), InterpretationAgent(None, 'test'),
            lambda: dict(yolo='error', text='error', vision='error'), {'model_version': {'yolo': 'test'}})
        self.controller.resources = resources()
        self.initial = dict(observed_at=utc_now(), power_observed_at=utc_now(), people_observed_at=utc_now(),
                            region='rasp_shared_view', power_w=0, visible_people=0,
                            observer='Operador', instrument='Medidor', equipment='Pi + sensores', unavailable_fields=[])
        self.experiment = dict(guided=True, scenario_id='S2', repetition=1, initial_observation=self.initial)

    def start(self, mode='B'):
        return self.controller.start(mode, 0, 'session', 'S2', self.experiment)

    def events(self, run_id):
        return [json.loads(line) for line in self.log.export(run_id)]

    def test_full_1800_second_run_stops_without_browser_and_exports_csv(self):
        run = self.start()
        for second in range(1801):
            with self.log.transaction():
                self.controller.tick(second, resources())
        self.assertFalse(self.controller.running)
        self.assertEqual(self.log.quality(run['run_id'])['samples'], 1800)
        self.assertEqual(self.log.quality(run['run_id'])['missing_samples'], 0)
        self.assertEqual(self.log.run(run['run_id'])['finish_reason'], 'MAX_RUN_DURATION')
        requests = self.log.observer_requests(run['run_id'])
        self.assertEqual(sum(r['reason'].startswith('PERIODIC_W:') for r in requests), 29)
        self.assertEqual(sum(r['reason'].startswith('SCENARIO_CHECKPOINT:') for r in requests), 5)
        self.assertEqual(requests[-1]['reason'], 'RUN_FINAL')
        self.assertFalse(self.log.quality(run['run_id'])['record_complete'])
        with export_csv_zip(self.log.path, run['run_id']) as exported, zipfile.ZipFile(exported) as archive:
            self.assertEqual(len(list(csv.DictReader(io.StringIO(archive.read('samples_1s.csv').decode('utf-8-sig'))))), 1800)
            self.assertIn('inference_tasks.csv', archive.namelist())
            self.assertIn('question_results.csv', archive.namelist())
            manifest = json.loads(archive.read('replay-manifest.json'))
            self.assertEqual(manifest['schema'], 'sense-replay.v1')
            self.assertEqual(manifest['run_id'], run['run_id'])
            self.assertTrue(set(manifest['files']).issubset(archive.namelist()))
            self.assertEqual(json.loads(archive.read('metadata.json'))['repetition'], 1)

    def test_gaps_remain_missing_and_retained_readings_age(self):
        run = self.start()
        self.controller.ingest(telemetry(), 0, time.time())
        self.controller.tick(1, resources())
        self.controller.tick(4, resources())
        self.controller.stop('USER_STOP', 5)
        samples = [r['payload'] for r in self.events(run['run_id']) if r['type'] == 'SAMPLE_1S']
        self.assertEqual([s['second'] for s in samples], [0, 1, 4])
        self.assertEqual(samples[-1]['temperature_c'], samples[1]['temperature_c'])
        self.assertEqual(samples[-1]['temperature_observation_id'], samples[1]['temperature_observation_id'])
        self.assertGreater(samples[-1]['temperature_age_s'], samples[1]['temperature_age_s'])
        self.assertIsNone(samples[-1]['visible_count'])
        self.assertEqual(self.log.quality(run['run_id'])['missing_samples'], 2)
        self.assertTrue(any(r['type'] == 'SAMPLE_GAP' for r in self.events(run['run_id'])))

    def test_observations_are_validated_persisted_and_never_feed_context(self):
        run = self.start()
        request = self.log.request_observer(run['run_id'], 'TEST', ['power_w', 'visible_people'])
        before = self.controller.context.observations.copy()
        for changes in ({'power_w': True}, {'power_w': float('nan')}, {'visible_people': -1},
                        {'unavailable_fields': ['power_w'], 'power_w': None}, {'region': ''}):
            with self.assertRaises(ValueError):
                self.log.resolve_observer(run['run_id'], request, dict(self.initial, **changes))
        payload = dict(self.initial, power_w=11.5, visible_people=3, notes='=2+2')
        self.log.resolve_observer(run['run_id'], request, payload)
        self.assertEqual(self.controller.context.observations, before)
        with self.assertRaises(ValueError):
            self.log.resolve_observer(run['run_id'], request, payload)
        with export_csv_zip(self.log.path, run['run_id']) as exported, zipfile.ZipFile(exported) as archive:
            power = list(csv.DictReader(io.StringIO(archive.read('power_readings.csv').decode('utf-8-sig'))))
            self.assertEqual(power[-1]['power_w'], '11.5')
            self.assertEqual(power[-1]['instrument'], 'Medidor')
            self.assertEqual(power[-1]['notes'], "'=2+2")
            self.assertEqual(power[-1]['request_id'], request)

    def test_unavailable_is_explicit_and_restart_keeps_pending_requests(self):
        run = self.start()
        request = self.log.request_observer(run['run_id'], 'TEST', ['power_w'])
        payload = dict(observed_at=utc_now(), power_w=None, unavailable_fields=['power_w'], missing_reason='No llegué a leerlo')
        self.log.resolve_observer(run['run_id'], request, payload)
        self.assertEqual(self.log.quality(run['run_id'])['unavailable_observations'], 1)
        pending = self.log.request_observer(run['run_id'], 'TEST_2', ['power_w'])
        second = ExperimentLog(self.log.path)
        self.addCleanup(second.db.close)
        self.assertEqual(second.run(run['run_id'])['status'], 'INTERRUPTED')
        self.assertIn(pending, [r['request_id'] for r in second.observer_requests(run['run_id'], True)])
        self.assertFalse(second.quality(run['run_id'])['record_complete'])

    def test_real_worker_start_failure_and_timing_are_linked_to_requests(self):
        self.controller.readiness = lambda: dict(yolo='ready', text='error', vision='error')
        self.controller.vision_agent.detector = lambda _: (_ for _ in ()).throw(RuntimeError('fallo controlado'))
        run = self.start('A')
        self.controller.tick(0, resources())
        task = self.tasks.active['vision']
        with self.assertRaises(RuntimeError):
            task.future.result(timeout=2)
        self.controller.tick(0.25, resources())
        events = self.events(run['run_id'])
        started = next(r['payload'] for r in events if r['type'] == 'TASK_STARTED')
        failed = next(r['payload'] for r in events if r['type'] == 'TASK_FAILED')
        self.assertEqual(started['command']['command_id'], failed['command']['command_id'])
        self.assertIsNotNone(failed['completed_at'])
        self.assertGreaterEqual(failed['duration_seconds'], 0)
        requests = self.log.observer_requests(run['run_id'])
        self.assertEqual([r['task_id'] for r in requests if r['reason'].startswith('VISION_TASK_')], [task.command.command_id] * 2)
        self.assertEqual(next(r['requested_at'] for r in requests if r['reason'] == 'VISION_TASK_STARTED'), started['started_at'])
        self.assertEqual(next(r['requested_at'] for r in requests if r['reason'] == 'VISION_TASK_FAILED'), failed['completed_at'])
        with self.assertRaises(ValueError):
            self.controller.set_presence(True, 0.5)

    def test_previous_readings_survive_reload_and_ignore_missing_and_other_runs(self):
        run = self.start()
        self.assertEqual(self.log.observer_previous(run['run_id']), dict(power_w=0, visible_people=0))
        request_id = self.log.request_observer(run['run_id'], 'TEST', ['power_w', 'visible_people'])
        self.log.resolve_observer(run['run_id'], request_id, dict(self.initial, power_w=12, visible_people=2))
        missing = self.log.request_observer(run['run_id'], 'TEST', ['power_w'])
        self.log.resolve_observer(run['run_id'], missing, dict(self.initial, power_w=None,
                                  unavailable_fields=['power_w'], missing_reason='No pude leer'))
        other = ExperimentLog(self.log.path)
        self.addCleanup(other.db.close)
        self.assertEqual(other.observer_previous(run['run_id']), dict(power_w=12, visible_people=2))
        self.assertEqual(other.observer_previous('other-run'), {})
        client = main.app.test_client()
        with patch.object(main, 'get_experiments', return_value=SimpleNamespace(log=other)):
            self.assertEqual(client.get(f"/api/experiments/{run['run_id']}").json['observer_previous'],
                             dict(power_w=12, visible_people=2))

    def test_event_time_is_fixed_and_repeated_readings_are_exported(self):
        run = self.start()
        event_time = '2026-10-27T12:00:00+00:00'
        request_id = self.log.request_observer(run['run_id'], 'TEST', ['power_w'], requested_at=event_time)
        record_id = self.log.resolve_observer(run['run_id'], request_id,
            dict(self.initial, power_w=0, repeated_fields=['power_w'], event_at='incorrect'))
        record = next(r for r in self.events(run['run_id']) if r.get('record_id') == record_id)
        self.assertEqual(record['payload']['event_at'], event_time)
        self.assertNotEqual(record['payload']['observed_at'], event_time)
        with export_csv_zip(self.log.path, run['run_id']) as exported, zipfile.ZipFile(exported) as archive:
            rows = list(csv.DictReader(io.StringIO(archive.read('power_readings.csv').decode('utf-8-sig'))))
            self.assertEqual(rows[-1]['event_at'], event_time)
            self.assertEqual(json.loads(rows[-1]['repeated_fields']), ['power_w'])
        for repeated in (['action'], ['power_w', 'power_w'], 'power_w', [True], ['visible_people']):
            with self.subTest(repeated=repeated), self.assertRaises(ValueError):
                validate_observation(dict(self.initial, repeated_fields=repeated), ['power_w'])

    def test_new_api_exports_live_and_resolves_after_stop(self):
        run = self.start()
        client = main.app.test_client()
        service = SimpleNamespace(log=self.log)
        with patch.object(main, 'get_experiments', return_value=service):
            with client.get(f"/api/experiments/{run['run_id']}/export?format=csv") as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'application/zip')
                with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                    self.assertEqual(json.loads(archive.read('metadata.json'))['status'], 'RUNNING')
            self.controller.stop('USER_STOP', 1)
            request = self.log.observer_requests(run['run_id'], True)[0]
            body = dict(self.initial, action='Fin anticipado')
            response = client.post(f"/api/experiments/{run['run_id']}/observer-requests/{request['request_id']}", json=body)
            self.assertEqual(response.status_code, 201)
            with client.get(f"/api/experiments/{run['run_id']}") as response:
                self.assertFalse(response.json['observer_requests'])
            power = dict(kind='EXTERNAL_POWER', payload=dict(observed_at=utc_now(), value=10, unit='W', scope='whole_run'))
            self.assertEqual(client.post(f"/api/experiments/{run['run_id']}/human-records", json=power).status_code, 201)

    def test_start_and_timestamp_validation(self):
        validate_guided_start(self.experiment)
        for updates in ({'repetition': True}, {'scenario_id': 'S4'}, {'initial_observation': None}):
            with self.assertRaises(ValueError):
                validate_guided_start(dict(self.experiment, **updates))
        with self.assertRaises(ValueError):
            validate_observation(dict(self.initial, power_observed_at='2040-01-01T00:00:00Z'), ['power_w'])

    def test_deadline_cancels_queue_before_poll_can_start_another_inference(self):
        run = self.start('D')
        gate, calls = threading.Event(), []
        self.addCleanup(gate.set)
        def command():
            return Command(identifier(), 'cycle', run['run_id'], 'InterpretationAgent', 'text', utc_now(), utc_now(), {'question_id': 'Q6'}, 'TEST')
        self.tasks.submit('gemma', command(), lambda: gate.wait(2) and None, 'first', 0, 1900)
        self.tasks.submit('gemma', command(), lambda: calls.append('should not run'), 'second', 0, 1900)
        self.controller.tick(1800, resources())
        self.assertFalse(self.controller.running)
        self.assertFalse(self.tasks.pending)
        self.assertFalse(calls)

    def test_live_zip_uses_one_snapshot_while_new_events_continue(self):
        from sense import trace
        run = self.start()
        write = trace._write_csv
        def during_export(archive, name, rows, fields):
            if name == 'samples_1s':
                self.log.event(run['run_id'], 'AFTER_EXPORT_SNAPSHOT', {})
            return write(archive, name, rows, fields)
        with patch.object(trace, '_write_csv', side_effect=during_export):
            with export_csv_zip(self.log.path, run['run_id']) as exported, zipfile.ZipFile(exported) as archive:
                self.assertNotIn('AFTER_EXPORT_SNAPSHOT', archive.read('events.csv').decode('utf-8-sig'))
        self.assertTrue(any(r['type'] == 'AFTER_EXPORT_SNAPSHOT' for r in self.events(run['run_id'])))


if __name__ == '__main__':
    unittest.main()
