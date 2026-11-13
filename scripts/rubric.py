"""Importa juicios documentados sin volver a evaluar ni modificar sus puntuaciones."""
from collections import defaultdict
import hashlib
import json

from common import digest, stats, write_csv, write_json

CRITERIA = ("accuracy", "relevance", "support")


def validate_records(evaluation, responses):
    corpus = {(r["run_id"], r["task_id"]): r for r in responses}
    if len(corpus) != len(responses):
        raise ValueError("Identidades duplicadas en el corpus")
    seen, cases, rows = set(), set(), []
    for record in evaluation["records"]:
        key = record["run_id"], record["task_id"]
        if key in seen or record["case_id"] in cases:
            raise ValueError("Ficha o tarea evaluada duplicada")
        response = corpus.get(key)
        if response is None or any(record[k] != response[k] for k in ("scenario", "mode", "repetition", "question_id")):
            raise ValueError(f"Identidad de ficha incompatible: {record['case_id']}")
        if hashlib.sha256(response["raw_output"].encode("utf-8")).hexdigest() != record["response_sha256"]:
            raise ValueError(f"La respuesta evaluada cambió: {record['case_id']}")
        scores = record["scores"]
        if set(scores) != set(CRITERIA) or any(type(scores[k]) is not int or not 1 <= scores[k] <= 5 for k in CRITERIA):
            raise ValueError(f"Puntuaciones fuera de la escala: {record['case_id']}")
        quality = sum(scores.values()) / len(CRITERIA)
        if abs(record["reported_quality"] - quality) > .0051:
            raise ValueError(f"Promedio incompatible: {record['case_id']}")
        if any(type(record[k]) is not bool for k in ("critical_error", "task_success")):
            raise ValueError(f"Indicadores no booleanos: {record['case_id']}")
        if not record["evidence"] or any(not record["justifications"].get(k) for k in CRITERIA):
            raise ValueError(f"Justificación incompleta: {record['case_id']}")
        seen.add(key)
        cases.add(record["case_id"])
        rows.append({**record, **scores, "quality": quality})
    if seen != set(corpus):
        raise ValueError("La evaluación no cubre exactamente el corpus")
    return rows


def summarize(rows):
    return {"n": len(rows), "critical_errors": sum(r["critical_error"] for r in rows),
            "task_successes": sum(r["task_success"] for r in rows),
            **{k: stats(r[k] for r in rows) for k in (*CRITERIA, "quality")},
            "score_counts": {k: {str(v): sum(r[k] == v for r in rows) for v in range(1, 6)} for k in CRITERIA}}


def export_evaluation(output, evaluation_path, responses):
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    source = evaluation_path.parent.parent / evaluation["source"]["path"]
    if digest(source) != evaluation["source"]["sha256"]:
        raise ValueError("El PDF fuente de la rúbrica cambió")
    rows = validate_records(evaluation, responses)
    summary = {"status": "COMPLETE", "source": evaluation["source"],
               "evaluation_sha256": digest(evaluation_path), "reference_doi": evaluation["reference_doi"],
               "adaptation": evaluation["adaptation"], "overall": summarize(rows)}
    for name, fields in (("by_question", ("question_id",)),
                         ("by_scenario_question", ("scenario", "question_id")),
                         ("by_configuration_question", ("scenario", "mode", "question_id")),
                         ("by_run", ("run_id", "scenario", "mode", "repetition", "question_id"))):
        groups = defaultdict(list)
        for row in rows:
            groups[tuple(row[k] for k in fields)].append(row)
        summary[name] = [{**dict(zip(fields, key)), **summarize(group)} for key, group in sorted(groups.items())]
    write_json(output / "evaluacion_rubrica.json", rows)
    write_csv(output / "evaluacion_rubrica.csv", rows)
    write_json(output / "evaluacion_rubrica_resumen.json", summary)
    return summary
