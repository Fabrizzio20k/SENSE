"""Corpus de IA con evidencia; la codificación semántica es una entrada explícita."""
import hashlib
import html
import json
import os
from collections import Counter
from pathlib import Path

from common import boolean, decode, number, read_csv, safe_image, timestamp, write_csv, write_json, write_text

VERDICTS = ("SUSTENTADA", "PARCIAL", "CONTRADICHA", "SIN_SUSTENTO", "NO_EVALUABLE")
REVIEW_FIELDS = ("fragment_id", "run_id", "task_id", "field", "text", "verdict",
                 "evidence", "justification", "reviewer", "reviewed_at")


def collect(identity, folder, tasks, observations, inputs, snapshots, publications):
    responses, fragments = [], []
    for task in tasks:
        if task.get("agent") != "InterpretationAgent":
            continue
        result = decode(task.get("result_json"), {})
        raw = result.get("raw_output")
        if raw is None:
            continue
        source_input = inputs.get(task["task_id"])
        snapshot_id = result.get("snapshot_id") or task.get("snapshot_id")
        image_id = result.get("image_id") or task.get("image_id")
        image = safe_image(folder, image_id)
        referenced = result.get("evidence_references", [])
        evidence = [observations[key] for key in referenced if key in observations]
        missing = [key for key in referenced if key not in observations and key != image_id]
        try:
            parsed_raw = json.loads(raw)
        except (ValueError, TypeError):
            parsed_raw = None
        interpretation = result.get("interpretation_id") or task.get("interpretation_id")
        linked = publications.get(interpretation, {"count": 0, "unique": []})
        input_time = timestamp(task.get("requested_at"))
        image_time = next((timestamp(o.get("captured_at")) for o in evidence
                           if o.get("key") == "count" and decode(o.get("metadata"), {}).get("image_id") == image_id), None)
        response = {**identity, "task_id": task["task_id"], "question_id": task.get("question_id"),
                    "action": task.get("action"), "status": task.get("status"),
                    "simulated": boolean(task.get("simulated")),
                    "model_executed": boolean(task.get("model_executed")),
                    "interpretation_id": interpretation, "snapshot_id": snapshot_id,
                    "image_id": image_id, "image_available": bool(image and image.is_file()),
                    "image_path": str(image) if image and image.is_file() else None,
                    "image_age_at_request_wall_s": input_time-image_time if input_time is not None and image_time is not None else None,
                    "raw_output": raw, "raw_output_parsed": parsed_raw, "result": result,
                    "input": source_input, "snapshot": snapshots.get(snapshot_id),
                    "evidence": evidence, "missing_evidence_ids": missing,
                    "publication_count": linked["count"], "published_variants": linked["unique"],
                    "semantic_status": "PENDING_REVIEW"}
        responses.append(response)
        if isinstance(parsed_raw, dict):
            pieces = [(key, index, text) for key, values in parsed_raw.items()
                      for index, text in enumerate(values if isinstance(values, list) else [values])]
        else:
            pieces = [("raw_output", 0, raw)]
        for field, index, text in pieces:
            if not isinstance(text, str) or not text.strip():
                continue
            stable = "\0".join((identity["run_id"], task["task_id"], field, str(index), text))
            fragment_id = hashlib.sha256(stable.encode()).hexdigest()[:24]
            fragments.append({"fragment_id": fragment_id, "run_id": identity["run_id"],
                              "task_id": task["task_id"], "field": field, "text": text,
                              "verdict": "", "evidence": "", "justification": "",
                              "reviewer": "", "reviewed_at": ""})
    return responses, fragments


def export_corpus(output, scripts, responses, fragments, assessments=()):
    write_csv(output / "fragmentos_ia.csv", fragments, REVIEW_FIELDS)
    template = scripts / "revision_ia.csv"
    if not template.exists():
        write_csv(template, fragments, REVIEW_FIELDS)
    annotated = read_csv(template)
    known = {f["fragment_id"]: f for f in fragments}
    seen, reviewed, issues = set(), [], []
    for row in annotated:
        key = row.get("fragment_id")
        if key in seen:
            raise ValueError(f"fragment_id duplicado en revision_ia.csv: {key}")
        seen.add(key)
        if not row.get("verdict"):
            continue
        if key not in known:
            issues.append({"severity": "WARNING", "issue": "REVIEW_NOT_IN_CURRENT_CORPUS", "detail": key})
            continue
        if any(row.get(k) != known[key].get(k) for k in ("run_id", "task_id", "field", "text")):
            raise ValueError(f"La revisión no corresponde al fragmento actual: {key}")
        if (row["verdict"] not in VERDICTS or timestamp(row.get("reviewed_at")) is None
                or not all(row.get(k, "").strip() for k in ("evidence", "justification", "reviewer"))):
            raise ValueError(f"Revisión incompleta o categoría inválida: {key}")
        reviewed.append(row)
    write_csv(output / "revision_ia_validada.csv", reviewed, REVIEW_FIELDS)
    counts = Counter(row["verdict"] for row in reviewed)
    response_index = {(r["run_id"], r["task_id"]): r for r in responses}
    for response in responses:
        total = sum(f["run_id"] == response["run_id"] and f["task_id"] == response["task_id"] for f in fragments)
        done = sum(f["run_id"] == response["run_id"] and f["task_id"] == response["task_id"] for f in reviewed)
        response["semantic_status"] = "REVIEWED" if done and done == total else "PARTIALLY_REVIEWED" if done else "PENDING_REVIEW"
    write_json(output / "respuestas_ia.json", responses)
    reviewed_groups = Counter((r["run_id"], r["task_id"], r["field"], r["verdict"]) for r in reviewed)
    grouped_rows = []
    for (run_id, task_id, field, verdict), n in reviewed_groups.items():
        source = response_index[run_id, task_id]
        grouped_rows.append({"run_id": run_id, "task_id": task_id, "question_id": source["question_id"],
                             "scenario": source["scenario"], "mode": source["mode"], "repetition": source["repetition"],
                             "field": field, "verdict": verdict, "fragments": n})
    write_csv(output / "revision_ia_resumen.csv", grouped_rows)
    summary = {"responses": len(responses), "fragments": len(fragments), "reviewed_fragments": len(reviewed),
               "pending_fragments": len(fragments)-len(reviewed), "verdicts": dict(counts), "groups": grouped_rows,
               "review_rows_missing_from_template": len(set(known)-seen),
               "note": "Categorías por fragmento y tarea, exploratorias posteriores a campaña; no son exactitud física global."}
    write_json(output / "estado_revision_ia.json", summary)
    write_csv(output / "respuestas_ia_resumen.csv", [{
        **{key: r.get(key) for key in ("run_id", "scenario", "mode", "repetition", "task_id", "question_id", "interpretation_id", "snapshot_id", "image_id", "image_available", "publication_count", "semantic_status")},
        "input_available": bool(r["input"]), "snapshot_available": bool(r["snapshot"]),
        "missing_evidence_n": len(r["missing_evidence_ids"]), "raw_characters": len(r["raw_output"]),
        "validation_status": r["result"].get("validation_status"),
        "prompt_tokens": r["result"].get("tokens", {}).get("prompt_tokens"),
        "completion_tokens": r["result"].get("tokens", {}).get("completion_tokens")
    } for r in responses])
    e = html.escape
    rubric_by_task = {(r["run_id"], r["task_id"]): r for r in assessments}
    blocks = []
    for response in responses:
        file = output / "evidencia_ia" / f"{response['run_id']}_{response['task_id']}.json"
        write_json(file, response)
        image = response["image_path"]
        picture = (f'<img loading="lazy" src="{e(os.path.relpath(image, output).replace(os.sep, "/"), quote=True)}" alt="Captura vinculada a la tarea">'
                   if image else "<p>Imagen no disponible o tarea textual.</p>")
        assessment = rubric_by_task.get((response["run_id"], response["task_id"]))
        score = ""
        if assessment:
            score = f'''<h3>Rúbrica {e(assessment['case_id'])} · calidad {assessment['quality']:.2f}/5</h3>
<p>Exactitud: {assessment['accuracy']} · Pertinencia: {assessment['relevance']} · Sustento: {assessment['support']} · Error crítico: {'Sí' if assessment['critical_error'] else 'No'} · Cumple tarea: {'Sí' if assessment['task_success'] else 'No'}</p>
<p>Evaluación posterior asistida consignada en el informe. <a href="../../SENSE_evaluacion_Gemma.pdf#page={int(assessment['pdf_page'])}">Ficha original, página {int(assessment['pdf_page'])}</a></p>
<details><summary>Justificaciones de la rúbrica</summary><pre>{e(json.dumps(assessment['justifications'], ensure_ascii=False, indent=2))}</pre><p>{e(assessment['evidence'])}</p></details>'''
        blocks.append(f'''<article id="{e(response['task_id'])}">
<h2>{e(response['scenario'])} · {e(response['mode'])} · R{response['repetition']} · {e(response['question_id'] or '')}</h2>
<p>Tarea: <code>{e(response['task_id'])}</code> · Publicaciones: {response['publication_count']} · Codificación por fragmentos: revision_ia.csv.</p>
<h3>Salida original de Gemma</h3><pre>{e(response['raw_output'])}</pre>{picture}
{score}
<details><summary>Entrada registrada y evidencia</summary><pre>{e(json.dumps({'input': response['input'], 'evidence': response['evidence'], 'published_variants': response['published_variants']}, ensure_ascii=False, indent=2))}</pre></details>
<p><a href="evidencia_ia/{e(file.name)}">Registro completo con snapshot y vínculos</a></p></article>''')
    write_text(output / "revision_ia.html", '''<!doctype html><html lang="es"><meta charset="utf-8">
<title>SENSE · Corpus de respuestas</title><style>body{font:16px/1.5 system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#172b3a;background:#f5f7fa}article{background:white;padding:1.4rem;margin:1.5rem 0;border:1px solid #cbd5df;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.5 monospace;background:#edf1f5;padding:1rem}img{max-width:100%;max-height:580px}h2{font-size:1.2rem}</style>
<h1>Corpus de respuestas de SENSE</h1><p>Informe local: no publica ni envía imágenes. VALIDATED es una validación formal. Las observaciones del sistema no son referencia física independiente. La rúbrica evalúa respuestas completas; revision_ia.csv conserva una codificación por fragmentos separada y main.py nunca sobrescribe ese archivo existente.</p>
''' + "\n".join(blocks) + "</html>")
    return summary, issues
