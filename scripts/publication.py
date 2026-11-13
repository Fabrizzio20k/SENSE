"""Material de investigación y cifras trazables para el capítulo de resultados."""
from collections import Counter
from pathlib import Path
import argparse
import json

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from common import csv_rows, stats, write_csv, write_json, write_text

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
OUT = SCRIPTS / "resultados" / "investigacion"


def load():
    return json.loads((SCRIPTS / "resultados" / "respuestas_ia.json").read_text(encoding="utf-8"))


def prepare(contacts=True):
    OUT.mkdir(parents=True, exist_ok=True)
    runs = pd.read_csv(SCRIPTS / "resultados" / "ejecuciones.csv")
    tasks = pd.read_csv(SCRIPTS / "resultados" / "tareas.csv", keep_default_na=False, dtype=str)
    faults = pd.read_csv(SCRIPTS / "resultados" / "fallos.csv", keep_default_na=False, dtype=str)
    questions = pd.read_csv(SCRIPTS / "resultados" / "preguntas.csv")
    pairs = pd.read_csv(SCRIPTS / "resultados" / "pares_conteo.csv")
    responses = load()
    summary = {"runs": len(runs), "sample_rows": int(runs.sample_rows.sum()),
               "missing_seconds": int(runs.missing_seconds.sum()), "sample_coverage": stats(runs.sample_coverage_fraction),
               "task_states": tasks.status.value_counts().to_dict(), "responses": len(responses),
               "response_questions": dict(Counter(r["question_id"] for r in responses)),
               "explicit_publication_links": sum(r["publication_count"] > 0 for r in responses),
               "power_coverage": stats(runs.power_coverage_fraction)}
    measures = ["vision_completed_nonsimulated", "text_completed_nonsimulated", "multimodal_completed_nonsimulated",
                "cpu_percent_median", "ram_used_mb_median", "process_rss_mb_max", "power_time_weighted_w_covered",
                "power_coverage_fraction", "vision_duration_median_s", "text_duration_median_s", "multimodal_duration_median_s"]
    grouped = []
    for (scenario, mode), group in runs.groupby(["scenario", "mode"], sort=True):
        row = {"scenario": scenario, "mode": mode}
        for measure in measures:
            row[measure] = stats(group[measure])
        grouped.append(row)
    summary["configurations"] = grouped
    latencies = []
    valid = tasks[(tasks.status == "TASK_COMPLETED") & (tasks.simulated == "False") & (tasks.model_executed != "False")]
    for (scenario, action), group in valid.groupby(["scenario", "action"], sort=True):
        latencies.append({"scenario": scenario, "action": action, **stats(group.duration_seconds), "queue": stats(group.queue_seconds)})
    summary["latencies"] = latencies
    fault_summary = []
    for (component, kind), group in faults.groupby(["component", "kind"], sort=True):
        eligible = group[group.preexisting_failure == "False"]
        fault_summary.append({"component": component, "kind": kind, "n": len(group),
                              "applied": int((group.applied_at != "").sum()),
                              "detected": int((group.detected_at != "").sum()),
                              "restored": int((group.restored_at != "").sum()),
                              "recovered": int((group.recovered_at != "").sum()),
                              "preexisting": int((group.preexisting_failure == "True").sum()),
                              "overlapped": int(group.overlapping_fault_ids.map(lambda x: bool(json.loads(x))).sum()),
                              "detection": stats(eligible.detection_latency_numeric_s), "recovery": stats(eligible.recovery_latency_numeric_s)})
    summary["faults"] = fault_summary
    good = pairs[pairs.pair_status == "PAIRED"]
    summary["count_reference"] = {"n": len(good), "mae": float(good.absolute_error.mean()),
                                  "rmse": float((good.error.pow(2).mean())**.5),
                                  "exact": int((good.error == 0).sum()), "reasons": pairs.pair_status.value_counts().to_dict(),
                                  "explicit_records": int(runs.count_explicit_records.sum()),
                                  "task_linked": int((good.link_method == "task_id").sum()),
                                  "within_tolerance": int((good.delta_s.abs() <= good.tolerance_s).sum()),
                                  "delta_s": stats(good.delta_s), "recording_delay_s": stats(good.recording_delay_s)}
    count_groups = []
    for scenario, group in good.groupby("scenario", sort=True):
        strict = group[group.delta_s.abs() <= group.tolerance_s]
        count_groups.append({"scenario": scenario, "n": len(group),
                             "mae": float(group.absolute_error.mean()),
                             "rmse": float(group.error.pow(2).mean()**.5),
                             "exact": int((group.error == 0).sum()), "within_tolerance_n": len(strict),
                             "within_tolerance_mae": stats(strict.absolute_error)["mean"]})
    summary["count_by_scenario"] = count_groups
    summary["power_readings"] = int(runs.power_records.sum())
    summary["power_reconfirmed"] = int(runs.power_repeated.sum())
    summary["power_corrections_applied"] = int(runs.power_corrections_applied.sum())
    summary["power_by_mode"] = [
        {"mode": mode, "runs": len(group),
         "runs_with_completed_ai": int(((group.text_completed_nonsimulated + group.multimodal_completed_nonsimulated) > 0).sum()),
         "power_time_weighted_w_covered": stats(group.power_time_weighted_w_covered),
         "coverage": stats(group.power_coverage_fraction), "energy_wh_covered": stats(group.energy_estimated_wh_covered)}
        for mode, group in runs.groupby("mode", sort=True)]
    summary["rubric_evaluation"] = json.loads((SCRIPTS / "resultados" / "evaluacion_rubrica_resumen.json").read_text(encoding="utf-8"))
    summary["question_resolved"] = []
    for (scenario, mode, q), group in questions.groupby(["scenario", "mode", "question_id"]):
        summary["question_resolved"].append({"scenario": scenario, "mode": mode, "question": q,
                                            "mean_fraction": float(group[group.status == "RESOLVED"].run_fraction.sum()/group.run_id.nunique())})
    link_fields = Counter()
    for meta in sorted((ROOT / "data").glob("E*/*/*/metadata.json")):
        for row in csv_rows(meta.parent / "question_results.csv"):
            for key in ("interpretation_id", "source_snapshot_id"):
                link_fields[key] += bool(row.get(key))
    summary["publication_fields_nonempty"] = dict(link_fields)
    write_json(OUT / "cifras_capitulo.json", summary)
    if not contacts:
        return summary, runs, questions, faults, responses
    visual = [(i, r) for i, r in enumerate(responses) if r["image_available"]]
    font = ImageFont.truetype("DejaVuSans.ttf", 18) if Path("DejaVuSans.ttf").exists() else ImageFont.load_default(size=20)
    for page, offset in enumerate(range(0, len(visual), 6), 1):
        sheet = Image.new("RGB", (1240, 1500), "white")
        draw = ImageDraw.Draw(sheet)
        for slot, (index, response) in enumerate(visual[offset:offset+6]):
            x, y = (slot % 2)*620, (slot // 2)*500
            draw.text((x+8, y+4), f"{index:03} {response['scenario']}/{response['mode']}/R{response['repetition']} {response['task_id'][:8]}", font=font, fill="black")
            with Image.open(response["image_path"]) as original:
                im = original.convert("RGB")
                im.thumbnail((604, 454))
                sheet.paste(im, (x+8, y+38))
        sheet.save(OUT / f"contacto_{page:02}.jpg", quality=92)
    assert len(responses) == sum(summary["response_questions"].values())
    assert len({(r["run_id"], r["task_id"]) for r in responses}) == len(responses)
    print(json.dumps({k:v for k,v in summary.items() if k not in ("configurations", "question_resolved")}, ensure_ascii=False, indent=2))
    print(f"Hojas de contacto: {(len(visual)+5)//6}; cifras: {OUT/'cifras_capitulo.json'}")


def generate(figures, registry):
    """Figuras seleccionadas y tablas del capítulo desde los mismos derivados."""
    import matplotlib.pyplot as plt
    from plots import save

    summary, runs, questions, faults, responses = prepare(contacts=False)
    tables = ROOT / "secciones" / "resultados"
    tables.mkdir(parents=True, exist_ok=True)

    def fmt(value, digits=1):
        return "--" if value is None else f"{value:.{digits}f}".replace(".", "{,}")

    def table(name, header, rows, columns, directory=tables):
        body = ["% Generado por scripts/main.py; no editar cifras a mano.", r"\begin{tabular}{"+columns+"}", r"\hline",
                " & ".join(header)+r" \\", r"\hline"]
        body.extend(" & ".join(row)+r" \\" for row in rows)
        body.extend([r"\hline", r"\end{tabular}", ""])
        write_text(directory / f"{name}.tex", "\n".join(body))

    annexes = ROOT / "secciones" / "anexos"
    inventory = runs.sort_values(["scenario", "mode", "repetition"])
    assert len(inventory) == inventory.run_id.nunique() == 54
    inventory_rows = [f"{r.scenario} / {r['mode']} / {int(r.repetition)} & \\texttt{{{r.folder}}} & \\texttt{{{r.run_id}}}" + r" \\"
                      for _, r in inventory.iterrows()]
    write_text(annexes / "matriz_ejecuciones.tex", "% Generado por scripts/main.py desde ejecuciones.csv.\n" + "\n".join(inventory_rows) + "\n")
    corrections = json.loads((SCRIPTS / "correcciones_potencia.json").read_text(encoding="utf-8"))["records"]
    correction_rows = [[f"\\texttt{{{r['folder']}}}", f"\\texttt{{{r['record_id']}}}", fmt(r['original_w']), fmt(r['corrected_w'])]
                       for r in corrections]
    table("correcciones_potencia", ["Carpeta", "Identificador del registro", "Original", "Rectificado"], correction_rows, "llrr", directory=annexes)

    rows = []
    for row in summary["configurations"]:
        vision = row["vision_completed_nonsimulated"]
        rows.append([row["scenario"], row["mode"], fmt(vision["median"], 0)+" ["+fmt(vision["min"], 0)+"--"+fmt(vision["max"], 0)+"]",
                     fmt(row["text_completed_nonsimulated"]["mean"]*3, 0), fmt(row["multimodal_completed_nonsimulated"]["mean"]*3, 0)])
    table("actividad", ["Escenario", "Modo", "Visión: mediana [rango]", "Texto: total", "Visual: total"], rows, "llrrr")
    action_names = {"vision": "Visión", "interpret_text": "Texto", "interpret_multimodal": "Multimodal", "text": "Texto", "multimodal": "Multimodal"}
    rows = [[r["scenario"], action_names.get(r["action"], r["action"].replace("_", r"\_")), str(r["n"]), fmt(r["median"]), fmt(r["p95"]), fmt(r["queue"]["p95"])] for r in summary["latencies"]]
    table("latencias", ["Escenario", "Tarea", "$n$", "Mediana (s)", "p95 (s)", "Cola p95 (s)"], rows, "llrrrr")
    rows = [[r["scenario"], str(r["n"]), fmt(r["mae"], 2), fmt(r["rmse"], 2), str(r["exact"]),
             str(r["within_tolerance_n"]), fmt(r["within_tolerance_mae"], 2)]
            for r in summary["count_by_scenario"]]
    table("conteo", ["Escenario", "$n$", "MAE", "RMSE", "Exactos", "$n_{3s}$", "MAE$_{3s}$"], rows, "lrrrrrr")
    rows = []
    for r in summary["faults"]:
        name = r["component"].upper() if r["component"] != "camera" else "Cámara"
        kind = {"TIMEOUT": "Timeout", "DATA_LOSS": "Pérdida", "CAMERA_UNAVAILABLE": "No disponible"}[r["kind"]]
        rows.append([name, kind, str(r["n"]), str(r["detected"]), str(r["recovered"]), str(r["detection"]["n"])+" / "+fmt(r["detection"]["median"]), str(r["recovery"]["n"])+" / "+fmt(r["recovery"]["median"])])
    table("fallos", ["Ruta", "Tipo", "Total", "Det.", "Rec.", "$n_d$ / med. s", "$n_r$ / med. s"], rows, "llrrrrr")

    rubric = summary["rubric_evaluation"]
    rows = [[r["scenario"], r["question_id"], str(r["n"]),
             *[fmt(r[k]["mean"], 2) for k in ("accuracy", "relevance", "support", "quality")],
             str(r["critical_errors"]), str(r["task_successes"])] for r in rubric["by_scenario_question"]]
    table("calidad_gemma", ["Esc.", "Ruta", "$n$", "Exact.", "Pert.", "Sust.", "Calidad", "EC", "Éxitos"], rows, "llrrrrrrr")

    cases = json.loads((SCRIPTS / "casos_ia.json").read_text(encoding="utf-8"))
    by_task = {r["task_id"]: r for r in responses}
    case_rows = []
    for case in cases["cases"]:
        response = by_task[case["task_id"]]
        assert case["excerpt"].casefold() in response["raw_output"].casefold(), case["case"]
        assert response["snapshot"] and not response["missing_evidence_ids"], case["case"]
        if response["question_id"] == "Q7":
            assert response["image_available"], case["case"]
        case_rows.append({**case, **{k: response[k] for k in ("run_id", "scenario", "mode", "repetition", "question_id", "snapshot_id", "image_id")}, "reviewer": cases["reviewer"]})
    assert len(case_rows) == len({r["task_id"] for r in case_rows}) == 8
    write_csv(OUT / "casos_ia.csv", case_rows)
    write_text(OUT / "CASOS_IA.md", "# Casos documentales preliminares\n\n"+cases["scope"]+"\n\nLos juicios siguientes son antecedentes documentales. La evaluación completa se conserva por separado en evaluacion_rubrica.json, con identificadores C001–C149 del PDF aportado.\n\nProcedencia: "+cases["reviewer"]+"\n\n"+"\n\n".join(
        f"## {r['case']} · {r['scenario']}/{r['mode']}/R{r['repetition']} · {r['question_id']}\n\nTarea `{r['task_id']}`; snapshot `{r['snapshot_id']}`; imagen `{r['image_id'] or 'no aplica'}`.\n\nEnunciado: «{r['excerpt']}».\n\nJuicio documental preliminar: **{r['verdict']}**. {r['evidence']}\n\nCriterio: {r['criterion']}" for r in case_rows)+"\n")

    colors = ["#176B87", "#A65B25", "#26795D"]
    with plt.rc_context({"font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5, "xtick.labelsize": 8, "ytick.labelsize": 8}):
        fig, axes = plt.subplots(2, 3, figsize=(6.2, 4.0), sharey=True, layout="constrained")
        for row, question in enumerate(("Q6", "Q7")):
            for col, scenario in enumerate(("S1", "S2", "S3")):
                ax = axes[row, col]
                group = [r for r in rubric["by_run"] if r["scenario"] == scenario and r["question_id"] == question]
                pooled = next(r for r in rubric["by_scenario_question"] if r["scenario"] == scenario and r["question_id"] == question)
                for x, criterion in enumerate(("accuracy", "relevance", "support")):
                    offsets = [(i-(len(group)-1)/2)*.035 for i in range(len(group))]
                    ax.scatter([x+v for v in offsets], [r[criterion]["mean"] for r in group], s=16, color=colors[col], alpha=.7)
                    ax.hlines(pooled[criterion]["mean"], x-.24, x+.24, color="black", lw=1.2)
                ax.set(title=f"{scenario} · {question} · n={pooled['n']}", ylim=(.8, 5.2), yticks=range(1, 6),
                       xticks=range(3), xticklabels=["Exact.", "Pert.", "Sust."])
                ax.grid(axis="y", alpha=.2)
        axes[0, 0].set_ylabel("Media en escala 1–5")
        axes[1, 0].set_ylabel("Media en escala 1–5")
        save(fig, figures, "cap4_calidad_gemma", "Puntos: media por ejecución con respuestas; trazo: media ponderada por respuestas en cada celda. Evaluación posterior asistida con tres criterios adaptados de Rico y Larson (2026). Las tareas Q6/Q7 y los prompts difieren; no son réplicas independientes ni un experimento emparejado.", registry)

        fig, axes = plt.subplots(1, 3, figsize=(6.2, 2.7), sharey=True, layout="constrained")
        for ax, scenario, color in zip(axes, ("S1", "S2", "S3"), colors):
            for x, mode in enumerate("ABC"):
                g = runs[(runs.scenario == scenario) & (runs["mode"] == mode)].sort_values("repetition")
                values = g.vision_completed_nonsimulated
                ax.scatter([x-.1, x, x+.1], values, s=25, color=color, zorder=3)
                ax.hlines(values.median(), x-.23, x+.23, color="black", lw=1.2)
            ax.set(xticks=range(3), xticklabels=list("ABC"), title=scenario, ylim=(0, 64))
            ax.grid(axis="y", alpha=.2)
        axes[0].set_ylabel("Tareas de visión completadas / 30 min")
        save(fig, figures, "cap4_adquisicion", "Cada punto representa una ejecución; trazo negro: mediana de tres ejecuciones. Tareas completadas no simuladas, A–C por escenario.", registry)

        fig, axes = plt.subplots(1, 3, figsize=(6.2, 3.2), sharey=True, layout="constrained")
        for ax, scenario in zip(axes, ("S1", "S2", "S3")):
            matrix = []
            for mode in "ABCDEF":
                matrix.append([next(r["mean_fraction"]*100 for r in summary["question_resolved"] if r["scenario"] == scenario and r["mode"] == mode and r["question"] == f"Q{q}") for q in range(1, 8)])
            im = ax.imshow(matrix, vmin=0, vmax=100, cmap="Blues", aspect="auto")
            for y, row in enumerate(matrix):
                for x, value in enumerate(row):
                    na = x == 6 and y < 4
                    ax.text(x, y, "—" if na else f"{value:.0f}", ha="center", va="center", fontsize=6.7, color="white" if value > 55 else "black")
            ax.set(title=scenario, xticks=range(7), xticklabels=[f"Q{q}" for q in range(1, 8)], yticks=range(6), yticklabels=list("ABCDEF"))
            ax.tick_params(axis="x", rotation=90)
        fig.colorbar(im, ax=axes, shrink=.8, label="Tiempo con estado RESOLVED (%)", fraction=.035)
        save(fig, figures, "cap4_cobertura", "Promedio de tres fracciones temporales por celda. RESOLVED es estado operativo, no corrección; Q7 no aplica a A–D. No se prolonga el último estado ni se rellenan huecos.", registry)

        fig, axes = plt.subplots(2, 3, figsize=(6.2, 4.8), sharex=True, sharey="row", layout="constrained")
        for col, scenario in enumerate(("S1", "S2", "S3")):
            for row, field in enumerate(("cpu_percent_median", "ram_used_mb_median")):
                ax = axes[row, col]
                for x, mode in enumerate("ABCDEF"):
                    g = runs[(runs.scenario == scenario) & (runs["mode"] == mode)].sort_values("repetition")
                    values = g[field] / (1024 if row else 1)
                    ax.scatter([x-.15, x, x+.15], values, s=17, color=colors[col], zorder=3)
                    ax.hlines(values.median(), x-.28, x+.28, color="black", lw=1)
                ax.set(xticks=range(6), xticklabels=list("ABCDEF"))
                ax.grid(axis="y", alpha=.2)
                if row == 0:
                    ax.set_title(scenario)
        axes[0, 0].set_ylabel("Mediana de CPU máquina (%)")
        axes[1, 0].set_ylabel("Mediana de RAM máquina (GiB)")
        save(fig, figures, "cap4_recursos", "Puntos: medianas temporales por ejecución; trazo: mediana de tres ejecuciones. Telemetría de máquina, muestras únicas vigentes. CPU mantiene su escala exportada; RAM en GiB.", registry)

        fig, axes = plt.subplots(2, 3, figsize=(6.2, 4.5), sharex=True, sharey="row", layout="constrained")
        for col, scenario in enumerate(("S1", "S2", "S3")):
            for row, field in enumerate(("power_time_weighted_w_covered", "power_coverage_fraction")):
                ax = axes[row, col]
                for x, mode in enumerate("ABCDEF"):
                    g = runs[(runs.scenario == scenario) & (runs["mode"] == mode)].sort_values("repetition")
                    values = g[field] * (100 if row else 1)
                    ax.scatter([x-.15, x, x+.15], values, s=17, color=colors[col], zorder=3)
                ax.set(xticks=range(6), xticklabels=list("ABCDEF"))
                ax.grid(axis="y", alpha=.2)
                if row == 0:
                    ax.set_title(scenario)
        axes[0, 0].set_ylabel("Potencia ponderada cubierta (W)")
        axes[1, 0].set_ylabel("Cobertura de integración (%)")
        axes[1, 0].set_ylim(0, 105)
        save(fig, figures, "cap4_potencia", "Cada punto corresponde a una ejecución. Potencia media ponderada solo durante los intervalos integrables y su cobertura; montaje completo alimentado por la toma. No se extrapola energía a 30 minutos.", registry)

        fig, axes = plt.subplots(1, 2, figsize=(6.2, 3.9), sharey=True, layout="constrained")
        names = ["Cámara / no disp.", "Cámara / timeout", "ENS160 / pérdida", "Gemma / timeout", "Radar / pérdida", "SHT40 / pérdida"]
        groups = list(faults.groupby(["component", "kind"], sort=True))
        for ax, field, title in zip(axes, ("detection_latency_numeric_s", "recovery_latency_numeric_s"), ("Detección", "Recuperación")):
            for y, (_, group) in enumerate(groups):
                values = pd.to_numeric(group.loc[group.preexisting_failure == "False", field], errors="coerce").dropna().tolist()
                ax.scatter(values, [y+(i % 5-2)*.045 for i in range(len(values))], s=13, color=colors[0], alpha=.7)
                ax.text(.98, y+.22, f"n={len(values)}", transform=ax.get_yaxis_transform(), ha="right", fontsize=7)
            ax.set(title=title, xlabel="Latencia registrada (s)", yticks=range(6), yticklabels=names)
            ax.grid(axis="x", alpha=.2)
        axes[0].invert_yaxis()
        save(fig, figures, "cap4_fallos", "Latencias con extremos observados, no negativas y sin fallos preexistentes. Detección usa el origen definido para cada tipo; recuperación parte de restauración. Los episodios se solapan y no son réplicas independientes.", registry)


def show_cases(start, end):
    for i, response in list(enumerate(load()))[start:end]:
        print(f"CASE {i:03} {response['scenario']}/{response['mode']}/R{response['repetition']} {response['question_id']} task={response['task_id']}")
        print("FACTS", {o['key']:o['value'] for o in response['evidence']})
        print("BASELINE", {k:v.get("value") for k,v in response["snapshot"].get("session_baseline", {}).items()})
        print("RAW", response["raw_output"])


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=35)
    args = parser.parse_args()
    if args.prepare:
        prepare()
    else:
        show_cases(args.start, args.end)
