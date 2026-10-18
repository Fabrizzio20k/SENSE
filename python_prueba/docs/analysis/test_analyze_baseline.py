import copy
import json
import unittest
from pathlib import Path

from analyze_baseline import analyze, quantile


SOURCE = Path(__file__).resolve().parents[1] / "data/2026-10-17-baseline-recibido.txt"


class BaselineTest(unittest.TestCase):
    def test_known_trace_and_truncated_tail(self):
        raw = SOURCE.read_bytes()
        with self.assertRaises(ValueError):
            analyze(raw)
        summary, intervals, transitions, segments = analyze(raw, allow_truncated_tail=True)
        self.assertEqual(summary["source_sha256"], "2b47eda963f45490bedda4590f637f8cd6a700a47e6e0ee2f313c7eb920a3ce7")
        self.assertEqual(summary["valid_records"], 490)
        self.assertEqual(summary["rejected_lines"][0]["line"], 491)
        self.assertEqual(len(intervals), 489)
        self.assertEqual(summary["interval_s"]["median"], 2.014112)
        self.assertAlmostEqual(summary["duration_s"], 984.938503)
        self.assertEqual(len(transitions), 42)
        self.assertEqual(summary["binary_presence_changes"], 4)
        self.assertEqual([s["sample_count"] for s in segments if not s["present"]], [38, 12])
        self.assertAlmostEqual(sum(s["held_until_next_s"] for s in segments), summary["duration_s"])

    def test_quantile_definition(self):
        self.assertAlmostEqual(quantile([4, 1, 3, 2], .95), 3.85)
        self.assertEqual(quantile([2], .99), 2)

    def test_invalid_data_is_not_silently_repaired(self):
        first, second = [json.loads(line) for line in SOURCE.read_text().splitlines()[:2]]

        def encoded(a, b):
            return (json.dumps(a)+"\n"+json.dumps(b)+"\n").encode()

        for bad_value in (True, float("nan"), float("inf"), "27.8"):
            bad = copy.deepcopy(first)
            bad["environment"]["sht40"]["temperature_c"] = bad_value
            with self.subTest(value=bad_value), self.assertRaises(ValueError):
                analyze(encoded(bad, second), allow_truncated_tail=True)
        bad = copy.deepcopy(first)
        bad["timestamp"] = "2026-10-17T22:08:47"
        with self.assertRaises(ValueError):
            analyze(encoded(bad, second))
        for a, b in ((first, first), (second, first)):
            with self.assertRaises(ValueError):
                analyze(encoded(a, b))
        with self.assertRaises(ValueError):
            analyze(b"{\n"+encoded(first, second), allow_truncated_tail=True)
        duplicate = json.dumps(first).replace('"device_id":', '"device_id": "duplicate", "device_id":', 1)
        with self.assertRaises(ValueError):
            analyze((duplicate+"\n"+json.dumps(second)).encode(), allow_truncated_tail=True)


if __name__ == "__main__":
    unittest.main()
