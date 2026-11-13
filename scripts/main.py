"""Ejecutar con `uv run main.py` desde scripts; las rutas no dependen del cwd."""
from __future__ import annotations

import csv
import json
import math
import platform
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from common import (TABLES, boolean, csv_rows, decode, digest, number, read_csv, safe_image,
                    stats, tagged, timestamp, write_csv, write_json, write_text)
from gemma import collect, export_corpus
from rubric import export_evaluation
from metrics import (count_pairs, fault_metrics, power_analysis, question_metrics,
                     resource_metrics, task_metrics)
import plots

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent


def table(path, identity, schema, sources):
    rows = read_csv(path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        fields = next(csv.reader(stream))
    if any(row.get("run_id") != identity["run_id"] for row in rows):
        raise ValueError(f"run_id inconsistente: {path}")
    key = {"inference_tasks": "task_id", "observations": "observation_id", "faults": "fault_id",
           "observer_requests": "request_id", "samples_1s": "second", "ground_truth": "record_id",
           "power_readings": "record_id", "images": "image_id"}.get(path.stem)
    if key:
        ids = [r[key] for r in rows]
        if any(not key_id for key_id in ids) or len(ids) != len(set(ids)):
            raise ValueError(f"Identificador vacío o duplicado ({key}): {path}")
    for field in fields:
        schema.append(tagged(identity, {"table": path.stem, "column": field, "rows": len(rows),
                                        "empty_cells": sum(not r[field] for r in rows)}))
    sources.append({"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
                    "sha256": digest(path), "rows": len(rows)})
    return rows


def events(path, identity, tasks, metadata, sources):
    counts, decisions = Counter(), Counter()
    inputs, snapshots, vision, lifecycle, gaps, periods = {}, {}, {}, [], [], []
    ids = {task.get("snapshot_id") for task in tasks}
    for task in tasks:
        result = decode(task.get("result_json"), {})
        ids.add(result.get("snapshot_id"))
    last_sequence, total = -1, 0
    selected = {"POLICY_EVALUATED", "VISION_SKIPPED", "TEXT_SLM_SKIPPED", "MULTIMODAL_SKIPPED",
                "SLM_INPUT", "CONTEXT_UPDATED", "VISION_OBSERVATION", "PERIOD_SCHEDULE", "SAMPLE_GAP"}
    for row in csv_rows(path):
        if row["run_id"] != identity["run_id"]:
            raise ValueError(f"run_id inconsistente en {path}")
        sequence = int(row["sequence"])
        if sequence <= last_sequence:
            raise ValueError(f"Secuencia duplicada o desordenada: {path}:{sequence}")
        last_sequence = sequence
        total += 1
        kind = row["type"]
        counts[kind] += 1
        if kind not in selected and not kind.startswith("TASK_"):
            continue
        p = decode(row["payload_json"], {})
        if kind == "SLM_INPUT":
            inputs[p["request_id"]] = p
        elif kind == "CONTEXT_UPDATED" and p.get("snapshot_id") in ids:
            snapshots[p["snapshot_id"]] = p
        elif kind == "VISION_OBSERVATION":
            vision[p["task_id"]] = p["observation"]
        elif kind == "SAMPLE_GAP":
            gaps.append(tagged(identity, {"sequence": sequence, **p}))
        elif kind == "PERIOD_SCHEDULE":
            periods.append(tagged(identity, {"sequence": sequence, **p}))
        elif kind.startswith("TASK_"):
            command = p.get("command", {})
            lifecycle.append(tagged(identity, {"sequence": sequence, "type": kind,
                              "timestamp_utc": row["timestamp_utc"], "recorded_at": row["recorded_at"],
                              "task_id": row.get("task_id") or command.get("command_id"), "payload": p}))
        else:
            decisions[(kind, p.get("action"), p.get("reason"))] += 1
    cut = number(metadata.get("export_event_sequence"))
    if cut is not None and last_sequence > cut:
        raise ValueError(f"Eventos posteriores al corte declarado: {path}")
    sources.append({"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
                    "sha256": digest(path), "rows": total})
    return {"counts": counts, "decisions": decisions, "inputs": inputs, "snapshots": snapshots,
            "vision": vision, "lifecycle": lifecycle, "gaps": gaps, "periods": periods}


def methods():
    return {
        "analysis_type": "Descriptivo y exploratorio, criterios definidos después de la campaña.",
        "unit": "Ejecución completa. Las muestras, tareas y anotaciones no añaden réplicas independientes.",
        "window": "[start_time, start_time + min(elapsed_s, duration_seconds)]; límites derivados de metadatos. No se supone sincronización del productor externo.",
        "presence": "Representación uniforme de la señal de presencia: 1 = presente, 0 = ausente. Se utiliza presence con su estado y antigüedad, sin segmentar por etiquetas de origen. Un dato vacío o no vigente no se convierte en ausencia.",
        "power": "Trapecios entre lecturas con power_observed_at explícito y frontera eléctrica coincidente. Incluye valores repetidos reconfirmados mediante nueva observación, según aclaración de los observadores del 12-11-2026. Excluye no disponibles, valores no finitos/negativos y timestamps contradictorios. No extrapola extremos ni huecos largos; recorta por interpolación entre extremos válidos. No usa EXTERNAL_ENERGY como W.",
        "power_corrections": "Correcciones individuales de transcripción confirmadas por el estudiante en correcciones_potencia.json. Identidad, valor original y carpeta deben coincidir; conserva power_w original y analysis_power_w usado. No modifica data/ ni aplica un umbral automático de exclusión de valores altos.",
        "power_gap": "Máximo 2 × power_interval_seconds entre lecturas válidas (120 s si intervalo=60). Criterio exploratorio conservado en cada ejecución, no requisito previo ni exactitud del instrumento. No se rellenan datos; intervalos más largos quedan sin integrar.",
        "power_comparison": "Wh corresponde solo al tiempo cubierto. Acompañar por cobertura y potencia media ponderada; no extrapolar a 30 minutos ni desagregar por modelo.",
        "count": "Conteo entero no negativo, disponible, hora de personas y región coincidente. Incluye valores repetidos reconfirmados. El task_id vincula la referencia a la escena capturada aunque el registro sea posterior, según el procedimiento confirmado el 12-11-2026. Solo sin vínculo explícito busca la captura más cercana con desfase <= comparison_max_skew_seconds (3 s si falta). Una referencia por captura: prioriza vínculo explícito y luego menor desfase. Conserva desfase y demora; cuenta por separado los pares dentro de tolerancia. Una fila sin conteo no constituye error humano.",
        "observers": "Dos observadores: uno registraba y el otro comprobaba la anotación; conteo directo del encuadre antes de consultar YOLO y vigilancia continua. Revisión conjunta de las interpretaciones mostradas tras cada ejecución, según preguntas_aclaracion_campana_SENSE.txt. La codificación por fragmentos se distingue de esa revisión de campaña.",
        "tasks": "Cuenta solicitudes de inference_tasks y conserva lifecycle de events; no usa cantidad de publicaciones como llamadas. Completadas no simuladas requiere simulated=False, estado TASK_COMPLETED y ausencia de model_executed=False. model_executed vacío sigue desconocido; no se etiqueta como True.",
        "latency": "Distribuciones de campos exportados no negativos en tareas completadas no simuladas. No incluye fallidas como duración cero ni llama latencia física a requested/completed. Cola y duración provienen del exportador; su equivalencia entre versiones sigue pendiente de confirmar. p95 lineal de pandas con n explícito.",
        "resources": "Deduplica resource_timestamp_utc y admite edad <= 2 × resource_interval_seconds (1 s por defecto). Resúmenes sobre muestras únicas, sin imputación ni prueba de Wh. MB exportados corresponden a MiB según informe de app. Pico VmHWM puede pertenecer al proceso entero; cpu_percent y process_cpu_percent mantienen su escala reportada, no se normalizan entre sí.",
        "questions": "Fracciones temporales del estado publicado entre publicaciones consecutivas separadas <= 2 × evaluation_interval_seconds (1 s por defecto). Sin extensión después de la última publicación; resto UNOBSERVED. RESOLVED describe cobertura operativa, no corrección. Promedio entre ejecuciones con igual peso.",
        "faults": "Conserva marcas por etapa, preexistencia y solapamientos. Latencias numéricas solo no negativas con extremos observados; los negativos se conservan en su campo original y se señalan en auditoria.csv. No mezcla DATA_LOSS y timeout como mismo origen. Recuperación ausente no es cero. applied_at ausente en DATA_LOSS no demuestra que no se filtraran datos.",
        "gemma": "Extrae raw_output, todos sus campos textuales, publicaciones, SLM_INPUT, snapshot e IDs de evidencia. observed_facts y evidence_references son construidos por el sistema y no prueba de grounding semántico. VALIDATED es formal. Codificación posterior explícita en revision_ia.csv; sin evaluaciones automáticas inventadas ni servicios externos.",
        "qualitative_cases": "casos_ia.json conserva ocho antecedentes documentales preliminares, separados de la rúbrica completa. La revisión conjunta de las salidas mostradas durante la campaña está confirmada; las notas posteriores del PDF aportado tienen la procedencia asistida que declara ese informe.",
        "rubric": "evaluacion_gemma.json transcribe las 149 fichas del PDF aportado. Adaptación de Rico y Larson (2026), DOI10.3390/aisens2020007: tres criterios ordinales 1–5 frente a cinco en el artículo. Calidad: promedio simple por respuesta; errores críticos y cumplimiento se conservan como juicios binarios. Verifica hashes, cobertura, identidades, notas y promedios; no emite nuevos juicios. Resúmenes por respuesta y ejecución; sin salida no recibe cero. No confundir medias con exactitud física ni terminación con cumplimiento semántico.",
        "comparisons": "A/B/C dentro de escenario; C/D y D/E se describen como configuraciones completas. La rúbrica caracteriza las 149 salidas conservadas, separando preguntas y escenarios. Compartir esquema de entrada no basta para emparejar dos tareas con diferente snapshot o pregunta. Las diferencias de medianas de ejecuciones permanecen descriptivas y no emparejadas.",
    }


def aggregate(rows):
    summaries, contrasts = [], []
    metrics = [key for key in rows[0] if key not in ("repetition",) and any(number(row.get(key)) is not None for row in rows)
               and key not in ("run_id", "scenario", "mode", "folder")]
    for scenario in ("S1", "S2", "S3"):
        for mode in "ABCDEF":
            selected = [row for row in rows if row["scenario"] == scenario and row["mode"] == mode]
            for metric in metrics:
                result = stats(row.get(metric) for row in selected)
                summaries.append({"scenario": scenario, "mode": mode, "metric": metric,
                                  "n_runs": result["n"], "median": result["median"],
                                  "min": result["min"], "max": result["max"], "mean": result["mean"]})
        for left, right in (("A", "B"), ("A", "C"), ("B", "C"), ("C", "D"), ("D", "E")):
            for metric in metrics:
                a = stats(row.get(metric) for row in rows if row["scenario"] == scenario and row["mode"] == left)
                b = stats(row.get(metric) for row in rows if row["scenario"] == scenario and row["mode"] == right)
                contrasts.append({"scenario": scenario, "left": left, "right": right, "metric": metric,
                                  "left_n": a["n"], "right_n": b["n"], "left_median": a["median"],
                                  "right_median": b["median"], "right_minus_left": b["median"]-a["median"]
                                  if a["median"] is not None and b["median"] is not None else None})
    return summaries, contrasts


def run():
    output, figures, data = SCRIPTS / "resultados", ROOT / "images" / "resultados", ROOT / "data"
    output.mkdir(parents=True, exist_ok=True)
    import pandas, matplotlib, PIL
    manifest = {"status": "RUNNING", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version(), "packages": {"pandas": pandas.__version__, "matplotlib": matplotlib.__version__, "pillow": PIL.__version__},
                "code": {p.name: digest(p) for p in sorted(SCRIPTS.glob("*.py"))},
                "lock_sha256": digest(SCRIPTS / "uv.lock") if (SCRIPTS / "uv.lock").exists() else None}
    manifest["qualitative_cases_sha256"] = digest(SCRIPTS / "casos_ia.json")
    manifest["campaign_clarifications_sha256"] = digest(ROOT / "preguntas_aclaracion_campana_SENSE.txt")
    manifest["additional_clarifications_sha256"] = digest(ROOT / "preguntas_complementarias_SENSE.txt")
    correction_file = SCRIPTS / "correcciones_potencia.json"
    correction_records = json.loads(correction_file.read_text(encoding="utf-8"))["records"]
    power_corrections = {r["record_id"]: r for r in correction_records}
    if len(power_corrections) != len(correction_records):
        raise ValueError("Identificadores duplicados en correcciones de potencia")
    manifest["power_corrections_sha256"] = digest(correction_file)
    write_json(output / "manifest.json", manifest)
    try:
        paths = sorted(data.glob("E[123]/[ABCDEF]/R[123]/metadata.json"))
        if not paths:
            raise ValueError(f"No hay exportaciones en {data}")
        issues, sources, schema, run_rows, metadata_rows, figures_index = [], [], [], [], [], []
        all_tables = defaultdict(list)
        all_responses, all_fragments = [], []
        run_ids, identities = set(), set()
        for index, path in enumerate(paths, 1):
            folder = path.parent
            meta = json.loads(path.read_text(encoding="utf-8-sig"))
            identity = {"run_id": meta["run_id"], "scenario": meta["scenario_id"], "mode": meta["mode"],
                        "repetition": meta["repetition"], "folder": folder.relative_to(data).as_posix()}
            cell = (identity["scenario"], identity["mode"], identity["repetition"])
            if identity["run_id"] in run_ids or cell in identities:
                raise ValueError(f"run_id o identidad de metadatos duplicados: {folder}")
            run_ids.add(identity["run_id"])
            identities.add(cell)
            print(f"[{index:02}/{len(paths)}] {identity['folder']} -> {cell}", flush=True)
            expected_cell = ("S"+folder.parts[-3][1:], folder.parts[-2], int(folder.name[1:]))
            if cell != expected_cell:
                issues.append(tagged(identity, {"severity": "WARNING", "issue": "FOLDER_METADATA_MISMATCH",
                                               "detail": {"folder_identity": expected_cell, "metadata_identity": cell}}))
            start = timestamp(meta.get("start_time"))
            duration, elapsed = number(meta.get("duration_seconds")), number(meta.get("elapsed_s"))
            if start is None or duration is None or duration <= 0 or elapsed is None or elapsed <= 0:
                raise ValueError(f"Ventana temporal no evaluable: {folder}")
            window = min(duration, elapsed)
            end, expected_samples = start+window, math.ceil(window)
            tables = {}
            for name in TABLES:
                if name != "events":
                    tables[name] = table(folder / f"{name}.csv", identity, schema, sources)
            for auxiliary in (path, folder / "LEEME.txt", folder / "replay-manifest.json"):
                sources.append({"path": auxiliary.relative_to(ROOT).as_posix(), "bytes": auxiliary.stat().st_size, "sha256": digest(auxiliary)})
            replay = json.loads((folder / "replay-manifest.json").read_text(encoding="utf-8-sig"))
            if replay.get("run_id") != identity["run_id"]:
                raise ValueError(f"Manifiesto de otra ejecución: {folder}")
            for source in replay.get("files", []):
                referenced = (folder / source).resolve()
                if not referenced.is_relative_to(folder.resolve()) or not referenced.is_file():
                    issues.append(tagged(identity, {"severity": "WARNING", "issue": "MANIFEST_SOURCE_UNAVAILABLE", "detail": source}))
            trace = events(folder / "events.csv", identity, tables["inference_tasks"], meta, sources)
            observations = {o["observation_id"]: o for o in tables["observations"]}
            for task in tables["inference_tasks"]:
                if task["task_id"] in trace["vision"]:
                    observation = trace["vision"][task["task_id"]]
                    result = decode(task.get("result_json"), {})
                    if "region" not in result:
                        result["region"] = observation.get("region")
                        task["result_json"] = json.dumps(result)
            image_rows = []
            for image in tables["images"]:
                actual = safe_image(folder, image["image_id"])
                row = dict(image, available=bool(actual and actual.is_file()))
                if row["available"]:
                    with Image.open(actual) as im:
                        row.update(width=im.width, height=im.height)
                        im.verify()
                    row["sha256"] = digest(actual)
                    sources.append({"path": actual.relative_to(ROOT).as_posix(), "bytes": actual.stat().st_size, "sha256": row["sha256"]})
                elif boolean(image.get("stored")) is True:
                    issues.append(tagged(identity, {"severity": "WARNING", "issue": "STORED_IMAGE_MISSING", "detail": image["image_id"]}))
                image_rows.append(tagged(identity, row))
            config = meta.get("config", {})
            pinterval = number(meta.get("power_interval_seconds")) or 60.
            power, power_rows, segments = power_analysis(tables["power_readings"], start, end, 2*pinterval, power_corrections)
            counts, pairs = count_pairs(tables["ground_truth"], tables["inference_tasks"], config, start, end)
            activity, latencies, task_issues = task_metrics(tables["inference_tasks"], start, end)
            interval = number(config.get("runtime", {}).get("evaluation_interval_seconds")) or 1.
            question_rows = question_metrics(tables["question_results"], start, end, 2*interval)
            resource_interval = number(config.get("runtime", {}).get("resource_interval_seconds")) or 1.
            resources = resource_metrics(tables["samples_1s"], resource_interval, expected_samples)
            faults = fault_metrics(tables["faults"], start, end)
            for fault in faults:
                if fault["negative_latency"]:
                    issues.append(tagged(identity, {"severity": "WARNING", "issue": "NEGATIVE_FAULT_LATENCY_EXCLUDED", "detail": fault["fault_id"]}))
            seconds = {int(s["second"]) for s in tables["samples_1s"]}
            missing = sorted(set(range(expected_samples))-seconds)
            declared_missing = {second for gap in trace["gaps"] for second in range(int(gap["from_second"]), int(gap["to_second"])+1)}
            if set(missing) != declared_missing.intersection(range(expected_samples)):
                issues.append(tagged(identity, {"severity": "WARNING", "issue": "SAMPLE_GAPS_DIFFER_FROM_MISSING_SECONDS", "detail": {"missing": missing, "declared": sorted(declared_missing)}}))
            all_tables["segundos_ausentes"].extend(tagged(identity, {"second": s, "declared_gap": s in declared_missing}) for s in missing)
            sample_metrics = {"sample_rows": len(seconds), "expected_samples": expected_samples,
                              "sample_coverage_fraction": len(seconds.intersection(range(expected_samples)))/expected_samples,
                              "missing_seconds": len(missing)}
            for field in ("temperature_status", "humidity_status", "aqi_status", "tvoc_status", "eco2_status", "presence_status", "count_status", "fsm_state"):
                counter = Counter(s.get(field, "") for s in tables["samples_1s"])
                all_tables["estados_contexto"].extend(tagged(identity, {"field": field, "value": state, "samples": n,
                                             "fraction_expected_samples": n/expected_samples}) for state, n in counter.items())
            pubs = {}
            for row in tables["question_results"]:
                if row.get("interpretation_id"):
                    pub = pubs.setdefault(row["interpretation_id"], {"count": 0, "unique": []})
                    pub["count"] += 1
                    value = {k: row.get(k) for k in ("question_id", "status", "answer", "source_snapshot_id", "evidence_ids")}
                    if value not in pub["unique"]:
                        pub["unique"].append(value)
            responses, fragments = collect(identity, folder, tables["inference_tasks"], observations,
                                           trace["inputs"], trace["snapshots"], pubs)
            all_responses.extend(responses)
            all_fragments.extend(fragments)
            for response in responses:
                if not response["input"] or not response["snapshot"] or response["missing_evidence_ids"]:
                    issues.append(tagged(identity, {"severity": "WARNING", "issue": "INCOMPLETE_INTERPRETATION_PROVENANCE", "detail": {
                        "task_id": response["task_id"], "input": bool(response["input"]), "snapshot": bool(response["snapshot"]), "missing_ids": response["missing_evidence_ids"]}}))
            row = {**identity, "status": meta.get("status"), "window_seconds": window,
                   "start_time": meta.get("start_time"), "end_time_recorded": meta.get("end_time"),
                   "software_version": meta.get("software_version"), "config_hash": meta.get("config_hash"),
                   "session_id": meta.get("session_id"), "export_event_sequence": meta.get("export_event_sequence"),
                   "question_publications": len(tables["question_results"]), "images_available": sum(i["available"] for i in image_rows),
                   "faults_injected": len(faults), "faults_detection_observed": sum(f["detection_observed"] for f in faults),
                   "faults_recovery_observed": sum(f["recovery_observed"] for f in faults),
                   "period_intervals_due": sum(number(p.get("intervals_due")) or 0 for p in trace["periods"]) if identity["mode"] == "A" else None,
                   "period_intervals_missed": sum(number(p.get("missed_intervals")) or 0 for p in trace["periods"]) if identity["mode"] == "A" else None,
                   **sample_metrics, **power, **counts, **activity, **resources}
            run_rows.append(row)
            metadata_rows.append({**identity, "metadata": meta})
            for name, values in (("potencia_lecturas", power_rows), ("potencia_segmentos", segments), ("pares_conteo", pairs),
                                 ("latencias", latencies), ("preguntas", question_rows), ("fallos", faults),
                                 ("imagenes", image_rows), ("tareas", tables["inference_tasks"])):
                all_tables[name].extend(tagged(identity, value) for value in values)
            all_tables["eventos_conteos"].extend(tagged(identity, {"type": key, "count": n}) for key, n in trace["counts"].items())
            all_tables["decisiones_motivos"].extend(tagged(identity, {"event_type": key[0], "action": key[1], "reason": key[2], "count": n}) for key, n in trace["decisions"].items())
            all_tables["ciclo_tareas"].extend(trace["lifecycle"])
            all_tables["periodos"].extend(trace["periods"])
            all_tables["huecos_muestreo"].extend(trace["gaps"])
            requests = Counter(row.get("status") for row in tables["observer_requests"])
            all_tables["solicitudes_observador"].extend(tagged(identity, {"status": key, "count": n}) for key, n in requests.items())
            issues.extend(tagged(identity, {"severity": "WARNING", **item}) for item in task_issues)
            plots.timeline(identity, tables["samples_1s"], segments, pairs, faults, start, window, figures, figures_index)
        expected = {(f"S{s}", mode, r) for s in (1, 2, 3) for mode in "ABCDEF" for r in (1, 2, 3)}
        if identities != expected:
            issues.append({"severity": "WARNING", "issue": "INCOMPLETE_OR_UNEXPECTED_GRID", "detail": {"missing": sorted(expected-identities), "extra": sorted(identities-expected)}})
        if len({r["software_version"] for r in run_rows}) > 1:
            issues.append({"severity": "WARNING", "issue": "MULTIPLE_SOFTWARE_IDENTIFIERS", "detail": "No se presupone equivalencia de versiones ni se interpreta software_version como commit Git."})
        corrected_rows = [r for r in all_tables["potencia_lecturas"] if r["power_correction_applied"]]
        if (len(corrected_rows) != len(power_corrections)
                or {r["record_id"] for r in corrected_rows} != set(power_corrections)
                or any(r["folder"] != power_corrections[r["record_id"]]["folder"] for r in corrected_rows)):
            raise ValueError("Las correcciones de potencia no corresponden exactamente a los registros previstos")
        rubric = export_evaluation(output, SCRIPTS / "evaluacion_gemma.json", all_responses)
        assessments = json.loads((output / "evaluacion_rubrica.json").read_text(encoding="utf-8"))
        semantic, review_issues = export_corpus(output, SCRIPTS, all_responses, all_fragments, assessments)
        issues.extend(review_issues)
        group_summary, contrasts = aggregate(run_rows)
        for name, rows in {"ejecuciones": run_rows, "esquemas": schema, "auditoria": issues,
                           "resumen_configuraciones": group_summary, "contrastes_descriptivos": contrasts, **all_tables}.items():
            write_csv(output / f"{name}.csv", rows)
        write_json(output / "metadatos.json", metadata_rows)
        write_json(output / "metodos.json", methods())
        write_json(output / "fuentes.json", sources)
        plots.comparisons(run_rows, figures, figures_index)
        plots.coverage(all_tables["preguntas"], figures, figures_index)
        plots.count_scatter(all_tables["pares_conteo"], figures, figures_index)
        plots.fault_plot(all_tables["fallos"], figures, figures_index)
        plots.semantic_review(semantic, figures, figures_index)
        from publication import generate
        generate(figures, figures_index)
        write_json(output / "figuras.json", figures_index)
        write_text(output / "FIGURAS.md", "# Figuras generadas\n\n" + "\n\n".join(f"- `{r['file']}` / `{r['vector_file']}`: {r['caption']}" for r in figures_index)+"\n")
        report(output, run_rows, all_tables, issues, semantic, rubric)
        checks = verify(run_rows, all_tables, all_responses, sources, output, figures, figures_index)
        manifest.update(status="COMPLETED", finished_at_utc=datetime.now(timezone.utc).isoformat(),
                        runs=len(run_rows), figures=len(figures_index), sources=len(sources),
                        warnings=len(issues), semantic_review=semantic, rubric_evaluation=rubric, checks=checks,
                        figures_directory=str(figures), results_directory=str(output))
        manifest["outputs"] = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob("*")) if p.is_file() and p.name != "manifest.json"}
        manifest["figure_hashes"] = {p.name: digest(p) for item in figures_index for key in ("file", "vector_file") if (p := figures/item[key]).is_file()}
        manifest["chapter_table_hashes"] = {p.name: digest(p) for p in sorted((ROOT / "secciones" / "resultados").glob("*.tex"))}
        manifest["annex_table_hashes"] = {p.name: digest(p) for p in sorted((ROOT / "secciones" / "anexos").glob("*.tex"))}
        write_json(output / "manifest.json", manifest)
        print(f"Listo: {len(run_rows)} ejecuciones, {len(figures_index)} figuras PNG/PDF.\nInforme: {output/'INFORME.md'}\nCorpus IA: {output/'revision_ia.html'}", flush=True)
    except Exception as error:
        manifest.update(status="FAILED", error=str(error))
        write_json(output / "manifest.json", manifest)
        write_text(output / "error.txt", traceback.format_exc())
        raise


def report(output, runs, tables, issues, semantic, rubric):
    versions = Counter(row["software_version"] for row in runs)
    pairs = [row for row in tables["pares_conteo"] if row["pair_status"] == "PAIRED"]
    faults = tables["fallos"]
    task_states = Counter(row.get("status") for row in tables["tareas"])
    lines = ["# SENSE · Informe descriptivo reproducible", "",
             "Criterios definidos después de la campaña. Este informe organiza evidencia; no valida autenticidad física, superioridad causal ni aceptación institucional.", "",
             f"- Ejecuciones: {len(runs)}. Ventana total: {sum(r['window_seconds'] for r in runs)/3600:.3f} h.",
             f"- Identificadores software_version distintos: {len(versions)}; no se presume equivalencia de ejecutables.",
             "- Presencia estandarizada: 1 = presente; 0 = ausente. Los datos no disponibles conservan su estado.",
             f"- Tareas exportadas: {len(tables['tareas'])}. Estados finales: `{json.dumps(dict(task_states), ensure_ascii=False)}`.",
             f"- Publicaciones por pregunta: {sum(r['question_publications'] for r in runs)}; no son inferencias independientes.",
             f"- Pares de conteo admitidos: {len(pairs)}; {sum(r['count_explicit_records'] for r in runs)} registros con conteo entre {len(tables['pares_conteo'])} registros humanos. Asociación explícita o temporal en pares_conteo.csv.",
             f"- Fallos: {len(faults)}; detección observada {sum(f['detection_observed'] for f in faults)}, recuperación observada {sum(f['recovery_observed'] for f in faults)}. Estos conteos no son tasas de éxito independientes.",
             f"- Respuestas IA con salida conservada: {semantic['responses']}; fragmentos {semantic['fragments']}, codificados {semantic['reviewed_fragments']}, pendientes de codificación {semantic['pending_fragments']}.",
             f"- Correcciones de potencia confirmadas: {sum(r['power_corrections_applied'] for r in runs)}. potencia_lecturas.csv conserva power_w original y analysis_power_w utilizado; correcciones_potencia.json identifica los cambios y su procedencia.",
             f"- Rúbrica posterior asistida por IA: {rubric['overall']['n']} respuestas, tres criterios de 1 a 5; calidad media {rubric['overall']['quality']['mean']:.3f}. Adaptación de Rico y Larson (2026), DOI 10.3390/aisens2020007. Fuente y justificaciones en evaluacion_rubrica.json; distinta de la revisión conjunta de dos observadores durante la campaña y de la codificación por fragmentos.",
             f"- Incidencias documentadas: {len(issues)}. Revisar auditoria.csv antes de usar cifras.", "",
             "## Lectura por escenario y configuración", "",
             "Cada fila presenta una ejecución completa. Wh cubiertos no equivalen a energía total de 30 min. MAE solo corresponde a pares puntuales con el n indicado. CPU conserva su escala reportada.", "",
             "|Escenario|Modo|R|Visión completada no simulada|Texto|Visual|CPU mediana %|Potencia ponderada W|Cobertura eléctrica %|Wh cubiertos|Pares n|MAE|",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    def fmt(value):
        return "s/d" if value is None else f"{value:.3f}"
    for r in sorted(runs, key=lambda r: (r['scenario'], r['mode'], r['repetition'])):
        lines.append("|"+"|".join([r['scenario'], r['mode'], str(r['repetition']), str(r['vision_completed_nonsimulated']),
                                 str(r['text_completed_nonsimulated']), str(r['multimodal_completed_nonsimulated']),
                                 fmt(r['cpu_percent_median']), fmt(r['power_time_weighted_w_covered']),
                                 fmt(100*r['power_coverage_fraction']), fmt(r['energy_estimated_wh_covered']),
                                 str(r['count_pairs_n']), fmt(r['count_mae'])])+"|")
    lines.extend(["", "## Fuentes para continuar la investigación", "",
                  "- RQ1: preguntas.csv y estados_contexto.csv describen disponibilidad operativa; respuestas_ia.json y revision_ia.html permiten examinar evidencia. RESOLVED no implica corrección.",
                  "- RQ2: ejecuciones.csv, tareas.csv, latencias.csv, periodos.csv y pares_conteo.csv permiten comparar A–C por escenario. No hay recall global sin referencia continua.",
                  "- RQ3/RQ4: comparar C/D y D/E como configuraciones completas, con sus tareas y costos. Q6 textual y Q7 visual tienen propósitos diferentes.",
                  "- F: fallos.csv y ciclo_tareas.csv conservan simulación, etapas, latencias, preexistencia y solapamiento. No interpretar trabajo simulado como inferencia ejecutada.",
                  "- Codificación de IA: completar ../revision_ia.csv; main.py preserva ese archivo e incorpora solo revisiones explícitas válidas. No modifica ni inventa etiquetas semánticas.",
                  "- Metodología y trazabilidad: metodos.json, fuentes.json, metadatos.json y manifest.json conservan reglas, hashes y versiones del análisis.", "",
                  "## Límites pendientes", "",
                  "El procedimiento de anotación, la doble comprobación, los valores reconfirmados y la revisión humana se documentan en las respuestas del 12-11-2026. La rúbrica resume los juicios del informe aportado: sus medias no son porcentajes de exactitud física ni medidas de acuerdo entre observadores. El servidor se mantuvo en CPU con cuatro hilos según los observadores. La energía integrada describe el montaje completo.", ""])
    write_text(output / "INFORME.md", "\n".join(lines))


def verify(runs, tables, responses, sources, output, figures, registry):
    """Autocomprobación de denominadores, referencias, archivos e integridad de fuentes."""
    for row in runs:
        for field in ("sample_coverage_fraction", "power_coverage_fraction", "resource_sample_coverage_fraction"):
            assert 0 <= row[field] <= 1+1e-9, (row["run_id"], field, row[field])
        pairs = [r for r in tables["pares_conteo"] if r["run_id"] == row["run_id"] and r["pair_status"] == "PAIRED"]
        assert len(pairs) == row["count_pairs_n"]
        assert len({p["task_id"] for p in pairs}) == len(pairs)
        for q in range(1, 8):
            fractions = [r["run_fraction"] for r in tables["preguntas"] if r["run_id"] == row["run_id"] and r["question_id"] == f"Q{q}"]
            assert abs(sum(fractions)-1) < 1e-8, (row["run_id"], q)
    assert len({(r["run_id"], r["task_id"]) for r in responses}) == len(responses)
    for source in sources:
        assert digest(ROOT / source["path"]) == source["sha256"], f"La fuente cambió durante el análisis: {source['path']}"
    for item in registry:
        with Image.open(figures / item["file"]) as im:
            im.verify()
        assert (figures / item["vector_file"]).read_bytes().startswith(b"%PDF-"), item
    for path in output.rglob("*.json"):
        if path.name != "manifest.json":
            json.loads(path.read_text(encoding="utf-8"))
    return {"input_hashes_unchanged": len(sources), "png_verified": len(registry),
            "pdf_headers_verified": len(registry), "run_denominators_checked": len(runs),
            "semantic_review_automated": False}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    run()
