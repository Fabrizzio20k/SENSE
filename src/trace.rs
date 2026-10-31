use crate::{Result, contracts::*, orchestrator::SenseOrchestrator, storage::ExperimentLog};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    io::{Seek, SeekFrom, Write},
    path::Path,
};
use zip::{ZipWriter, write::SimpleFileOptions};
pub fn sample_document(c: &mut SenseOrchestrator, now: f64) -> Value {
    let ctx = c.context.snapshot(now).document;
    let r = &c.resources;
    let tasks = c.tasks.view(now);
    let raw = &c.last_raw_presence;
    let mut out = json!({"timestamp_utc":ctx["created_at"],"elapsed_s":rounded(now-c.started,3),"fsm_state":c.fsm,"conflict_status":ctx["conflict"],"active_question":list(&tasks["active"]).iter().map(|t|t["question_id"].clone()).collect::<Vec<_>>(),"information_need":c.policy.needs.as_object().unwrap().values().filter(|n|n["status"]=="PENDING").map(|n|n["need_id"].clone()).collect::<Vec<_>>(),"environment_event_active":ctx["environment_conditions"].as_object().unwrap().values().any(|v|v["state"]=="ACTIVE"||v["state"]=="RECOVERING"),"cpu_percent":r["cpu_total_percent"],"ram_used_mb":r["ram_used_mb"],"ram_available_mb":r["available_mb"],"swap_mb":r["swap_used_mb"],"pi_temp_c":r["temperature_c"],"throttled":r["throttled"],"resource_timestamp_utc":r["sampled_at"],"gemma_processes":r.get("gemma_processes").unwrap_or(&json!([])),"resource_age_s":r["sampled_monotonic"].as_f64().map(|t|rounded((now-t).max(0.),3)),"queued_tasks":tasks["queued"],"sample_status":"OBSERVED","component_health":c.health.components,"fault_ids":c.faults.records.as_object().unwrap().values().filter(|f|!truth(&f["restored_at"])).map(|f|f["fault_id"].clone()).collect::<Vec<_>>(),"presence_source":if c.manual_presence.is_some(){"MANUAL_CONTROL"}else{"RADAR"},"manual_near":c.manual_near,"radar_raw_presence":raw["value"],"radar_raw_observation_id":raw["observation_id"],"radar_raw_observed_at":raw["captured_at"],"radar_raw_age_s":if raw.is_null(){None}else{Some(rounded((now-c.raw_presence_received+c.raw_presence_age).max(0.),3))},"radar_raw_distance_cm":raw["metadata"]["trigger_distance_cm"]});
    if let Some(m) = r["main"].as_object() {
        for (k, v) in m {
            out[format!("process_{k}")] = v.clone();
        }
    }
    for (lane, agent) in [("vision", "VisionAgent"), ("gemma", "InterpretationAgent")] {
        let task = list(&tasks["active"])
            .into_iter()
            .find(|t| t["agent"] == agent)
            .unwrap_or(Value::Null);
        out[format!("{lane}_worker_state")] = task.get("status").cloned().unwrap_or(json!("IDLE"));
        out[format!("{lane}_task_id")] = task["command_id"].clone();
        out[format!("{lane}_task_simulated")] = json!(truth(&task["simulated"]));
    }
    for (key, name) in [
        ("temperature", "temperature_c"),
        ("humidity", "humidity_pct"),
        ("aqi", "aqi"),
        ("tvoc", "tvoc_ppb"),
        ("eco2", "eco2_ppm_equiv"),
        ("presence", "presence"),
        ("count", "visible_count"),
    ] {
        let obs = &ctx["observations"][key];
        out[name] = obs["value"].clone();
        for (source, suffix) in [
            ("observation_id", "observation_id"),
            ("captured_at", "observed_at"),
            ("age_seconds", "age_s"),
            ("status", "status"),
        ] {
            out[format!("{key}_{suffix}")] =
                obs.get(source).cloned().unwrap_or(if source == "status" {
                    json!("UNKNOWN")
                } else {
                    Value::Null
                });
        }
    }
    let radar = &ctx["observations"]["presence"]["metadata"];
    out["distance_cm"] = radar["trigger_distance_cm"].clone();
    out["radar_status"] = out["presence_status"].clone();
    out["radar_state_code"] = radar["state_code"].clone();
    out["movement"] = if radar["state_code"].as_u64().is_some_and(|v| v <= 3) {
        json!([1, 3].contains(&radar["state_code"].as_u64().unwrap()))
    } else {
        Value::Null
    };
    out["sensor_data_status"] =
        json!(
            if ["temperature", "humidity", "aqi", "tvoc", "eco2", "presence"]
                .iter()
                .all(|k| out[format!("{k}_status")] == "VALID")
            {
                "VALID"
            } else {
                "PARTIAL"
            }
        );
    for k in [
        "motion_distance_cm",
        "static_distance_cm",
        "total_distance_cm",
        "motion_energy",
        "static_energy",
    ] {
        out[k] = radar[k].clone();
    }
    out
}
pub fn cell(v: &Value) -> String {
    match v {
        Value::Null => String::new(),
        Value::Bool(v) => {
            if *v {
                "True".into()
            } else {
                "False".into()
            }
        }
        Value::String(s) => {
            if s.trim_start().starts_with(['=', '+', '-', '@']) {
                format!("'{s}")
            } else {
                s.clone()
            }
        }
        _ => v.to_string(),
    }
}
fn options() -> SimpleFileOptions {
    SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated)
}
fn write_csv<W: Write + Seek>(
    z: &mut ZipWriter<W>,
    name: &str,
    fields: &[String],
    rows: impl IntoIterator<Item = Result<Value>>,
) -> Result<()> {
    z.start_file(format!("{name}.csv"), options())?;
    z.write_all(&[0xef, 0xbb, 0xbf])?;
    let mut w = csv::WriterBuilder::new()
        .terminator(csv::Terminator::CRLF)
        .from_writer(z);
    w.write_record(fields)?;
    for row in rows {
        let row = row?;
        w.write_record(fields.iter().map(|k| cell(&row[k])))?;
    }
    w.flush()?;
    Ok(())
}
fn headers(name: &str) -> Vec<String> {
    let v: Value = serde_json::from_str(include_str!("../sense/export_headers.json")).unwrap();
    list(&v[name]).iter().map(|v| text(v).into()).collect()
}
fn merge(target: &mut Value, source: &Value) {
    target
        .as_object_mut()
        .unwrap()
        .extend(source.as_object().unwrap().clone());
}
pub fn export_csv_zip(path: &Path, id: &str) -> Result<std::fs::File> {
    export_csv_zip_snapshot(path, id, || {})
}
fn export_csv_zip_snapshot(
    path: &Path,
    id: &str,
    after_snapshot: impl FnOnce(),
) -> Result<std::fs::File> {
    let mut out = tempfile::tempfile()?;
    let log = ExperimentLog::reader(path)?;
    log.db.execute_batch("BEGIN")?;
    let mut run = log.run(id)?.ok_or("Ejecución no encontrada.")?;
    let cutoff: Option<i64> = log.db.query_row(
        "SELECT max(sequence) FROM events WHERE run_id=?",
        [id],
        |r| r.get(0),
    )?;
    after_snapshot();
    let count: i64 = log.db.query_row(
        "SELECT count(*) FROM samples_1s WHERE run_id=?",
        [id],
        |r| r.get(0),
    )?;
    run["export_event_sequence"] = json!(cutoff);
    run["exported_samples"] = json!(count);
    let mut z = ZipWriter::new(&mut out);
    z.start_file("metadata.json", options())?;
    z.write_all(serde_json::to_string_pretty(&run)?.as_bytes())?;
    z.start_file("replay-manifest.json", options())?;
    z.write_all(json!({"schema":"sense-replay.v1","run_id":id,"event_sequence":cutoff,"files":["metadata.json","samples_1s.csv","events.csv","ground_truth.csv","power_readings.csv","observer_requests.csv"],"images_stored":false}).to_string().as_bytes())?;
    z.start_file("LEEME.txt", options())?;
    z.write_all("Snapshot de la ejecución al descargar. CSV UTF-8; celdas vacías = dato desconocido.\nPotencia W manual: hora observada distinta de hora registrada; no es energía ni consumo exclusivo de IA.\nsamples_1s conserva datos retenidos con edad y referencia original. Segundos ausentes: SAMPLE_GAP en events.\nPersonas: región observada, no necesariamente ocupación del aula. Fotografías no almacenadas.\nJSON anidado se conserva en columnas *_json. Tareas tardías pueden llegar después de esta descarga.\nReplay: importa este ZIP en la pestaña Replay; el manifiesto versiona las mismas fuentes CSV, sin duplicarlas.\n".as_bytes())?;
    let mut samples = log
        .db
        .prepare("SELECT payload FROM samples_1s WHERE run_id=? ORDER BY second")?;
    let mut sample_rows = samples.query([id])?;
    let first = sample_rows
        .next()?
        .map(|r| r.get::<_, String>(0))
        .transpose()?
        .map(|s| serde_json::from_str::<Value>(&s))
        .transpose()?;
    let fields = if let Some(ref first) = first {
        let mut f = vec!["run_id".into()];
        f.extend(first.as_object().unwrap().keys().cloned());
        f
    } else {
        headers("samples_1s")
    };
    let rows = first
        .into_iter()
        .map(Ok)
        .chain(std::iter::from_fn(|| match sample_rows.next() {
            Ok(Some(r)) => Some(
                r.get::<_, String>(0)
                    .map_err(Into::into)
                    .and_then(|s| serde_json::from_str(&s).map_err(Into::into)),
            ),
            Ok(None) => None,
            Err(e) => Some(Err(e.into())),
        }))
        .map(|r: Result<Value>| {
            r.map(|mut r| {
                r["run_id"] = json!(id);
                r
            })
        });
    write_csv(&mut z, "samples_1s", &fields, rows)?;
    let mut tasks: BTreeMap<String, Value> = BTreeMap::new();
    let mut observations: BTreeMap<String, Value> = BTreeMap::new();
    let mut images: BTreeMap<String, Value> = BTreeMap::new();
    let mut faults: BTreeMap<String, Value> = BTreeMap::new();
    let mut stmt = log.db.prepare(
        "SELECT sequence,timestamp,type,payload FROM events WHERE run_id=? ORDER BY sequence",
    )?;
    let mut rows = stmt.query([id])?;
    let events = std::iter::from_fn(|| match rows.next() {
        Ok(Some(r)) => Some((|| -> Result<Value> {
            let seq: i64 = r.get(0)?;
            let at: String = r.get(1)?;
            let kind: String = r.get(2)?;
            let p: Value = serde_json::from_str(&r.get::<_, String>(3)?)?;
            if kind.starts_with("FAULT_") && truth(&p["fault_id"]) {
                let mut f = p.clone();
                f["run_id"] = json!(id);
                faults.insert(text(&p["fault_id"]).into(), f);
            }
            let command = if p["command"].is_object() {
                Some(&p["command"])
            } else if kind == "COMMAND_ISSUED" {
                Some(&p)
            } else {
                None
            };
            if let Some(c) = command {
                let task_id = text(&c["command_id"]);
                let t = tasks
                    .entry(task_id.into())
                    .or_insert(json!({"run_id":id,"task_id":task_id}));
                let para = &c["parameters"];
                merge(
                    t,
                    &json!({"agent":c["target_agent"],"action":c["action"],"reason":c["reason"],"requested_at":c["created_at"],"cycle_id":c["correlation_id"],"question_id":para["question_id"],"snapshot_id":para["snapshot_id"],"fault_id":para["fault_id"],"simulated":para.get("simulated").unwrap_or(&json!(false)),"model_executed":para["model_executed"]}),
                );
                if kind.starts_with("TASK_") {
                    t["status"] = json!(kind);
                    for k in [
                        "started_at",
                        "completed_at",
                        "queue_seconds",
                        "duration_seconds",
                        "error",
                        "late",
                        "remote_execution_uncertain",
                    ] {
                        if let Some(v) = p.get(k) {
                            t[k] = v.clone();
                        }
                    }
                    if kind == "TASK_TIMEOUT" {
                        t["timed_out"] = json!(true);
                    }
                    if let Some(result) = p.get("result") {
                        t["result_json"] = result.clone();
                        for k in [
                            "image_id",
                            "model_id",
                            "runtime_model_id",
                            "validation_status",
                            "interpretation_id",
                            "capture_seconds",
                            "inference_seconds",
                        ] {
                            t[k] = result[k].clone();
                        }
                        t["visible_count"] = result["count"].clone();
                        if truth(&result["image_id"]) {
                            images.entry(text(&result["image_id"]).into()).or_insert(json!({"run_id":id,"task_id":task_id,"image_id":result["image_id"],"captured_at":result["captured_at"],"stored":false}));
                        }
                    }
                }
            } else if kind == "TASK_CANCELLED" {
                let tid = text(&p["command_id"]);
                let t = tasks
                    .entry(tid.into())
                    .or_insert(json!({"run_id":id,"task_id":tid}));
                t["status"] = json!(kind);
                t["cancelled"] = json!(true);
            }
            let mut add_obs = |key: &str, o: &Value| {
                let mut row = o.clone();
                row["run_id"] = json!(id);
                row["key"] = json!(key);
                observations
                    .entry(text(&o["observation_id"]).into())
                    .or_insert(row);
            };
            if ["OBSERVATIONS_RECEIVED", "CONTEXT_UPDATED"].contains(&kind.as_str()) {
                if let Some(m) = p["observations"].as_object() {
                    for (k, o) in m {
                        add_obs(k, o);
                    }
                }
                if truth(&p["raw_presence"]) {
                    add_obs("raw_presence", &p["raw_presence"]);
                }
            } else if kind == "VISION_OBSERVATION" {
                add_obs("count", &p["observation"]);
            }
            let task_id = command.map(|c| c["command_id"].clone()).unwrap_or_else(|| {
                ["command_id", "task_id"]
                    .iter()
                    .find_map(|k| p.get(*k).filter(|v| truth(v)).cloned())
                    .unwrap_or_else(|| {
                        if kind == "SLM_INPUT" {
                            p["request_id"].clone()
                        } else {
                            Value::Null
                        }
                    })
            });
            let mut event_at = ["timestamp", "captured_at", "sampled_at"]
                .iter()
                .find_map(|k| p.get(*k).filter(|v| truth(v)).cloned())
                .unwrap_or(json!(at));
            let specific = match kind.as_str() {
                "TASK_STARTED" => Some("started_at"),
                "TASK_COMPLETED" | "TASK_FAILED" => Some("completed_at"),
                "COMMAND_ISSUED" => Some("created_at"),
                _ => None,
            };
            if let Some(k) = specific
                && truth(&p[k])
            {
                event_at = p[k].clone();
            }
            Ok(
                json!({"run_id":id,"sequence":seq,"timestamp_utc":event_at,"recorded_at":at,"type":kind,"task_id":task_id,"event_id":if kind=="OBSERVER_REQUESTED"{Value::Null}else{p["event_id"].clone()},"payload_json":p}),
            )
        })()),
        Ok(None) => None,
        Err(e) => Some(Err(e.into())),
    });
    write_csv(&mut z, "events", &headers("events"), events)?;
    for (name, table) in [
        ("faults", faults),
        ("inference_tasks", tasks),
        ("observations", observations),
        ("images", images),
    ] {
        write_csv(&mut z, name, &headers(name), table.into_values().map(Ok))?;
    }
    let mut stmt=log.db.prepare("SELECT timestamp,payload FROM events WHERE run_id=? AND type='RESULT_PUBLISHED' ORDER BY sequence")?;
    let mut rows = stmt.query([id])?;
    let mut pending_answers = std::collections::VecDeque::new();
    let answers = std::iter::from_fn(|| {
        loop {
            if let Some(answer) = pending_answers.pop_front() {
                return Some(Ok(answer));
            }
            let row = match rows.next() {
                Ok(Some(row)) => row,
                Ok(None) => return None,
                Err(e) => return Some(Err(e.into())),
            };
            let parsed = (|| -> Result<()> {
                let at: String = row.get(0)?;
                let payload: Value = serde_json::from_str(&row.get::<_, String>(1)?)?;
                if let Some(answers) = payload["answers"].as_object() {
                    for (question, answer) in answers {
                        let mut answer = answer.clone();
                        merge(
                            &mut answer,
                            &json!({"run_id":id,"timestamp_utc":at,"cycle_id":payload["cycle_id"],"question_id":question}),
                        );
                        pending_answers.push_back(answer);
                    }
                }
                Ok(())
            })();
            if let Err(e) = parsed {
                return Some(Err(e));
            }
        }
    });
    write_csv(
        &mut z,
        "question_results",
        &headers("question_results"),
        answers,
    )?;
    let mut stmt = log.db.prepare(
        "SELECT record_id,timestamp,kind,payload FROM human_records WHERE run_id=? ORDER BY rowid",
    )?;
    let mut rows = stmt.query([id])?;
    let mut records = vec![];
    while let Some(r) = rows.next()? {
        let mut p: Value = serde_json::from_str(&r.get::<_, String>(3)?)?;
        merge(
            &mut p,
            &json!({"run_id":id,"record_id":r.get::<_,String>(0)?,"recorded_at":r.get::<_,String>(1)?,"kind":r.get::<_,String>(2)?}),
        );
        if p["kind"] == "EXTERNAL_POWER" {
            p["power_w"] = p["value"].clone();
        }
        records.push(p);
    }
    write_csv(
        &mut z,
        "ground_truth",
        &headers("ground_truth"),
        records
            .iter()
            .filter(|r| {
                r.get("visible_people").is_some()
                    || r.get("action").is_some()
                    || r["kind"] == "GROUND_TRUTH"
            })
            .cloned()
            .map(Ok),
    )?;
    write_csv(
        &mut z,
        "power_readings",
        &headers("power_readings"),
        records
            .into_iter()
            .filter(|r| {
                r.get("power_w").is_some()
                    || list(&r["unavailable_fields"]).contains(&json!("power_w"))
                    || ["EXTERNAL_POWER", "EXTERNAL_ENERGY"].contains(&text(&r["kind"]))
            })
            .map(Ok),
    )?;
    write_csv(
        &mut z,
        "observer_requests",
        &headers("observer_requests"),
        log.observer_requests(id, false)?.into_iter().map(Ok),
    )?;
    z.finish()?;
    log.db.execute_batch("ROLLBACK")?;
    out.seek(SeekFrom::Start(0))?;
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn live_zip_uses_one_snapshot_while_new_events_continue() {
        let temp = tempfile::tempdir().unwrap();
        let log = ExperimentLog::new(&temp.path().join("trace.sqlite3")).unwrap();
        log.begin(&json!({"run_id":"run","start_time":utc_now()}))
            .unwrap();
        log.event("run", "BEFORE_EXPORT", &json!({})).unwrap();
        let file = export_csv_zip_snapshot(&log.path, "run", || {
            log.event("run", "AFTER_EXPORT_SNAPSHOT", &json!({}))
                .unwrap();
        })
        .unwrap();
        let mut zip = zip::ZipArchive::new(file).unwrap();
        let mut csv = String::new();
        use std::io::Read;
        zip.by_name("events.csv")
            .unwrap()
            .read_to_string(&mut csv)
            .unwrap();
        assert!(csv.contains("BEFORE_EXPORT"));
        assert!(!csv.contains("AFTER_EXPORT_SNAPSHOT"));
        assert!(
            log.events("run", 0, 200)
                .unwrap()
                .iter()
                .any(|e| e["type"] == "AFTER_EXPORT_SNAPSHOT")
        );
    }
}
