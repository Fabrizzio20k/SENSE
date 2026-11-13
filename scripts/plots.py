"""Figuras descriptivas PNG/PDF con tres ejecuciones visibles por celda."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pandas as pd
import math

from common import boolean, number, timestamp

COLORS = {"A": "#29628b", "B": "#239281", "C": "#d19820", "D": "#8c62a9", "E": "#cb6842", "F": "#b04f6c"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titleweight": "bold", "pdf.fonttype": 42,
                     "axes.labelcolor": "#243442", "text.color": "#243442", "figure.facecolor": "white"})


def save(fig, folder, name, caption, registry):
    folder.mkdir(parents=True, exist_ok=True)
    fig.savefig(folder / f"{name}.png", dpi=220, bbox_inches="tight")
    fig.savefig(folder / f"{name}.pdf", bbox_inches="tight")
    registry.append({"file": f"{name}.png", "vector_file": f"{name}.pdf", "caption": caption})
    plt.close(fig)


def comparisons(rows, folder, registry):
    frame = pd.DataFrame(rows)
    specifications = [
        ("vision_completed_nonsimulated", "Visión completada no simulada", "Tareas por ejecución", "01_activaciones_vision"),
        ("text_completed_nonsimulated", "Interpretación textual completada", "Tareas por ejecución", "02_activaciones_texto"),
        ("multimodal_completed_nonsimulated", "Interpretación visual completada", "Tareas por ejecución", "03_activaciones_multimodal"),
        ("cpu_percent_median", "CPU de la máquina", "Mediana del % reportado", "04_cpu"),
        ("process_rss_mb_max", "Memoria del proceso principal", "RSS máximo observado (MiB)", "05_memoria"),
        ("power_time_weighted_w_covered", "Potencia media en intervalos cubiertos", "W estimados por integración", "06_potencia"),
        ("power_coverage_fraction", "Cobertura de integración eléctrica", "Fracción del intervalo de ejecución", "07_cobertura_potencia"),
        ("energy_estimated_wh_covered", "Energía estimada solo en intervalos cubiertos", "Wh · consultar cobertura", "08_energia_parcial"),
        ("count_mae", "Error absoluto de conteo en pares evaluables", "Personas visibles · MAE", "09_error_conteo"),
        ("vision_duration_median_s", "Duración mediana de tareas de visión", "s · completadas no simuladas", "10_latencia_vision"),
        ("text_duration_median_s", "Duración mediana de tareas textuales", "s · completadas no simuladas", "11_latencia_texto"),
        ("multimodal_duration_median_s", "Duración mediana de tareas multimodales", "s · completadas no simuladas", "12_latencia_multimodal"),
    ]
    for field, title, ylabel, name in specifications:
        fig, axes = plt.subplots(1, 3, figsize=(12, 3.6), layout="constrained", sharey=True)
        for ax, scenario in zip(axes, ("S1", "S2", "S3")):
            sub = frame[frame.scenario == scenario]
            for i, mode in enumerate("ABCDEF"):
                group = sub[sub["mode"] == mode]
                values = []
                for _, row in group.iterrows():
                    value = number(row.get(field))
                    if value is not None:
                        values.append(value)
                        ax.scatter(i+(int(row["repetition"])-2)*.14, value, color=COLORS[mode],
                                   marker=("o", "s", "^")[(int(row["repetition"])-1) % 3], s=40, zorder=3)
                        if field == "count_mae":
                            ax.annotate(f"n={int(row['count_pairs_n'])}", (i, value), xytext=(3, 5),
                                        textcoords="offset points", fontsize=6)
                if values:
                    median = float(pd.Series(values).median())
                    ax.plot([i-.26, i+.26], [median, median], color="#263442", lw=1.4)
                else:
                    ax.text(i, .03, "s/d", transform=ax.get_xaxis_transform(), ha="center", fontsize=8)
            ax.set(title=scenario, xticks=range(6), xticklabels=list("ABCDEF"), xlabel="Configuración")
            ax.grid(axis="y", alpha=.18)
        axes[0].set_ylabel(ylabel)
        fig.suptitle(title)
        fig.legend(handles=[Line2D([], [], ls="", marker=m, color="#526373", label=f"R{i}")
                            for i, m in enumerate(("o", "s", "^"), 1)], loc="outside lower center", ncol=3)
        save(fig, folder, name, title+". Cada punto es una ejecución; raya = mediana. s/d = sin datos evaluables; no equivale a cero. Configuraciones completas, sin atribución causal aislada.", registry)


def coverage(questions, folder, registry):
    df = pd.DataFrame(questions)
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), layout="constrained", sharey=True)
    last = None
    for ax, scenario in zip(axes, ("S1", "S2", "S3")):
        matrix = []
        for q in [f"Q{i}" for i in range(1, 8)]:
            values = []
            for mode in "ABCDEF":
                group = df[(df.scenario == scenario) & (df["mode"] == mode) & (df.question_id == q)]
                selected = group[group.status == "RESOLVED"]
                n_runs = df[(df.scenario == scenario) & (df["mode"] == mode)].run_id.nunique()
                applicable = group[~group.status.isin(["NOT_APPLICABLE", "UNOBSERVED"])].publications.sum()
                values.append(selected.run_fraction.sum()/n_runs if n_runs and applicable else float("nan"))
            matrix.append(values)
        last = ax.imshow(matrix, vmin=0, vmax=1, cmap="Blues", aspect="auto")
        for y, values in enumerate(matrix):
            for x, value in enumerate(values):
                ax.text(x, y, f"{100*value:.0f}%" if math.isfinite(value) else "N/A", ha="center", va="center", fontsize=8, color="white" if value > .6 else "#263442")
        ax.set(title=scenario, xticks=range(6), xticklabels=list("ABCDEF"), yticks=range(7),
               yticklabels=[f"Q{i}" for i in range(1, 8)], xlabel="Configuración")
    fig.colorbar(last, ax=axes, label="Fracción temporal operativa RESOLVED")
    fig.suptitle("Cobertura operativa de preguntas · no mide corrección")
    save(fig, folder, "13_cobertura_preguntas", "Media por ejecución de fracciones temporales RESOLVED; intervalos entre publicaciones cercanas. No representa exactitud semántica ni física; Q6 y Q7 son tareas distintas.", registry)


def count_scatter(pairs, folder, registry):
    valid = [row for row in pairs if row["pair_status"] == "PAIRED"]
    fig, axes = plt.subplots(1, 3, figsize=(6.2, 2.8), layout="constrained")
    for ax, scenario in zip(axes, ("S1", "S2", "S3")):
        values = [r for r in valid if r["scenario"] == scenario]
        if values:
            limit = max(max(r["human_count"], r["predicted_count"]) for r in values)+1
            ax.plot([0, limit], [0, limit], color="#a5aeb8", ls="--", lw=1)
            for mode in "ABCDEF":
                selected = [r for r in values if r["mode"] == mode]
                ax.scatter([r["human_count"] for r in selected], [r["predicted_count"] for r in selected],
                           alpha=.65, label=mode, s=28, color=COLORS[mode])
        else:
            ax.text(.5, .5, "Sin pares evaluables", transform=ax.transAxes, ha="center")
        ax.set(title=f"{scenario} · n={len(values)}", xlabel="Conteo humano", ylabel="Conteo YOLO")
        ax.title.set_fontsize(9)
        ax.xaxis.label.set_fontsize(8)
        ax.yaxis.label.set_fontsize(8)
        ax.tick_params(labelsize=7)
    axes[-1].legend(fontsize=7, loc="best") if valid else None
    save(fig, folder, "14_pares_conteo", "Referencias reconfirmadas, región coincidente y vínculo explícito a captura; sin vínculo, asociación temporal dentro de tolerancia. Los pares no son réplicas experimentales independientes.", registry)


def fault_plot(faults, folder, registry):
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), layout="constrained")
    for ax, field, label in zip(axes, ("detection_latency_numeric_s", "recovery_latency_numeric_s"),
                               ("Detección", "Recuperación")):
        components = sorted({r["component"]+" / "+r["kind"] for r in faults})
        for x, component in enumerate(components):
            selected = [r for r in faults if r["component"]+" / "+r["kind"] == component
                        and r["preexisting_failure_decoded"] is False and number(r.get(field)) is not None]
            ax.scatter([x+(i % 5-2)*.045 for i in range(len(selected))], [r[field] for r in selected], s=23, color="#29628b", alpha=.7)
            ax.text(x, .02, f"n={len(selected)}", transform=ax.get_xaxis_transform(), ha="center", fontsize=8)
        ax.set(xticks=range(len(components)), xticklabels=components, title=label, ylabel="Latencia registrada (s)")
        ax.tick_params(axis="x", rotation=40, labelsize=7)
    fig.suptitle("Fallos F · extremos observados, sin fallos preexistentes")
    save(fig, folder, "15_latencias_fallos", "Latencias registradas con extremos disponibles; detección usa orígenes diferentes según tipo de fallo. Solapamientos se conservan en la tabla; puntos no son réplicas independientes.", registry)


def semantic_review(summary, folder, registry):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), layout="constrained")
    verdicts = ["SUSTENTADA", "PARCIAL", "CONTRADICHA", "SIN_SUSTENTO", "NO_EVALUABLE"]
    for ax, question in zip(axes, ("Q6", "Q7")):
        selected = [row for row in summary["groups"] if row["question_id"] == question
                    and row["field"] in ("inferences", "observations", "summary", "raw_output")]
        if not selected:
            ax.text(.5, .5, "Sin codificación por fragmentos\nRúbrica por respuesta: figura cap4_calidad_gemma", ha="center", va="center", transform=ax.transAxes)
            ax.set_xticks([])
            ax.set_yticks([])
        else:
            counts = [sum(r["fragments"] for r in selected if r["verdict"] == category) for category in verdicts]
            ax.bar(range(5), counts, color=["#239281", "#d19820", "#b04f6c", "#cb6842", "#8c62a9"])
            ax.set_xticks(range(5), verdicts, rotation=30, ha="right", fontsize=8)
            ax.set_ylabel("Fragmentos revisados")
        ax.set_title(question)
    fig.suptitle("Codificación exploratoria de IA · tareas separadas")
    save(fig, folder, "16_revision_semantica_ia", "Solo fragmentos explícitamente codificados en revision_ia.csv, por tarea Q6/Q7. Recomendaciones y unknowns quedan en tablas, fuera de este recuento de enunciados. Pendientes no se convierten en aciertos ni errores.", registry)


def timeline(identity, samples, power_segments, pairs, faults, start, window, folder, registry):
    frame = pd.DataFrame(samples)
    frame.index = pd.to_numeric(frame.second)
    frame = frame.reindex(range(int(window)))
    x = pd.to_numeric(frame.elapsed_s, errors="coerce")/60
    fig, axes = plt.subplots(5, 1, figsize=(10, 10), sharex=True, layout="constrained")
    for field, label, color in (("visible_count", "YOLO retenido vigente", "#29628b"),
                                ("presence", "Presencia (1) / ausencia (0)", "#239281")):
        status_field = "count_status" if field == "visible_count" else "presence_status"
        y = pd.to_numeric(frame.get(field), errors="coerce")
        if status_field in frame:
            y = y.where(frame[status_field] == "VALID")
        axes[0].plot(x, y, label=label, color=color, lw=1.1, drawstyle="steps-post")
    human = [r for r in pairs if r.get("human_time") and r.get("human_count") is not None
             and r["pair_status"] not in ("REPEATED_UNVERIFIED", "UNAVAILABLE", "OUTSIDE_RUN")]
    axes[0].scatter([((r["capture_epoch"] if r.get("link_method") == "task_id" else timestamp(r["human_time"]))-start)/60 for r in human], [r["human_count"] for r in human],
                    marker="x", color="#b04f6c", s=22, label="Referencia humana puntual")
    axes[0].set_ylabel("Presencia / conteo")
    axes[0].legend(fontsize=7, loc="upper right")
    for ax, field, status, label, color in ((axes[1], "temperature_c", "temperature_status", "Temperatura (°C)", "#cb6842"),
                                          (axes[2], "eco2_ppm_equiv", "eco2_status", "eCO₂ estimado (ppm eq.)", "#8c62a9")):
        y = pd.to_numeric(frame[field], errors="coerce").where(frame[status] == "VALID")
        ax.plot(x, y, lw=1, color=color)
        ax.set_ylabel(label)
    axes[3].plot(x, pd.to_numeric(frame.cpu_percent, errors="coerce"), color="#29628b", lw=.8)
    axes[3].set_ylabel("CPU máquina (%)")
    for segment in power_segments:
        axes[4].plot([(segment["from_epoch"]-start)/60, (segment["to_epoch"]-start)/60],
                     [segment["from_w"], segment["to_w"]], color="#239281", lw=1.3)
    axes[4].set(ylabel="Potencia manual (W)", xlabel="Tiempo desde inicio (min)")
    for fault in faults:
        left, right = fault.get("activation_s"), fault.get("restore_s")
        if left is not None:
            for ax in axes:
                ax.axvspan(left/60, (right if right is not None else window)/60, alpha=.055, color="#b04f6c")
    for ax in axes:
        ax.grid(alpha=.15)
        ax.set_xlim(0, window/60)
    fig.suptitle(f"{identity['scenario']} · {identity['mode']} · R{identity['repetition']}\n{identity['run_id']}", fontsize=11)
    name = f"cronologia_{identity['scenario']}_{identity['mode']}_R{identity['repetition']}"
    save(fig, folder, name, "Cronología descriptiva de una ejecución. Valores contextuales retenidos con validez; potencia solo en segmentos integrables, sin extrapolación. Sombreado = fallo activado hasta restauración o cierre; puede haber solapamientos.", registry)
