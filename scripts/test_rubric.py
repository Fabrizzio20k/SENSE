import copy
import hashlib
import unittest

from rubric import validate_records, summarize


class RubricTests(unittest.TestCase):
    def setUp(self):
        self.response = {"run_id": "run", "task_id": "task", "scenario": "S1", "mode": "D",
                         "repetition": 1, "question_id": "Q6", "raw_output": "Evidencia"}
        self.record = {**{k: v for k, v in self.response.items() if k != "raw_output"},
                       "case_id": "C001", "response_sha256": hashlib.sha256(b"Evidencia").hexdigest(),
                       "scores": {"accuracy": 5, "relevance": 4, "support": 3}, "reported_quality": 4.,
                       "critical_error": False, "task_success": True, "evidence": "Registro de origen",
                       "justifications": {k: "Justificación" for k in ("accuracy", "relevance", "support")}}

    def validate(self, records):
        return validate_records({"records": records}, [self.response])

    def test_mean_and_denominators(self):
        summary = summarize(self.validate([self.record]))
        self.assertEqual(summary["quality"]["mean"], 4.)
        self.assertEqual(summary["task_successes"], 1)
        self.assertEqual(summary["critical_errors"], 0)
        self.assertEqual(summary["score_counts"]["support"]["3"], 1)

    def test_duplicate_and_missing_coverage_rejected(self):
        for records in ([], [self.record, self.record]):
            with self.assertRaises(ValueError):
                self.validate(records)

    def test_invalid_score_identity_content_or_mean_rejected(self):
        for field, value in (("scores", {"accuracy": True, "relevance": 4, "support": 3}),
                             ("scores", {"accuracy": 6, "relevance": 4, "support": 3}),
                             ("scenario", "S2"), ("reported_quality", 3.5),
                             ("response_sha256", "changed"), ("critical_error", "False"),
                             ("justifications", {})):
            record = copy.deepcopy(self.record)
            record[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.validate([record])


if __name__ == "__main__":
    unittest.main()
