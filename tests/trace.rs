mod common;
use common::*;
use sense_people_counter::{
    contracts::*,
    protocol,
    storage::ExperimentLog,
    trace::{cell, export_csv_zip},
};
use serde_json::{Value, json};
use std::{
    io::Read,
    sync::{Arc, mpsc},
};
fn csv_rows(h: &Harness, name: &str) -> Vec<Value> {
    let file = export_csv_zip(&h.c.log.path, text(&h.c.run["run_id"])).unwrap();
    let mut zip = zip::ZipArchive::new(file).unwrap();
    let mut text = String::new();
    zip.by_name(&format!("{name}.csv"))
        .unwrap()
        .read_to_string(&mut text)
        .unwrap();
    let mut rdr = csv::Reader::from_reader(text.trim_start_matches('\u{feff}').as_bytes());
    let fields = rdr.headers().unwrap().clone();
    rdr.records()
        .map(|r| {
            let r = r.unwrap();
            json!(
                fields
                    .iter()
                    .zip(r.iter())
                    .map(|(k, v)| (k.to_owned(), json!(v)))
                    .collect::<serde_json::Map<_, _>>()
            )
        })
        .collect()
}
#[test]
fn full_1800_second_run_stops_without_browser_and_exports_csv() {
    let mut h = Harness::new();
    h.disable_models();
    let r = h.guided("B", "S2", 1);
    for s in 0..=1800 {
        h.step(s as f64);
    }
    assert!(!h.c.running());
    let q = h.c.log.quality(text(&r["run_id"])).unwrap();
    assert_eq!(q["samples"], 1800);
    assert_eq!(q["missing_samples"], 0);
    assert_eq!(h.c.run["finish_reason"], "MAX_RUN_DURATION");
    let requests =
        h.c.log
            .observer_requests(text(&r["run_id"]), false)
            .unwrap();
    assert_eq!(
        requests
            .iter()
            .filter(|r| text(&r["reason"]).starts_with("PERIODIC_W:"))
            .count(),
        29
    );
    assert_eq!(
        requests
            .iter()
            .filter(|r| text(&r["reason"]).starts_with("SCENARIO_CHECKPOINT:"))
            .count(),
        0
    );
    assert_eq!(requests.last().unwrap()["reason"], "RUN_FINAL");
    assert!(!truth(&q["record_complete"]));
    assert_eq!(csv_rows(&h, "samples_1s").len(), 1800);
    let file = export_csv_zip(&h.c.log.path, text(&r["run_id"])).unwrap();
    let mut zip = zip::ZipArchive::new(file).unwrap();
    let mut manifest = String::new();
    zip.by_name("replay-manifest.json")
        .unwrap()
        .read_to_string(&mut manifest)
        .unwrap();
    let m: Value = serde_json::from_str(&manifest).unwrap();
    assert_eq!(m["schema"], "sense-replay.v1");
    assert_eq!(m["run_id"], r["run_id"]);
    for f in list(&m["files"]) {
        assert!(zip.by_name(text(&f)).is_ok());
    }
}
#[test]
fn gaps_remain_missing_and_retained_readings_age() {
    let mut h = Harness::new();
    h.disable_models();
    let r = h.guided("B", "S2", 1);
    h.ingest(0., None);
    h.step(1.);
    h.step(4.);
    h.c.stop("USER_STOP", h.now + 5.).unwrap();
    let samples: Vec<_> = h
        .events()
        .into_iter()
        .filter(|e| e["type"] == "SAMPLE_1S")
        .map(|e| e["payload"].clone())
        .collect();
    assert_eq!(
        samples
            .iter()
            .map(|s| number(&s["second"]) as i64)
            .collect::<Vec<_>>(),
        vec![0, 1, 4]
    );
    assert_eq!(
        samples[2]["temperature_observation_id"],
        samples[1]["temperature_observation_id"]
    );
    assert!(number(&samples[2]["temperature_age_s"]) > number(&samples[1]["temperature_age_s"]));
    assert!(samples[2]["visible_count"].is_null());
    assert_eq!(
        h.c.log.quality(text(&r["run_id"])).unwrap()["missing_samples"],
        2
    );
    h.event("SAMPLE_GAP");
}

#[test]
fn sampled_presence_is_exported_without_manual_tags() {
    let mut h = Harness::new();
    h.disable_models();
    h.start("C");
    h.c.set_presence(&json!(false), h.now, &Value::Null)
        .unwrap();
    h.step(0.);
    h.step(1.);
    h.step(1.5);
    let latest = h.c.context.observations["presence"]["observation_id"].clone();
    let event = h.event("OBSERVATIONS_RECEIVED");
    assert_eq!(
        event["payload"]["observations"]["presence"]["observation_id"],
        latest
    );
    let observations = csv_rows(&h, "observations");
    let row = observations
        .iter()
        .find(|r| r["observation_id"] == latest)
        .unwrap();
    assert_eq!(row["key"], "presence");
    assert_eq!(row["source_agent"], "PresenceAgent");
    let metadata: Value = serde_json::from_str(text(&row["metadata"])).unwrap();
    assert_eq!(metadata, json!({}));
    let sample = sense_people_counter::trace::sample_document(&mut h.c, h.now + 1.5);
    assert_eq!(sample["presence_source"], "RADAR");
    assert!(sample.get("manual_near").is_none());
    for table in ["observations", "samples_1s", "events", "question_results"] {
        let rows = csv_rows(&h, table);
        let exported = serde_json::to_string(&rows).unwrap();
        for tag in [
            "MANUAL_CONTROL",
            "OperatorControl",
            "HELD_MANUAL_CONTROL",
            "PRESENCE_CONTROL_SAMPLED",
            "control_set_at",
            "manual_near",
        ] {
            assert!(!exported.contains(tag), "{table}: {tag}");
        }
    }
    assert_eq!(
        h.events()
            .iter()
            .filter(|e| e["type"] == "OBSERVATIONS_RECEIVED")
            .count(),
        1
    );
}
#[test]
fn observations_are_validated_persisted_and_never_feed_context() {
    let mut h = Harness::new();
    let r = h.guided("B", "S2", 1);
    let id = text(&r["run_id"]);
    let request =
        h.c.log
            .request_observer(id, "TEST", &["power_w", "visible_people"], None, None, None)
            .unwrap();
    let before = h.c.context.observations.clone();
    for changes in [
        json!({"power_w":true}),
        json!({"power_w":null}),
        json!({"visible_people":-1}),
        json!({"unavailable_fields":["power_w"],"power_w":null}),
        json!({"region":""}),
    ] {
        let mut p = initial();
        p.as_object_mut()
            .unwrap()
            .extend(changes.as_object().unwrap().clone());
        assert!(h.c.log.resolve_observer(id, &request, &p).is_err());
    }
    let mut p = initial();
    p["power_w"] = json!(11.5);
    p["visible_people"] = json!(3);
    p["notes"] = json!("=2+2");
    h.c.log.resolve_observer(id, &request, &p).unwrap();
    assert_eq!(h.c.context.observations, before);
    assert!(h.c.log.resolve_observer(id, &request, &p).is_err());
    let power = csv_rows(&h, "power_readings");
    let row = power.last().unwrap();
    assert_eq!(row["power_w"], "11.5");
    assert_eq!(row["instrument"], "Medidor");
    assert_eq!(row["notes"], "'=2+2");
    assert_eq!(row["request_id"], request);
}
#[test]
fn unavailable_is_explicit_and_restart_keeps_pending_requests() {
    let mut h = Harness::new();
    let r = h.guided("B", "S2", 1);
    let id = text(&r["run_id"]);
    let req =
        h.c.log
            .request_observer(id, "TEST", &["power_w"], None, None, None)
            .unwrap();
    h.c.log.resolve_observer(id,&req,&json!({"observed_at":utc_now(),"power_w":null,"unavailable_fields":["power_w"],"missing_reason":"No llegué a leerlo"})).unwrap();
    assert_eq!(h.c.log.quality(id).unwrap()["unavailable_observations"], 1);
    let pending =
        h.c.log
            .request_observer(id, "TEST_2", &["power_w"], None, None, None)
            .unwrap();
    let second = ExperimentLog::new(&h.c.log.path).unwrap();
    assert_eq!(second.run(id).unwrap().unwrap()["status"], "INTERRUPTED");
    assert!(
        second
            .observer_requests(id, true)
            .unwrap()
            .iter()
            .any(|r| r["request_id"] == pending)
    );
    assert!(!truth(&second.quality(id).unwrap()["record_complete"]));
}
#[test]
fn real_worker_start_failure_and_timing_are_linked_to_requests() {
    let mut h = Harness::new();
    h.c.adapters.detector = Arc::new(|_| Err("fallo controlado".into()));
    let r = h.guided("A", "S2", 1);
    h.finish_vision();
    let started = h.event("TASK_STARTED")["payload"].clone();
    let failed = h.event("TASK_FAILED")["payload"].clone();
    assert_eq!(
        started["command"]["command_id"],
        failed["command"]["command_id"]
    );
    assert!(!failed["completed_at"].is_null());
    assert!(number(&failed["duration_seconds"]) >= 0.);
    let reqs =
        h.c.log
            .observer_requests(text(&r["run_id"]), false)
            .unwrap();
    assert_eq!(
        reqs.iter()
            .filter(|r| text(&r["reason"]).starts_with("VISION_TASK_"))
            .count(),
        2
    );
    assert_eq!(
        reqs.iter()
            .find(|r| r["reason"] == "VISION_TASK_STARTED")
            .unwrap()["requested_at"],
        started["started_at"]
    );
    assert_eq!(
        reqs.iter()
            .find(|r| r["reason"] == "VISION_TASK_FAILED")
            .unwrap()["requested_at"],
        failed["completed_at"]
    );
    assert!(
        h.c.set_presence(&json!(true), h.now + 0.5, &Value::Null)
            .is_err()
    );
}
#[test]
fn previous_readings_survive_reload_and_ignore_missing_and_other_runs() {
    let mut h = Harness::new();
    let r = h.guided("B", "S2", 1);
    let id = text(&r["run_id"]);
    assert_eq!(
        h.c.log.observer_previous(id).unwrap(),
        json!({"power_w":0,"visible_people":0})
    );
    let request =
        h.c.log
            .request_observer(id, "TEST", &["power_w", "visible_people"], None, None, None)
            .unwrap();
    let mut p = initial();
    p["power_w"] = json!(12);
    p["visible_people"] = json!(2);
    h.c.log.resolve_observer(id, &request, &p).unwrap();
    let missing =
        h.c.log
            .request_observer(id, "TEST", &["power_w"], None, None, None)
            .unwrap();
    p["power_w"] = Value::Null;
    p["unavailable_fields"] = json!(["power_w"]);
    p["missing_reason"] = json!("No pude leer");
    h.c.log.resolve_observer(id, &missing, &p).unwrap();
    let other = ExperimentLog::new(&h.c.log.path).unwrap();
    assert_eq!(
        other.observer_previous(id).unwrap(),
        json!({"power_w":12,"visible_people":2})
    );
    assert_eq!(other.observer_previous("other-run").unwrap(), json!({}));
}
#[test]
fn event_time_is_fixed_and_repeated_readings_are_exported() {
    let mut h = Harness::new();
    let r = h.guided("B", "S2", 1);
    let at = "2026-10-27T12:00:00+00:00";
    let request =
        h.c.log
            .request_observer(
                text(&r["run_id"]),
                "TEST",
                &["power_w"],
                None,
                None,
                Some(at),
            )
            .unwrap();
    let mut p = initial();
    p["repeated_fields"] = json!(["power_w"]);
    p["event_at"] = json!("incorrect");
    let record =
        h.c.log
            .resolve_observer(text(&r["run_id"]), &request, &p)
            .unwrap();
    let e = h
        .events()
        .into_iter()
        .find(|e| e["record_id"] == record)
        .unwrap();
    assert_eq!(e["payload"]["event_at"], at);
    assert_ne!(e["payload"]["observed_at"], at);
    let rows = csv_rows(&h, "power_readings");
    assert_eq!(rows.last().unwrap()["event_at"], at);
    assert_eq!(
        serde_json::from_str::<Value>(text(&rows.last().unwrap()["repeated_fields"])).unwrap(),
        json!(["power_w"])
    );
    for repeated in [
        json!(["action"]),
        json!(["power_w", "power_w"]),
        json!("power_w"),
        json!([true]),
        json!(["visible_people"]),
    ] {
        p["repeated_fields"] = repeated;
        assert!(protocol::validate_observation(&p, &["power_w".into()]).is_err());
    }
    for formula in ["=2+2", " +command", "-cmd", "@cmd"] {
        assert!(cell(&json!(formula)).starts_with('\''));
    }
}
#[test]
fn start_and_timestamp_validation() {
    let exp =
        json!({"guided":true,"scenario_id":"S2","repetition":1,"initial_observation":initial()});
    protocol::validate_guided_start(&exp).unwrap();
    for changes in [
        json!({"repetition":true}),
        json!({"scenario_id":"S4"}),
        json!({"initial_observation":null}),
        json!({"replaces_run_id":true}),
        json!({"replaces_run_id":""}),
        json!({"guided":false,"replaces_run_id":"old"}),
    ] {
        let mut p = exp.clone();
        p.as_object_mut()
            .unwrap()
            .extend(changes.as_object().unwrap().clone());
        assert!(protocol::validate_guided_start(&p).is_err());
    }
    let mut p = initial();
    p["power_observed_at"] = json!("2040-01-01T00:00:00Z");
    assert!(protocol::validate_observation(&p, &["power_w".into()]).is_err());
}
#[test]
fn completed_repetitions_require_explicit_remeasurement_and_keep_history() {
    let mut h = Harness::new();
    h.disable_models();
    let mut payload = json!({"guided":true,"scenario_id":"S2","mode":"C","repetition":2,"initial_observation":initial()});
    let early = h.guided("C", "S2", 2);
    h.c.stop("USER_STOP", h.now + 10.).unwrap();
    assert!(h.c.log.completed_repetitions().unwrap().is_empty());
    let first = h.guided("C", "S2", 2);
    h.c.stop("MAX_RUN_DURATION", h.now + 1800.).unwrap();
    assert!(h.c.log.completed_repetitions().unwrap().is_empty());
    let resolve = |h: &Harness, id: &str| {
        let mut observation = initial();
        observation["action"] = json!("Cierre observado");
        for request in h.c.log.observer_requests(id, true).unwrap() {
            h.c.log
                .resolve_observer(id, text(&request["request_id"]), &observation)
                .unwrap();
        }
    };
    resolve(&h, text(&first["run_id"]));
    assert!(
        h.c.log
            .request_observer(
                text(&first["run_id"]),
                "EXTRA",
                &["power_w"],
                None,
                None,
                None
            )
            .is_err()
    );
    assert_eq!(
        h.c.log.completed_repetitions().unwrap()[0]["run_id"],
        first["run_id"]
    );
    let before = h.c.run.clone();
    assert!(h.c.start("C", h.now, "session", "S2", &payload).is_err());
    assert_eq!(h.c.run, before);
    payload["replaces_run_id"] = json!("wrong-run");
    assert!(h.c.start("C", h.now, "session", "S2", &payload).is_err());
    payload["replaces_run_id"] = first["run_id"].clone();
    let aborted = h.c.start("C", h.now, "session", "S2", &payload).unwrap();
    h.c.stop("USER_STOP", h.now + 30.).unwrap();
    resolve(&h, text(&aborted["run_id"]));
    assert_eq!(
        h.c.log.completed_repetitions().unwrap()[0]["run_id"],
        first["run_id"]
    );
    let replacement = h.c.start("C", h.now, "session", "S2", &payload).unwrap();
    assert_eq!(replacement["replaces_run_id"], first["run_id"]);
    h.c.stop("MAX_RUN_DURATION", h.now + 1800.).unwrap();
    assert_eq!(
        h.c.log.completed_repetitions().unwrap()[0]["run_id"],
        first["run_id"]
    );
    resolve(&h, text(&replacement["run_id"]));
    let completed = h.c.log.completed_repetitions().unwrap();
    assert_eq!(completed.len(), 1);
    assert_eq!(completed[0]["run_id"], replacement["run_id"]);
    assert!(h.c.start("C", h.now, "session", "S2", &payload).is_err());
    assert_eq!(
        h.c.log.run(text(&early["run_id"])).unwrap().unwrap()["finish_reason"],
        "USER_STOP"
    );
    assert_eq!(
        h.c.log.run(text(&first["run_id"])).unwrap().unwrap()["finish_reason"],
        "MAX_RUN_DURATION"
    );
    assert!(export_csv_zip(&h.c.log.path, text(&first["run_id"])).is_ok());
    // El bloqueo no depende de las últimas 100 filas del historial ni de la memoria del proceso.
    for _ in 0..101 {
        h.c.log
            .begin(&json!({"run_id":identifier(),"start_time":utc_now()}))
            .unwrap();
    }
    let reopened = ExperimentLog::reader(&h.c.log.path).unwrap();
    assert_eq!(reopened.completed_repetitions().unwrap(), completed);
    assert_eq!(list(&reopened.runs().unwrap()).len(), 100);
    let mut other = payload.clone();
    other["mode"] = json!("D");
    other.as_object_mut().unwrap().remove("replaces_run_id");
    reopened.validate_repetition_start(&other).unwrap();
    other["mode"] = json!("C");
    other["repetition"] = json!(3);
    reopened.validate_repetition_start(&other).unwrap();
}
#[test]
fn deadline_cancels_queue_before_poll_can_start_another_inference() {
    let mut h = Harness::new();
    h.disable_models();
    h.guided("D", "S2", 1);
    let (tx, rx) = mpsc::channel();
    let mut c = command("text");
    c["experiment_run_id"] = h.c.run["run_id"].clone();
    h.c.tasks.submit(
        "gemma",
        c.clone(),
        Box::new(move || {
            rx.recv()?;
            Ok(json!({}).into())
        }),
        "first".into(),
        h.now,
        1900.,
        None,
    );
    c["command_id"] = json!(identifier());
    h.c.tasks.submit(
        "gemma",
        c,
        Box::new(|| panic!("queued inference ran after stop")),
        "second".into(),
        h.now,
        1900.,
        None,
    );
    h.step(1800.);
    assert!(!h.c.running());
    assert!(h.c.tasks.pending.is_empty());
    tx.send(()).unwrap();
    h.finish_lane("gemma", 1801.);
}
