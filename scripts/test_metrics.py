"""Casos límite que cambiarían las conclusiones, sin nuevas dependencias."""
import json
import tempfile
import unittest
from pathlib import Path

from common import boolean, number, timestamp, write_csv
from gemma import collect, export_corpus, REVIEW_FIELDS
from metrics import count_pairs, fault_metrics, power_analysis, question_metrics, task_metrics

BASE = timestamp("2026-11-01T00:00:00+00:00")


def at(seconds):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(BASE+seconds, timezone.utc).isoformat()


def power(seconds, value, **extra):
    return {"record_id": str(seconds), "power_observed_at": at(seconds), "power_w": str(value),
            "scope": "connected_equipment", "equipment": "pi", "instrument": "meter",
            "repeated_fields": "[]", "unavailable_fields": "[]", **extra}


def task(seconds=10):
    return {"task_id": "v", "status": "TASK_COMPLETED", "action": "vision", "simulated": "False",
            "model_executed": "", "result_json": json.dumps({"captured_at": at(seconds), "count": 2,
                                                           "region": "roi", "image_id": "image"})}


def human(seconds=11, **extra):
    return {"record_id": "h", "task_id": "v", "people_observed_at": at(seconds), "visible_people": "1",
            "region": "roi", "repeated_fields": "[]", "unavailable_fields": "[]", **extra}


class MetricsTests(unittest.TestCase):
    def test_negative_fault_latency_is_flagged_and_not_clamped(self):
        row = {"fault_id": "f", "activated_at": at(1), "detected_at": at(2),
               "restored_at": at(3), "recovered_at": at(3),
               "detection_latency_s": "1", "recovery_latency_s": "-0.00001"}
        result = fault_metrics([row], BASE, BASE+10)[0]
        self.assertTrue(result["negative_latency"])
        self.assertIsNone(result["recovery_latency_numeric_s"])
        self.assertEqual(result["recovery_latency_s"], "-0.00001")
        self.assertEqual(result["detection_latency_numeric_s"], 1)

    def test_missing_is_not_zero_or_false(self):
        self.assertIsNone(number(""))
        self.assertIsNone(number("nan"))
        self.assertIsNone(boolean(""))
        self.assertIs(boolean("False"), False)
        self.assertEqual(number("0"), 0)
        self.assertIsNone(timestamp("2026-11-01T00:00:00"))

    def test_energy_clips_without_extrapolating(self):
        summary, _, segments = power_analysis([power(0, 0), power(120, 120)], BASE+30, BASE+90, 120)
        self.assertAlmostEqual(summary["energy_estimated_wh_covered"], 1)
        self.assertEqual(segments[0]["from_w"], 30)
        self.assertEqual(segments[0]["to_w"], 90)
        self.assertEqual(summary["power_coverage_fraction"], 1)

    def test_energy_gaps_and_scope_changes(self):
        for values in ([power(0, 4), power(121, 4)],
                       [power(0, 4), power(60, 4, equipment="another")]):
            summary, _, _ = power_analysis(values, BASE, BASE+180, 120)
            self.assertIsNone(summary["energy_estimated_wh_covered"])
            self.assertEqual(summary["power_coverage_fraction"], 0)

    def test_repeated_power_is_a_new_reconfirmed_reading(self):
        summary, rows, _ = power_analysis(
            [power(0, 4), power(60, 4, repeated_fields='["power_w"]')], BASE, BASE+60, 120)
        self.assertAlmostEqual(summary["energy_estimated_wh_covered"], 4/60)
        self.assertEqual(summary["power_coverage_fraction"], 1)
        self.assertTrue(rows[1]["reconfirmed_repeated"])

    def test_duplicate_timestamp_never_doubles_energy(self):
        summary, quality, _ = power_analysis([power(0, 3), power(0, 3, record_id="copy"), power(60, 3)], BASE, BASE+60, 120)
        self.assertAlmostEqual(summary["energy_estimated_wh_covered"], .05)
        self.assertEqual(sum(r["analysis_status"] == "DUPLICATE_TIMESTAMP" for r in quality), 1)
        summary, _, _ = power_analysis([power(0, 3), power(30, 4), power(30, 8, record_id="conflict"), power(60, 3)], BASE, BASE+60, 120)
        self.assertIsNone(summary["energy_estimated_wh_covered"])

    def test_count_requires_time_region_and_independent_record(self):
        summary, pairs = count_pairs([human(), human(12, record_id="h2")], [task()], {}, BASE, BASE+60)
        self.assertEqual(summary["count_pairs_n"], 1)
        self.assertEqual(summary["count_mae"], 1)
        self.assertEqual(pairs[1]["pair_status"], "DUPLICATE_CAPTURE_REFERENCE")
        for reference, reason in ((human(14, task_id=""), "TIME_SKEW"), (human(region="other"), "REGION_MISMATCH"),
                                  (human(visible_people=""), "NO_COUNT_FIELD"),
                                  (human(people_observed_at="", observed_at=at(11)), "NO_PEOPLE_OBSERVATION_TIME")):
            summary, pairs = count_pairs([reference], [task()], {}, BASE, BASE+60)
            self.assertEqual(summary["count_pairs_n"], 0)
            self.assertIsNone(summary["count_mae"])
            self.assertEqual(pairs[0]["pair_status"], reason)

    def test_confirmed_power_correction_preserves_source_and_changes_energy(self):
        readings = [power(0, 41), power(60, 4.1)]
        correction = {"0": {"original_w": 41, "corrected_w": 4.1}}
        summary, quality, _ = power_analysis(readings, BASE, BASE+60, 120, correction)
        self.assertAlmostEqual(summary["energy_estimated_wh_covered"], 4.1/60)
        self.assertEqual(summary["power_corrections_applied"], 1)
        self.assertEqual(quality[0]["power_w"], "41")
        self.assertEqual(quality[0]["analysis_power_w"], 4.1)
        self.assertEqual(readings[0]["power_w"], "41")

    def test_incompatible_power_correction_is_rejected(self):
        for correction in ({"original_w": 4.1, "corrected_w": 4.1},
                           {"original_w": 41, "corrected_w": -1},
                           {"original_w": 41, "corrected_w": "nan"}):
            with self.subTest(correction=correction), self.assertRaises(ValueError):
                power_analysis([power(0, 41)], BASE, BASE+60, 120, {"0": correction})

    def test_task_linked_reference_accepts_typing_delay_and_reconfirmation(self):
        reference = human(25, repeated_fields='["visible_people"]', recorded_at=at(28))
        summary, pairs = count_pairs([reference], [task()], {}, BASE, BASE+60)
        self.assertEqual(summary["count_pairs_n"], 1)
        self.assertEqual(summary["count_pairs_within_time_tolerance"], 0)
        self.assertEqual(pairs[0]["delta_s"], 15)
        self.assertEqual(pairs[0]["recording_delay_s"], 18)
        self.assertTrue(pairs[0]["reconfirmed_repeated"])
        summary, _ = count_pairs([dict(reference, task_id="missing")], [task()], {}, BASE, BASE+60)
        self.assertEqual(summary["count_pairs_n"], 0)

    def test_explicit_task_link_precedes_incidental_nearest_reference(self):
        summary, pairs = count_pairs([human(10, task_id=""), human(25, record_id="linked")],
                                     [task()], {}, BASE, BASE+60)
        self.assertEqual(summary["count_pairs_task_linked"], 1)
        self.assertEqual(pairs[0]["pair_status"], "DUPLICATE_CAPTURE_REFERENCE")
        self.assertEqual(pairs[1]["pair_status"], "PAIRED")

    def test_question_gaps_are_not_resolved_time(self):
        rows = [{"question_id": "Q1", "timestamp_utc": at(t), "status": "RESOLVED", "answer": "same"} for t in (0, 1, 10)]
        result = question_metrics(rows, BASE, BASE+20, 2)
        resolved = next(r for r in result if r["question_id"] == "Q1" and r["status"] == "RESOLVED")
        self.assertEqual(resolved["seconds"], 1)
        self.assertEqual(resolved["unique_payload_states"], 1)
        self.assertEqual(resolved["run_fraction"], .05)

    def test_simulated_timeout_is_not_completed_model_work(self):
        rows = [task(), dict(task(), task_id="sim", simulated="True", model_executed="False",
                            status="TASK_FAILED", timed_out="True", duration_seconds="20")]
        summary, _, _ = task_metrics(rows, BASE, BASE+60)
        self.assertEqual(summary["vision_requested"], 2)
        self.assertEqual(summary["vision_completed_nonsimulated"], 1)
        self.assertEqual(summary["vision_model_executed_true"], 0)
        self.assertEqual(summary["vision_model_executed_unknown"], 1)

    def test_raw_extra_fields_are_retained_and_review_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identity = {"run_id": "r", "scenario": "S1", "mode": "E", "repetition": 1, "folder": "E1/E/R1"}
            sample = {"task_id": "t", "agent": "InterpretationAgent", "action": "multimodal", "question_id": "Q7",
                      "result_json": json.dumps({"raw_output": '{"inferences":["a"],"observations":["b"]}', "interpretation_id": "i"})}
            responses, fragments = collect(identity, root, [sample], {}, {}, {}, {})
            self.assertEqual({f["field"] for f in fragments}, {"inferences", "observations"})
            fragments[0].update(verdict="NO_EVALUABLE", evidence="Imagen no conservada", justification="No image", reviewer="test", reviewed_at=at(0))
            write_csv(root/"revision_ia.csv", fragments, REVIEW_FIELDS)
            before = (root/"revision_ia.csv").read_bytes()
            summary, _ = export_corpus(root/"output", root, responses, fragments)
            self.assertEqual(summary["reviewed_fragments"], 1)
            self.assertEqual((root/"revision_ia.csv").read_bytes(), before)
            assessment = {"run_id": "r", "task_id": "t", "case_id": "C001", "quality": 4., "accuracy": 5,
                          "relevance": 4, "support": 3, "critical_error": False, "task_success": True,
                          "pdf_page": 8, "justifications": {"support": "Evidencia <citada>"}, "evidence": "Registro"}
            summary, _ = export_corpus(root/"output", root, responses, fragments, [assessment])
            viewer = (root/"output/revision_ia.html").read_text(encoding="utf-8")
            self.assertIn("Rúbrica C001 · calidad 4.00/5", viewer)
            self.assertIn("Evidencia &lt;citada&gt;", viewer)
            self.assertEqual(summary["reviewed_fragments"], 1)
            self.assertEqual((root/"revision_ia.csv").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
