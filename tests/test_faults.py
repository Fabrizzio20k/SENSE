import csv
import io
import json
import tempfile
import time
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from sense.agents import InterpretationAgent, VisionAgent
from sense.contracts import utc_now
from sense.orchestrator import SenseOrchestrator
from sense.runtime import TaskManager
from sense.storage import ExperimentLog
from sense.trace import export_csv_zip
from test_sense import config, resources, telemetry


class FaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = ExperimentLog(Path(self.temp.name) / 'faults.sqlite3')
        self.addCleanup(self.log.db.close)
        self.tasks = TaskManager(1)
        self.addCleanup(lambda: [e.shutdown(wait=True) for e in self.tasks.executors.values()])
        self.config = config()
        self.config['vision'].update(timeout_seconds=2, cooldown_seconds=1)
        for kind in ('textual', 'multimodal'):
            self.config['interpretation'][kind].update(timeout_seconds=2, cooldown_seconds=1)
        self.now, self.wall, self.second = time.monotonic(), time.time(), 0
        self.captures, self.completions = [], []
        def capture():
            self.captures.append(self.second)
            return b'image', self.stamp(self.second)
        def complete(*args, **kwargs):
            self.completions.append(self.second)
            return {'content': json.dumps(dict(inferences=['Descripción de prueba.'], unknowns=[], recommendations=[]))}
        self.controller = SenseOrchestrator(self.config, self.log, self.tasks, VisionAgent(capture, lambda _: 2),
            InterpretationAgent(complete, 'test'), lambda: dict(yolo='ready', text='ready', vision='ready'),
            {'model_version': {'yolo': 'test', 'gemma': 'test'}})
        self.controller.resources = resources()

    def stamp(self, second):
        return datetime.fromtimestamp(self.wall + second, timezone.utc).isoformat()

    def start(self, mode='F', guided=False, scenario='S1', repetition=1):
        experiment = dict(guided=True, scenario_id=scenario, repetition=repetition, initial_observation=dict(
            observed_at=utc_now(), region='rasp_shared_view', power_w=10, visible_people=0,
            observer='Test', instrument='V1', equipment='Pi', unavailable_fields=[])) if guided else None
        return self.controller.start(mode, self.now, 'session', scenario, experiment)

    def step(self, second):
        self.second = second
        with self.log.transaction():
            self.controller.tick(self.now + second, resources())

    def ingest(self, second, **kwargs):
        self.second = second
        self.controller.ingest(telemetry(self.stamp(second), **kwargs), self.now + second, self.wall + second)

    def fault(self, component, enabled, second):
        self.controller.set_fault(dict(action='availability', component=component, enabled=enabled), self.now + second)

    def rows(self, run_id):
        return [json.loads(line) for line in self.log.export(run_id)]

    def finish_vision(self):
        self.step(0)
        self.tasks.active['vision'].future.result(timeout=2)
        self.step(0.1)

    def test_f_reuses_e_policy_and_includes_multimodal(self):
        run = self.start()
        self.ingest(0)
        self.finish_vision()
        self.assertEqual(run['mode'], 'F')
        self.assertEqual(run['policy_mode'], 'E')
        task = self.tasks.active['gemma']
        task.future.result(timeout=2)
        self.step(0.2)
        self.assertEqual(task.command.parameters['question_id'], 'Q7')
        self.assertEqual(self.controller.answers['Q7']['status'], 'INTERPRETED')
        self.assertEqual(len(self.captures), 1)
        self.assertEqual(len(self.completions), 1)

    def test_sensor_blackout_retains_age_then_detects_and_recovers_on_new_data(self):
        self.controller.readiness = lambda: dict(yolo='error', text='error', vision='error')
        run = self.start()
        self.ingest(0)
        self.step(0)
        original = self.controller.context.observations['temperature']
        self.fault('sht40', False, 1)
        for second in range(1, 12):
            self.ingest(second, temperature=30, humidity=80)
            self.step(second)
        snapshot = self.controller.context.snapshot(self.now + 11).document()['observations']
        self.assertEqual(snapshot['temperature']['value'], original.value)
        self.assertEqual(snapshot['temperature']['observation_id'], original.observation_id)
        self.assertEqual(snapshot['temperature']['status'], 'STALE')
        self.assertEqual(snapshot['aqi']['status'], 'VALID')
        self.assertEqual(self.controller.health.components['sht40']['status'], 'STALE')
        fault = next(iter(self.controller.faults.records.values()))
        self.assertGreater(fault['detection_latency_s'], 0)
        self.assertTrue(any(r['type'] == 'FSM_TRANSITION' and r['payload']['to'] == 'DEGRADED' for r in self.rows(run['run_id'])))
        self.fault('sht40', True, 12)
        self.step(12)
        self.assertIsNone(fault['recovered_at'])
        self.ingest(13, temperature=27)
        self.step(13)
        self.assertEqual(self.controller.health.components['sht40']['status'], 'HEALTHY')
        self.assertIsNotNone(fault['recovered_at'])
        with export_csv_zip(self.log.path, run['run_id']) as exported, zipfile.ZipFile(exported) as archive:
            rows = list(csv.DictReader(io.StringIO(archive.read('faults.csv').decode('utf-8-sig'))))
            self.assertEqual(rows[0]['fault_id'], fault['fault_id'])
            self.assertEqual(rows[0]['recovery_latency_s'], '1.0')

    def test_manual_radar_does_not_hide_physical_source_loss(self):
        self.controller.readiness = lambda: dict(yolo='error', text='error', vision='error')
        self.start(guided=True)
        self.ingest(0)
        self.step(0)
        self.fault('radar', False, 1)
        self.controller.set_presence(True, self.now + 1)
        for second in range(2, 9):
            self.ingest(second, presence=0)
            self.step(second)
        presence = self.controller.context.snapshot(self.now + 8).document()['observations']['presence']
        self.assertEqual(presence['value'], 1)
        self.assertEqual(presence['status'], 'VALID')
        self.assertEqual(presence['source_agent'], 'OperatorControl')
        self.assertEqual(self.controller.health.components['radar']['status'], 'STALE')
        self.assertTrue(self.controller.faults.records)
        self.controller.set_presence(None, self.now + 9)
        self.assertEqual(self.controller.context.snapshot(self.now + 9).document()['observations']['presence']['status'], 'STALE')

    def test_manual_b_triggers_zone_changes_without_centimeters_or_fake_samples(self):
        self.start('B', guided=True)
        self.controller.set_presence(True, self.now)
        self.step(0)
        task = self.tasks.active['vision']
        self.assertEqual(task.command.reason, 'MANUAL_ZONE_ENTERED')
        manual = self.controller.context.snapshot(self.now).document()['observations']['presence']
        self.assertNotIn('trigger_distance_cm', manual['metadata'])
        self.assertEqual(self.controller.view(self.now)['reactive_trigger']['required_samples'], 1)
        task.future.result(timeout=2)
        self.step(0.1)
        self.controller.set_presence(False, self.now + 31)
        self.step(31)
        self.assertEqual(self.tasks.active['vision'].command.reason, 'MANUAL_ZONE_EXITED')
        self.tasks.active['vision'].future.result(timeout=2)
        self.step(31.1)
        self.controller.set_presence(None, self.now + 32)
        self.assertEqual(self.controller.view(self.now + 32)['reactive_trigger']['state'], 'UNKNOWN')

    def test_manual_controls_available_b_through_f_but_not_a_or_as_ground_truth(self):
        for mode in 'BCDEF':
            run = self.start(mode, guided=True)
            self.controller.set_presence(True, self.now)
            self.assertEqual(self.controller.context.observations['presence'].source_agent, 'OperatorControl')
            self.assertTrue(any(r['reason'] == 'MANUAL_PRESENCE_CHANGED' for r in self.log.observer_requests(run['run_id'])))
            self.controller.stop('USER_STOP', self.now + 0.1)
        self.start('A')
        with self.assertRaises(ValueError):
            self.controller.set_presence(True, self.now)

    def test_same_value_with_manual_origin_invalidates_prior_inference_context(self):
        from sense.policy import semantic_key
        self.start()
        self.ingest(0)
        raw = self.controller.context.snapshot(self.now).document()
        self.controller.set_presence(True, self.now)
        manual = self.controller.context.snapshot(self.now).document()
        self.assertEqual(raw['observations']['presence']['value'], manual['observations']['presence']['value'])
        self.assertNotEqual(semantic_key('Q6', raw, 'test'), semantic_key('Q6', manual, 'test'))

    def test_camera_failure_uses_common_degraded_path_and_bounded_probe(self):
        self.start()
        self.ingest(0)
        self.fault('camera', False, 0)
        self.step(0)
        self.step(0.1)
        self.assertFalse(self.captures)
        self.assertEqual(self.controller.health.components['camera']['status'], 'FAILED')
        self.assertEqual(self.controller.fsm, 'WAIT')
        self.step(0.5)
        self.assertEqual(self.tasks.counters['accepted'], 1)
        self.fault('camera', True, 0.6)
        self.step(1.2)
        self.tasks.active['vision'].future.result(timeout=2)
        self.step(1.3)
        self.assertEqual(len(self.captures), 1)
        self.assertEqual(self.controller.health.components['camera']['status'], 'HEALTHY')
        self.assertIsNotNone(next(iter(self.controller.faults.records.values()))['recovered_at'])

    def test_simulated_gemma_timeout_never_executes_model_and_allows_verified_recovery(self):
        run = self.start()
        self.ingest(0)
        self.controller.set_fault(dict(action='timeout', lane='gemma'), self.now)
        self.finish_vision()
        self.assertFalse(self.completions)
        self.assertTrue(self.tasks.active['gemma'].simulation)
        self.step(2.2)
        self.assertFalse(self.tasks.quarantined)
        self.assertFalse(self.completions)
        self.assertIsNone(self.tasks.active['gemma'])
        self.assertEqual(self.controller.health.components['gemma']['status'], 'FAILED')
        self.controller.query('Q7', self.now + 3.3)
        self.step(3.3)
        self.tasks.active['gemma'].future.result(timeout=2)
        self.step(3.4)
        self.assertEqual(len(self.completions), 1)
        self.assertEqual(self.controller.health.components['gemma']['status'], 'HEALTHY')
        fault = next(iter(self.controller.faults.records.values()))
        self.assertIsNotNone(fault['recovered_at'])
        with export_csv_zip(self.log.path, run['run_id']) as exported, zipfile.ZipFile(exported) as archive:
            tasks = list(csv.DictReader(io.StringIO(archive.read('inference_tasks.csv').decode('utf-8-sig'))))
            simulated = next(t for t in tasks if t['fault_id'])
            self.assertEqual(simulated['simulated'], 'True')
            self.assertEqual(simulated['model_executed'], 'False')
            self.assertEqual(simulated['timed_out'], 'True')

    def test_simulated_vision_timeout_and_stop_release_without_background_threads(self):
        self.start()
        self.controller.set_fault(dict(action='timeout', lane='vision'), self.now)
        self.step(0)
        self.step(2.1)
        self.assertFalse(self.captures)
        self.assertIsNone(self.tasks.active['vision'])
        self.assertEqual(self.tasks.counters['timed_out'], 1)
        self.controller.stop('USER_STOP', self.now + 2.2)
        self.start()
        self.controller.set_fault(dict(action='timeout', lane='vision'), self.now)
        self.step(0)
        self.controller.stop('USER_STOP', self.now + 0.1)
        self.step(0.2)
        self.assertFalse(self.tasks.busy)
        self.assertFalse(self.captures)

    def test_real_remote_timeout_still_quarantines_runtime_in_f(self):
        from requests.exceptions import ReadTimeout
        self.controller.interpreter.completion = lambda *args, **kwargs: (_ for _ in ()).throw(ReadTimeout('real uncertainty'))
        self.start()
        self.ingest(0)
        self.finish_vision()
        with self.assertRaises(ReadTimeout):
            self.tasks.active['gemma'].future.result(timeout=2)
        self.step(0.2)
        self.assertIn('gemma', self.tasks.quarantined)
        with self.assertRaises(ValueError):
            self.controller.set_fault(dict(action='timeout', lane='gemma'), self.now + 1)
        self.assertIn('gemma', self.tasks.quarantined)

    def test_all_scenarios_three_repetitions_and_six_modes_keep_distinct_runs(self):
        ids = set()
        for mode in 'ABCDEF':
            for scenario in ('S1', 'S2', 'S3'):
                for repetition in (1, 2, 3):
                    run = self.start(mode, True, scenario, repetition)
                    ids.add(run['run_id'])
                    self.controller.stop('USER_STOP', self.now + 0.1)
                    saved = self.log.run(run['run_id'])
                    self.assertEqual((saved['scenario_id'], saved['repetition'], saved['mode']), (scenario, repetition, mode))
        self.assertEqual(len(ids), 54)

    def test_fault_api_and_controller_reject_other_modes_and_invalid_controls(self):
        client = main.app.test_client()
        self.start('E')
        def call(action, payload):
            self.assertEqual(action, 'fault')
            self.controller.set_fault(payload, self.now)
            return {'ok': True}
        with patch.object(main, 'get_experiments', return_value=SimpleNamespace(call=call)):
            control = dict(action='availability', component='sht40', enabled=False)
            self.assertEqual(client.post('/api/experiments/faults', json=control).status_code, 409)
            self.controller.stop('USER_STOP', self.now + 0.1)
            self.start('F')
            self.assertEqual(client.post('/api/experiments/faults', json=control).status_code, 202)
            for bad in (None, [], dict(control, enabled=0), dict(control, component='cpu'), dict(action='timeout', lane='other')):
                self.assertEqual(client.post('/api/experiments/faults', json=bad).status_code, 400)
        self.controller.ingest(dict(telemetry(), timestamp=None), self.now, self.wall)
        self.assertTrue(self.controller.running)

    def test_brief_recovered_blackout_is_not_detected_retroactively(self):
        self.controller.readiness = lambda: dict(yolo='error', text='error', vision='error')
        self.start()
        self.ingest(0)
        self.step(0)
        self.fault('sht40', False, 1)
        self.fault('sht40', True, 2)
        self.ingest(3)
        self.step(3)
        fault = next(iter(self.controller.faults.records.values()))
        self.assertIsNotNone(fault['recovered_at'])
        self.assertIsNone(fault['detected_at'])
        self.step(20)
        self.assertIsNone(fault['detected_at'])

    def test_timeout_expiring_in_queue_is_reported_as_not_executed(self):
        from sense.contracts import Command, identifier
        self.start()
        gate = __import__('threading').Event()
        self.addCleanup(gate.set)
        first = Command(identifier(), 'cycle', self.controller.run['run_id'], 'InterpretationAgent', 'text', utc_now(), utc_now(), {'question_id': 'Q6'}, 'TEST')
        self.tasks.submit('gemma', first, lambda: gate.wait(2) and None, 'blocker', self.now, 100)
        self.controller.set_fault(dict(action='timeout', lane='gemma'), self.now)
        fault = self.controller.faults.task_fault('gemma')
        second = Command(identifier(), 'cycle', first.experiment_run_id, 'InterpretationAgent', 'text', utc_now(), utc_now(), {'question_id': 'Q6', 'fault_id': fault['fault_id']}, 'TEST')
        self.tasks.submit('gemma', second, None, 'simulated', self.now, 1, simulation=fault)
        self.controller.faults.accepted(fault, second, self.now)
        self.step(2)
        self.assertFalse(self.controller.faults.timeouts)
        self.assertEqual(fault['not_executed_reason'], 'QUEUE_DEADLINE')
        self.assertIsNone(fault['detected_at'])

    def test_preexisting_failure_does_not_claim_a_detection_latency(self):
        self.controller.readiness = lambda: dict(yolo='error', text='error', vision='error')
        self.start()
        self.step(12)
        self.fault('sht40', False, 13)
        self.step(13)
        fault = next(iter(self.controller.faults.records.values()))
        self.assertTrue(fault['preexisting_failure'])
        self.assertIsNone(fault['detection_latency_s'])

    def test_f_collects_1800_samples_and_stops_with_faults_without_browser(self):
        self.controller.readiness = lambda: dict(yolo='error', text='error', vision='error')
        run = self.start(guided=True, scenario='S3', repetition=3)
        for component in ('sht40', 'ens160', 'radar'):
            self.fault(component, False, 0)
        for second in range(1801):
            self.step(second)
        self.assertFalse(self.controller.running)
        self.assertEqual(self.log.quality(run['run_id'])['samples'], 1800)
        self.assertEqual(self.log.quality(run['run_id'])['missing_samples'], 0)
        self.assertEqual(self.log.run(run['run_id'])['mode'], 'F')
        self.assertFalse(self.controller.faults.disabled)
        self.assertFalse(self.captures)

    def test_control_storage_failure_stops_collection_instead_of_running_unlogged(self):
        from sense.service import ExperimentService
        from test_sense import ROOT
        with tempfile.TemporaryDirectory() as directory, patch('sense.service.ResourceMonitor') as monitor:
            monitor.return_value.sample.return_value = resources()
            service = ExperimentService(ROOT, Path(directory), ROOT / 'sense' / 'pilot.yaml', None, None, None,
                                        'test', lambda: dict(yolo='error', text='error', vision='error'))
            try:
                service.reserve()
                service.call('start', {'mode': 'F'})
                event = service.log.event
                def failing_event(run_id, kind, payload):
                    if kind == 'FAULT_INJECTED':
                        raise OSError('No se pudo guardar la intervención')
                    return event(run_id, kind, payload)
                with patch.object(service.log, 'event', side_effect=failing_event):
                    with self.assertRaises(OSError):
                        service.call('fault', dict(action='availability', component='sht40', enabled=False))
                    service.call('stop')
                self.assertFalse(service.controller.running)
                self.assertEqual(service.controller.run['status'], 'FAILED')
                self.assertFalse(service.controller.faults.disabled)
            finally:
                service.close()

    def test_explicit_manual_actions_do_not_depend_on_sensor_timestamp_ordering(self):
        self.start('B')
        with patch('sense.orchestrator.utc_now', return_value='2026-01-02T00:00:00Z'):
            self.controller.set_presence(True, self.now)
        with patch('sense.orchestrator.utc_now', return_value='2026-01-01T00:00:00Z'):
            self.controller.set_presence(False, self.now + 1)
        self.assertEqual(self.controller.policy.reactive_pending['event_type'], 'MANUAL_ZONE_EXITED')


if __name__ == '__main__':
    unittest.main()
