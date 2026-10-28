import unittest
from datetime import datetime

from sense.acquisition import PresenceAgent
from sense.config import validate_config
from sense.context import ContextStore
from sense.policy import PolicyEngine
from test_sense import config, ingest_packet, put_count, stamp, telemetry


class ReactiveDistanceTests(unittest.TestCase):
    def setUp(self):
        self.config = config()
        self.policy = PolicyEngine(self.config, "B", 0)
        self.store = ContextStore(self.config)
        self.events = []

    def sample(self, second, distance, code=2, **fields):
        packet = telemetry(stamp(second), presence=code)
        packet["presence"].update(motion_distance_cm=distance, static_distance_cm=distance, **fields)
        wall = datetime.fromisoformat(packet["timestamp"]).timestamp()
        ingest_packet(self.store, packet, second, wall)
        self.events += self.policy.observe_presence(self.store.observations["presence"], wall)

    def decide(self, second, busy=False):
        decision = self.policy.vision(self.store.snapshot(second).document(), second, self.events, True, busy, None)
        self.events.clear()
        return decision

    def test_near_at_start_triggers_after_three_fresh_samples(self):
        self.sample(0, 20)
        self.assertIsNone(self.decide(0).action)
        self.sample(1, 20)
        self.assertIsNone(self.decide(1).action)
        self.sample(2, 20)
        self.assertEqual(len(self.events[-1]["evidence_ids"]), 3)
        self.assertEqual(self.decide(2).reason, "RADAR_NEAR_CONFIRMED")

    def test_threshold_is_strict_and_invalid_rearm_blocks_start(self):
        for second in range(3):
            self.sample(second, 30)
        self.assertIsNone(self.decide(2).action)
        self.config["modes"]["reactive_exit_at_or_above_cm"] = 30
        with self.assertRaises(ValueError):
            validate_config(self.config)

    def test_persistent_far_presence_never_triggers_even_if_count_stale(self):
        put_count(self.store, 0)
        for second in range(70):
            self.sample(second, 300)
            self.assertIsNone(self.decide(second).action)
        self.assertEqual(self.store.snapshot(69).document()["observations"]["count"]["status"], "STALE")
        self.assertEqual(self.store.observations["presence"].value, 1)

    def test_hysteresis_exit_cooldown_and_no_periodic_refresh(self):
        for second in range(3):
            self.sample(second, 20)
        self.assertEqual(self.decide(2).action, "vision")
        self.policy.accepted_vision(2)
        for second in range(3, 36):
            self.sample(second, 35)
            self.assertIsNone(self.decide(second).action)
        for second in range(36, 39):
            self.sample(second, 50)
        self.assertEqual(self.decide(38).reason, "RADAR_ZONE_EXITED")
        self.policy.accepted_vision(38)
        for second in range(39, 42):
            self.sample(second, 29)
        self.assertEqual(self.decide(41).reason, "COOLDOWN_ACTIVE")
        for second in range(42, 69):
            self.sample(second, 29)
        self.assertEqual(self.decide(68).reason, "RADAR_ZONE_ENTERED")

    def test_invalid_missing_zero_or_stale_distance_never_means_near(self):
        for value in (None, 0, -1, True, "20", float("nan")):
            with self.subTest(value=value):
                self.setUp()
                for second in range(3):
                    self.sample(second, value)
                self.assertIsNone(self.decide(2).action)
        self.setUp()
        for second in range(3):
            self.sample(second, 20)
        self.assertIsNone(self.decide(20).action)

    def test_invalid_readings_and_gaps_break_confirmation(self):
        for second, distance in ((0, 20), (1, 20), (2, None), (3, 20), (4, 20), (20, 20)):
            self.sample(second, distance)
            self.assertIsNone(self.decide(second).action)

    def test_repeated_evaluation_does_not_count_as_new_sensor_samples(self):
        self.sample(0, 20)
        for _ in range(10):
            self.assertIsNone(self.decide(0).action)

    def test_uses_active_target_distance_and_preserves_raw_measurements(self):
        packet = telemetry(stamp(0), presence=2)
        packet["presence"].update(motion_distance_cm=10, static_distance_cm=309, total_distance_cm=8)
        observation = PresenceAgent.observe(packet, stamp(0), "radar")
        metadata = dict(observation.metadata)
        self.assertEqual(metadata["trigger_distance_cm"], 309)
        self.assertEqual(metadata["trigger_distance_source"], "static_distance_cm")
        self.assertEqual(metadata["total_distance_cm"], 8)
        self.assertEqual(observation.value, 1)

    def test_raw_presence_events_do_not_bypass_distance_rule(self):
        for second in range(3):
            self.sample(second, 300)
        self.events.append({"event_type": "PRESENCE_CHANGED"})
        self.assertIsNone(self.decide(2).action)

    def test_motion_and_both_targets_choose_only_relevant_valid_distances(self):
        for code, motion, stationary, expected in ((1, 250, 10, 250), (2, 10, 250, 250),
                                                   (3, 250, 20, 20), (3, 20, None, None)):
            packet = telemetry(stamp(0), presence=code)
            packet["presence"].update(motion_distance_cm=motion, static_distance_cm=stationary, total_distance_cm=1)
            observation = PresenceAgent.observe(packet, stamp(0), "radar")
            self.assertEqual(dict(observation.metadata)["trigger_distance_cm"], expected)

    def test_absence_confirms_exit_without_treating_missing_distance_as_zero(self):
        for second in range(3):
            self.sample(second, 20)
        self.decide(2)
        self.policy.accepted_vision(2)
        for second in range(3, 6):
            self.sample(second, None, code=0)
        self.assertEqual(self.events[-1]["event_type"], "RADAR_ZONE_EXITED")
        self.assertIsNone(self.events[-1]["distance_cm"])

    def test_zero_total_distance_does_not_turn_absence_into_presence(self):
        packet = telemetry(stamp(0), presence=0)
        packet['presence']['total_distance_cm'] = 0
        observation = PresenceAgent.observe(packet, stamp(0), 'radar')
        self.assertEqual(observation.value, 0)
        self.assertIsNone(dict(observation.metadata)['trigger_distance_cm'])


if __name__ == "__main__":
    unittest.main()
